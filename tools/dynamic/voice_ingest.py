#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""KOL 入库 + 富化(信源链路重构 v4)。

微博 KOL 只走舆情 API；散户情绪不再抓取或计算微博。
候选帖幂等 upsert 到 voice_post(verbatim)→ 明确状态/退出码
→ ai_funnel.process_voice 富化(relevance + 摘要/翻译/tag,不丢行,置 is_ai_relevant)。
auth_expired/system failure 写告警并返回非零，供 scheduler 如实退避；
rate_limited/cached_stale/upstream_not_ready 返回稳定延期码 22，scheduler
只等待下一个 tick。最后一种状态表示正式舆情窗口仍在分页，并不是 KOL 抓取失败。

用法:python voice_ingest.py [--leader-id N] [--max-enrich 40] [--wait-for-api]
"""
from __future__ import annotations
import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # 就地,避免多模块重复包装导致 buffer 被 GC 关闭
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent.parent
DB = ROOT / "data" / "research.db"
CONFIG = ROOT / "tools" / "dynamic" / "config.yaml"
ALERTDIR = ROOT / "cache" / "dynamic_alerts"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "dynamic"))
sys.path.insert(0, str(ROOT / "tools" / "dynamic" / "fetchers"))
import yaml
from voice_fetcher import make_fetcher
import ai_funnel
from relevance_classifier import RelevanceClassifier
CFG = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
NOW = datetime.now().isoformat(timespec="seconds")
# relevance 闸只对这些 handle 生效(如马斯克);其余领袖只富化不丢
FILTER_HANDLES = {str(h).strip().lower().lstrip("@")
                  for h in (CFG.get("topic_gate", {}) or {}).get("voice_filter_handles", [])}

# ``api_miss`` means the filtered API request succeeded but this author had no
# record in the lookback window. It must remain visible for health diagnostics,
# yet must not pause a quiet author after three normal empty checks.
SUCCESS_STATUSES = {"ok", "empty", "api_miss", "ok_with_skips"}
DEFERRED_STATUSES = {"rate_limited", "cached_stale", "upstream_not_ready"}
EXIT_AUTH = 20
EXIT_SYSTEM = 21
EXIT_DEFERRED = 22
# Backwards-compatible name for callers/tests that treated 22 as rate-limit.
EXIT_RATE_LIMIT = EXIT_DEFERRED


@dataclass
class FetchOutcome:
    got: int
    inserted: int
    updated: int
    status: str
    detail: str = ""

    @property
    def ok(self) -> bool:
        return self.status in SUCCESS_STATUSES


def _upsert_candidates(con, leader, candidates, *, fetched_at: str) -> tuple[int, int]:
    """Atomically upsert raw voice fields without touching existing AI enrichment."""
    savepoint = "voice_candidate_upsert"
    con.execute(f"SAVEPOINT {savepoint}")
    inserted = updated = 0
    try:
        for candidate in candidates:
            post_id = str(candidate.get("post_id") or "").strip()
            if not post_id:
                continue
            exists = con.execute(
                "SELECT content_text FROM voice_post WHERE leader_id=? AND post_id=?",
                (leader["id"], post_id),
            ).fetchone()
            previous_content = str(exists[0] or "") if exists else ""
            candidate_content = str(candidate.get("content_text") or "")
            content_replaced = bool(
                exists
                and candidate_content != previous_content
                and len(candidate_content) >= len(previous_content)
            )
            has_media = candidate.get("has_media")
            if has_media is not None:
                has_media = 1 if has_media else 0
            con.execute(
                """INSERT INTO voice_post(
                     leader_id,post_url,post_id,posted_at,content_text,content_html,
                     has_media,fetch_timestamp,last_verified_at)
                   VALUES(?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(leader_id,post_id) DO UPDATE SET
                     post_url=CASE WHEN TRIM(COALESCE(excluded.post_url,''))<>''
                                   THEN excluded.post_url ELSE voice_post.post_url END,
                     posted_at=COALESCE(excluded.posted_at,voice_post.posted_at),
                     content_text=CASE
                       WHEN LENGTH(COALESCE(excluded.content_text,'')) >=
                            LENGTH(COALESCE(voice_post.content_text,''))
                       THEN excluded.content_text ELSE voice_post.content_text END,
                     content_html=CASE
                       WHEN LENGTH(COALESCE(excluded.content_html,'')) >
                            LENGTH(COALESCE(voice_post.content_html,''))
                       THEN excluded.content_html ELSE voice_post.content_html END,
                     has_media=COALESCE(excluded.has_media,voice_post.has_media),
                     fetch_timestamp=excluded.fetch_timestamp,
                     last_verified_at=COALESCE(excluded.last_verified_at,voice_post.last_verified_at)""",
                (
                    leader["id"],
                    candidate.get("post_url"),
                    post_id,
                    candidate.get("posted_at"),
                    candidate.get("content_text"),
                    candidate.get("content_html"),
                    has_media,
                    candidate.get("upstream_fetched_at") or fetched_at,
                    candidate.get("upstream_finished_at") or fetched_at,
                ),
            )
            if content_replaced:
                _clear_voice_enrichment(con, leader["id"], post_id)
            if exists:
                updated += 1
            else:
                inserted += 1
        con.execute(
            """UPDATE opinion_leader
               SET last_fetched_at=?,updated_at=?
               WHERE id=?""",
            (fetched_at, fetched_at, leader["id"]),
        )
        con.execute(f"RELEASE SAVEPOINT {savepoint}")
        return inserted, updated
    except Exception:
        con.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        con.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise


def _clear_voice_enrichment(con, leader_id: int, post_id: str) -> None:
    """Clear only columns derived from a raw body that was actually replaced."""
    derived = {
        "ai_tags_company",
        "ai_tags_industry",
        "ai_tags_event_id",
        "post_type",
        "ai_summary",
        "ai_summary_source_ids",
        "ai_summary_generated_at",
        "ai_tagged_by",
        "subtopic",
        "is_ai_relevant",
        "relevance_reason",
        "content_text_zh",
        "ai_summary_zh",
        "translated_at",
        "translated_by",
    }
    existing = {str(row[1]) for row in con.execute("PRAGMA table_info(voice_post)")}
    columns = sorted(derived & existing)
    if not columns:
        return
    assignments = ",".join(f'"{column}"=NULL' for column in columns)
    con.execute(
        f"UPDATE voice_post SET {assignments} WHERE leader_id=? AND post_id=?",
        (leader_id, post_id),
    )


def _insert_non_weibo_candidates(con, leader, candidates, *, fetched_at: str) -> int:
    """Preserve the existing non-Weibo insert-only storage contract."""
    savepoint = "voice_candidate_insert"
    con.execute(f"SAVEPOINT {savepoint}")
    inserted = 0
    try:
        for candidate in candidates:
            post_id = str(candidate.get("post_id") or "").strip()
            if not post_id:
                continue
            has_media = candidate.get("has_media")
            if has_media is not None:
                has_media = 1 if has_media else 0
            cur = con.execute(
                """INSERT OR IGNORE INTO voice_post(
                     leader_id,post_url,post_id,posted_at,content_text,content_html,
                     has_media,fetch_timestamp,last_verified_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    leader["id"],
                    candidate.get("post_url"),
                    post_id,
                    candidate.get("posted_at"),
                    candidate.get("content_text"),
                    candidate.get("content_html"),
                    has_media,
                    fetched_at,
                    fetched_at,
                ),
            )
            inserted += max(cur.rowcount, 0)
        con.execute(f"RELEASE SAVEPOINT {savepoint}")
        return inserted
    except Exception:
        con.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
        con.execute(f"RELEASE SAVEPOINT {savepoint}")
        raise


