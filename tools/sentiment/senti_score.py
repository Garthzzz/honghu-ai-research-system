#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""散户层股吧打分 — 分层抽样(热帖优先+保底随机)→ 对样本内 attitude IS NULL 的 guba 行跑 DeepSeek 三分类。

抽样口径(替换旧"每桶前N条"有偏抽样,放量桶失真):
  按 (platform, company, bucket) 独立抽(senti3.select_sample):桶内 ≤50 全打;>50 取 heat 降序 Top40 + 真随机10。
  已打分算进配额(不浪费已有结果);给 senti_raw.sampled 置位(1入样本/0排除);打分只打 sampled=1 AND attitude IS NULL。
  ?? 幂等可重跑;真随机槽 seed 稳定可复现(senti3._stable_seed)。

复用 senti_direction 的 few-shot 股吧黑话 prompt + 噪声粗筛(同一打分器,尺度一致)。
看涨→1(正) 看跌→2(负) 中性→3(中),写回 senti_raw.attitude(attitude_src 已是 deepseek_self)。
星瀚记录自带原生 attitude,不在此打分(其 sampled 不影响打分,聚合按 attitude 统计)。只写 sentiment.db。

用法:python senti_score.py [--since 2026-06-01] [--max 240] [--batch 14] [--sample-only]
"""
from __future__ import annotations
import sys, argparse
from itertools import groupby
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dynamic"))
import common, senti3, retail_windows_v2
from senti_direction import prefilter, classify_batch
try:
    import llm_client
except Exception:
    llm_client = None

_LAB2ATT = {"看涨": 1, "看跌": 2, "中性": 3}
SINCE_FLOOR = "2026-06-01"        # 只补 6/1 起;6/1 前低覆盖存量桶不补(聚合标 usable=0)


def apply_sampling(con, since, cfg):
    """对 bucket_id>=since 的每个 (platform, company, bucket) 组分层抽样,置 senti_raw.sampled。幂等。
    只处理 retail+news 层(guba 是 DeepSeek 打分对象;sampled 门控 guba 打分)。
    单查询 + groupby(避免逐组往返),seed 稳定可复现。"""
    max_pb = int(cfg["max_per_bucket"]); top = int(cfg["top_by_heat"]); rf = int(cfg["random_floor"])
    rows = con.execute("""SELECT id, platform, company_id, bucket_id, COALESCE(heat_value,0) hv, attitude
        FROM senti_raw WHERE bucket_id >= ? AND source_layer IN ('retail','news')
        ORDER BY platform, company_id, bucket_id""", (since,)).fetchall()
    n_groups = n_trig = n_samp = n_excl = 0
    samp_ids, excl_ids = [], []
    for (plat, cid, bid), grp in groupby(rows, key=lambda r: (r["platform"], r["company_id"], r["bucket_id"])):
        items = [(r["id"], r["hv"], r["attitude"] is not None) for r in grp]
        n_groups += 1
        seed = senti3._stable_seed(f"{bid}|{plat}|{cid}")     # 稳定可复现 + 每独立单元不同
        samp, excl = senti3.select_sample(items, max_per_bucket=max_pb, top_by_heat=top,
                                          random_floor=rf, seed=seed)
        if excl:
            n_trig += 1                                       # 触发抽样(>50)的组
        samp_ids += [(i,) for i in samp]; excl_ids += [(i,) for i in excl]
        n_samp += len(samp); n_excl += len(excl)
    if samp_ids:
        con.executemany("UPDATE senti_raw SET sampled=1 WHERE id=?", samp_ids)
    if excl_ids:
        con.executemany("UPDATE senti_raw SET sampled=0 WHERE id=?", excl_ids)
    con.commit()
    return {"groups": n_groups, "triggered": n_trig, "sampled": n_samp, "excluded": n_excl}


def classify_rows_with_retries(
    con,
    rows,
    *,
    batch_size: int,
    retry_passes: int = 4,
    max_calls: int = 1200,
):
    """只重试模型未返回合法标签的行，并逐轮缩小批次。

    DeepSeek 偶尔会返回长度不匹配或不可解析的批量 JSON。旧实现直接留下空值，
    导致窗口虽然已有大量分数仍被永久标成未完成。这里保留每轮已成功结果，只把
    失败行送入下一轮；批次按 ``14 -> 7 -> 3 -> 1`` 收缩，避免重复计费和整批饥饿。
    返回 ``(labeled, pending_rows, pass_stats)``，最终仍失败的行保持 NULL，不造数。

    为避免模型全局故障时把数千条记录逐级拆成上万次无效请求，另有两层熔断：
    单轮至少检查 3 个初始批次（且不少于 42 行）仍零成功时停止；总模型调用数
    默认不超过 1200。小批局部解析失败仍会完整走 ``14 -> 7 -> 3 -> 1``。
    """
    pending = list(rows)
    labeled = 0
    stats = []
    passes = max(1, int(retry_passes))
    initial_batch = max(1, int(batch_size))
    call_budget = max(1, int(max_calls))
    call_count = 0
    zero_progress_floor = max(42, initial_batch * 3)
    for pass_index in range(passes):
        if not pending:
            break
        current_batch = max(1, initial_batch // (2 ** pass_index))
        attempted = len(pending)
        next_pending = []
        pass_labeled = 0
        halted = None
        for offset in range(0, len(pending), current_batch):
            if call_count >= call_budget:
                next_pending.extend(pending[offset:])
                halted = "call_budget_exhausted"
                break
            batch = pending[offset:offset + current_batch]
            call_count += 1
            try:
                results = classify_batch([row["title"] for row in batch])
            except Exception:
                results = [(None, None)] * len(batch)
            if len(results) != len(batch):
                results = [(None, None)] * len(batch)
            for row, (label, reason) in zip(batch, results):
                attitude = _LAB2ATT.get(label)
                if not attitude:
                    next_pending.append(row)
                    continue
                con.execute(
                    "UPDATE senti_raw SET attitude=?, reason=? WHERE id=?",
                    (attitude, (reason or "")[:120], row["id"]),
                )
                labeled += 1
                pass_labeled += 1
            con.commit()
        pending = next_pending
        stats.append({
            "pass": pass_index + 1,
            "batch": current_batch,
            "attempted": attempted,
            "labeled": pass_labeled,
            "remaining": len(pending),
            "calls": call_count,
            "halted": halted,
        })
        if halted:
            break
        if pass_labeled == 0 and attempted >= zero_progress_floor:
            stats[-1]["halted"] = "zero_progress_circuit_breaker"
            break
    return labeled, pending, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--max",
        type=int,
        default=None,
        help="最多打分数；legacy 默认 240，V2 window 默认不限；0 表示不限",
    )
    ap.add_argument(
        "--max-llm-calls",
        type=int,
        default=1200,
        help="单次评分进程最多调用模型的批次数；默认 1200，防止全局故障请求风暴",
    )
    ap.add_argument("--batch", type=int, default=14)
    ap.add_argument(
        "--retry-passes",
        type=int,
        default=4,
        help="模型批量输出无效时的总尝试轮数；默认 4（批次逐轮减半直至 1）",
    )
    ap.add_argument("--since", default=SINCE_FLOOR, help="抽样+打分起始日(只补 6/1 起;默认 2026-06-01)")
    ap.add_argument("--sample-only", action="store_true", help="只跑抽样置位,不调 LLM(调试/审计)")
    ap.add_argument("--skip-sample", action="store_true", help="跳过抽样置位(续跑分块:sampled 已置好,直接打分省开销)")
    ap.add_argument("--window-id", help="V2 window id；按公司轮转选样，杜绝全局 heat 饥饿")
    ap.add_argument("--per-company-target", type=int, help="V2 每家公司本轮上限；默认不限")
    ap.add_argument("--require-complete", action="store_true", help="V2 尚有未评分样本时返回非零")
    args = ap.parse_args()
    con = common.get_senti_db()
    common.assert_senti_only(con)                      # 门C
    cfg = senti3.load_sampling_config()

    # ── 1) 分层抽样:置 sampled(替换"前N条")──
    if not args.skip_sample:
        if args.window_id:
            st = retail_windows_v2.prepare_window_score_sample(
                con,
                args.window_id,
                max_per_company=int(cfg["max_per_bucket"]),
                top_by_heat=int(cfg["top_by_heat"]),
                random_floor=int(cfg["random_floor"]),
            )
            print(f"V2 窗口公平抽样:{st}")
        else:
            st = apply_sampling(con, args.since, cfg)
            print(f"抽样:组 {st['groups']}(触发抽样 {st['triggered']}/{st['groups']}={100*st['triggered']/max(st['groups'],1):.1f}%)"
                  f" → 入样本 {st['sampled']} / 排除 {st['excluded']}")
    if args.sample_only:
        con.close(); return 0

    # ── 2) 打分。V2 先按公司轮转，再在公司内按 heat 排序；legacy 保持旧行为。──
    candidate_stat = None
    if args.window_id:
        retail_windows_v2.ensure_schema(con)
        max_total = None if args.max in (None, 0) else args.max
        candidate_ids, candidate_stat = retail_windows_v2.fair_score_candidate_ids(
            con,
            args.window_id,
            max_total=max_total,
            per_company_target=args.per_company_target,
        )
        if candidate_ids:
            placeholders = ",".join("?" for _ in candidate_ids)
            by_id = {
                int(row["id"]): row
                for row in con.execute(
                    f"SELECT id,title FROM senti_raw WHERE id IN ({placeholders})", candidate_ids
                )
            }
            rows = [by_id[row_id] for row_id in candidate_ids if row_id in by_id]
        else:
            rows = []
        print(f"V2 公平选样:{candidate_stat}")
    else:
        legacy_max = 240 if args.max is None else args.max
        rows = con.execute("""SELECT id, title FROM senti_raw
            WHERE platform='guba' AND attitude IS NULL AND sampled=1
              AND title IS NOT NULL AND TRIM(title)<>'' AND bucket_id >= ?
            ORDER BY COALESCE(heat_value,0) DESC, publish_time DESC LIMIT ?""",
            (args.since, legacy_max if legacy_max != 0 else -1)).fetchall()
    print(f"待打标股吧行(样本内未打分):{len(rows)}")
    labeled = noise = 0

    to_llm = []
    for r in rows:
        need, _ = prefilter(r["title"])
        if not need:
            con.execute("UPDATE senti_raw SET attitude=3, reason='粗筛噪声' WHERE id=?", (r["id"],))
            noise += 1
        else:
            to_llm.append(r)
    con.commit()

    if not (llm_client and llm_client.enabled()):
        print(f"DeepSeek 未启用 → 仅粗筛中性 {noise};LLM 方向分留空(不造数)")
        remaining = len(to_llm)
        if args.window_id:
            _, after = retail_windows_v2.fair_score_candidate_ids(con, args.window_id, max_total=0)
            remaining = after["candidates"]
        con.close()
        return 3 if args.require_complete and args.window_id and remaining else 0

    labeled, retry_pending, retry_stats = classify_rows_with_retries(
        con,
        to_llm,
        batch_size=args.batch,
        retry_passes=args.retry_passes,
        max_calls=args.max_llm_calls,
    )
    for stat in retry_stats:
        print(
            "LLM 重试轮次 "
            f"{stat['pass']}: batch={stat['batch']} attempted={stat['attempted']} "
            f"labeled={stat['labeled']} remaining={stat['remaining']} "
            f"calls={stat['calls']}"
            + (f" halted={stat['halted']}" if stat.get("halted") else "")
        )

    cov = con.execute("SELECT COUNT(DISTINCT company_id) FROM senti_raw WHERE platform='guba' AND attitude IS NOT NULL").fetchone()[0]
    print(f"=== 股吧方向分:LLM打标 {labeled} / 粗筛中性 {noise} / 覆盖 {cov} 股 ===")
    if llm_client:
        print("DeepSeek usage:", getattr(llm_client, "USAGE", ""))
    remaining = 0
    if args.window_id:
        _, after = retail_windows_v2.fair_score_candidate_ids(con, args.window_id, max_total=0)
        remaining = after["remaining"] + after["selected"]
        print(f"V2 window 未评分剩余:{remaining}")
    con.close()
    return 4 if args.require_complete and remaining else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