def fetch_leader(con, leader) -> FetchOutcome:
    """Fetch/sync one leader and atomically persist raw posts."""
    fetched_at = datetime.now().isoformat(timespec="seconds")
    pconf = CFG["platforms"].get(leader["platform"], {})
    fetcher = make_fetcher(leader["platform"], pconf)
    if fetcher is None:
        return FetchOutcome(0, 0, 0, "no_fetcher", "platform fetcher missing")
    try:
        cands = fetcher.fetch(dict(leader))
    except Exception as e:
        return FetchOutcome(0, 0, 0, "system_error", f"fetcher:{type(e).__name__}")
    status = getattr(fetcher, "last_status", "ok")
    if not cands and status == "ok":
        status = "empty"
    if status not in SUCCESS_STATUSES:
        return FetchOutcome(0, 0, 0, status, f"fetcher_status={status}")
    try:
        if leader["platform"] == "weibo":
            inserted, updated = _upsert_candidates(
                con, leader, cands, fetched_at=fetched_at
            )
        else:
            inserted = _insert_non_weibo_candidates(
                con, leader, cands, fetched_at=fetched_at
            )
            updated = 0
        con.commit()
    except Exception as exc:
        con.rollback()
        return FetchOutcome(
            len(cands), 0, 0, "system_error", f"research_db:{type(exc).__name__}"
        )
    return FetchOutcome(len(cands), inserted, updated, status)


def enrich(con, max_enrich, leader_id=None):
    """对 active leader 的未富化 voice_post 做 funnel 富化(relevance + 摘要/翻译/tag)。
    leader_id 非空时只富化该 leader —— scheduler 按 leader 起独立子进程(120s 超时),
    限定范围避免一个领袖的抓取子进程被全库富化积压拖垮(误判 paused)。"""
    clf = RelevanceClassifier(con)
    closed = ai_funnel.ClosedSet(con)
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT vp.*, ol.region, ol.account_handle
        FROM voice_post vp JOIN opinion_leader ol ON ol.id=vp.leader_id
        WHERE ol.is_active=1 AND (vp.ai_tagged_by IS NULL OR vp.ai_tagged_by <> 'deepseek_funnel')
          AND (? IS NULL OR vp.leader_id = ?)
        ORDER BY vp.id DESC LIMIT ?""", (leader_id, leader_id, max_enrich)).fetchall()
    done = 0
    for r in rows:
        lang = "zh" if r["region"] == "cn" else "en"
        handle = str(r["account_handle"] or "").strip().lower().lstrip("@")
        apply_filter = handle in FILTER_HANDLES
        ai_funnel.process_voice(con, clf, closed, r, source_lang=lang,
                                now_iso=datetime.now().isoformat(timespec="seconds"),
                                apply_filter=apply_filter)
        con.commit(); done += 1
    return done


def alert(lines):
    ALERTDIR.mkdir(parents=True, exist_ok=True)
    (ALERTDIR / f"{datetime.now().date().isoformat()}.md").open("a", encoding="utf-8").write("\n".join(lines) + "\n")


def _result_exit_code(results: list[tuple[sqlite3.Row, FetchOutcome]]) -> int:
    statuses = {outcome.status for _, outcome in results if not outcome.ok}
    if not statuses:
        return 0
    if "auth_expired" in statuses:
        return EXIT_AUTH
    # Only a purely transient result set is deferrable.  A simultaneous system
    # failure must remain visible instead of being masked by another leader's
    # shared-token contention in an all-leaders manual invocation.
    if statuses.issubset(DEFERRED_STATUSES):
        return EXIT_DEFERRED
    return EXIT_SYSTEM


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--leader-id", type=int)
    ap.add_argument("--max-enrich", type=int, default=40)
    ap.add_argument(
        "--wait-for-api",
        action="store_true",
        help="仅供人工补抓：等待共享 subject/infos 令牌；计划任务仍立即延期",
    )
    args = ap.parse_args(argv)
    if args.wait_for_api:
        weibo_api = (CFG.get("platforms", {}).get("weibo", {}) or {}).get("api") or {}
        weibo_api["wait_for_token"] = True
        weibo_api.setdefault("wait_timeout_sec", 600)
    con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row
    q = "SELECT * FROM opinion_leader WHERE is_active=1"
    params = ()
    if args.leader_id is not None:
        q += " AND id=?"; params = (args.leader_id,)
    leaders = con.execute(q, params).fetchall()
    if not leaders:
        con.close()
        print("VOICE_INGEST_FAILURE leader_not_found", file=sys.stderr)
        return EXIT_SYSTEM
    results: list[tuple[sqlite3.Row, FetchOutcome]] = []
    alerts = []
    deferrals = []
    for L in leaders:
        outcome = fetch_leader(con, L)
        results.append((L, outcome))
        if not outcome.ok:
            message = (
                f"- {L['name']}({L['platform']} @{L['account_handle']}):"
                f"{outcome.status}；{outcome.detail or '无更多详情'}"
            )
            if outcome.status in DEFERRED_STATUSES:
                deferrals.append(message)
            else:
                alerts.append(message)

    print(f"{'leader':<14}{'platform':<10}{'got':>5}{'ins':>5}{'upd':>5}  status")
    for leader, outcome in results:
        print(
            f"  {leader['name']:<12}{leader['platform']:<10}"
            f"{outcome.got:>5}{outcome.inserted:>5}{outcome.updated:>5}  "
            f"{outcome.status} {outcome.detail[:160]}"
        )

    # 来源失败时不调用富化外部服务，保留明确的 source exit code。
    all_sources_ok = all(outcome.ok for _, outcome in results)
    n_enrich = enrich(con, args.max_enrich, args.leader_id) if all_sources_ok else 0
    print(f"\nfunnel 富化 voice_post:{n_enrich} 条 | COUNT: voice_relevant={ai_funnel.COUNT['voice_relevant']} voice_irrelevant={ai_funnel.COUNT['voice_irrelevant']}")
    if all_sources_ok:
        import llm_client
        print("DeepSeek usage:", llm_client.USAGE)
    else:
        print("DeepSeek usage: skipped(source failure)")
    tot = con.execute("SELECT COUNT(*) FROM voice_post").fetchone()[0]
    print(f"voice_post 总数:{tot}")

    if alerts:
        alert([f"## KOL source failure — {NOW}"] + alerts)
        print(f"alerts → cache/dynamic_alerts/{datetime.now().date().isoformat()}.md")
    if deferrals:
        print("KOL source deferred(shared yuqing token):")
        print("\n".join(deferrals))
    exit_code = _result_exit_code(results)
    payload = {
        "ok": exit_code == 0,
        "deferred": exit_code == EXIT_DEFERRED,
        "exit_code": exit_code,
        "leaders": [
            {
                "leader_id": leader["id"],
                "platform": leader["platform"],
                "status": outcome.status,
                "got": outcome.got,
                "inserted": outcome.inserted,
                "updated": outcome.updated,
            }
            for leader, outcome in results
        ],
    }
    print("VOICE_INGEST_RESULT " + json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if exit_code:
        marker = "VOICE_INGEST_DEFERRED" if exit_code == EXIT_DEFERRED else "VOICE_INGEST_FAILURE"
        print(
            marker + " "
            + ",".join(
                f"{leader['id']}:{outcome.status}"
                for leader, outcome in results
                if not outcome.ok
            ),
            file=sys.stderr,
        )
    con.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
