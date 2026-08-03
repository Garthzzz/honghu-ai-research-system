#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""星瀚(智慧星光)快搜 API 统一窗口客户端 —— 三层情绪系统专用。

与既有 kuaisearch_client(领袖 UID 过滤、单拉缓存)互补:本客户端面向**按时间窗 + 翻页**
的全量拉取(三层 + 补抓),复用其 token/opener/BASE(DRY,不重复造轮子)。

策略(经济 + 鲁棒):每个(专题,时间窗)**一次拉全媒体**(mediaType=[]),翻页到取尽,
本地按 webName/domain/mediaType 分层(senti3.classify_platform)——
雪球无独立 mediaType 枚举,故走 webName/domain 过滤(用户「先试 sites 不行则过滤」的过滤分支),
并 log 平台分布以经验确认雪球/各源是否在监测池内(不预判抓不到)。

限流:senti3.RateLimiter(subject/infos 1次/60s,文件持久,阻塞到令牌)。绝不超频。
按条计费 → 调用方保证时间窗不重叠。token 读 secrets,绝不入库/入日志。
"""
from __future__ import annotations
import sys, json, time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.request import Request
from urllib.error import HTTPError, URLError

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "tools" / "dynamic" / "fetchers"))
import senti3
# 复用既有客户端的 token / 直连 opener / BASE / 文本清洗 / 时间戳(DRY)
from kuaisearch_client import load_token, BASE, _OPENER, _strip, _ts_ms, TIMEOUT

PAGE_MAX = 180


@dataclass(frozen=True)
class XinghanPage:
    """一页稳定快照结果。

    ``offset``/``next_offset`` 使用 API 的原始记录位置；即使本地 dedup 后条数
    变少，也必须按 ``limitNum`` 推进，不能用去重后的长度计算下一页。
    """

    records: list[dict]
    offset: int
    next_offset: int
    terminal: bool
    raw_count: int


def build_body(*, subject_id, begin_ms, end_ms, now_ms, media_types=(), sites=(),
               weibo_types=("1", "2", "3"), attitude=(), order_by=2, time_type="1",
               limit=PAGE_MAX, offset=0, is_repeat="0"):
    """subject/infos 完整请求体(超集,参数化)。文档警告「不传≠默认全部」→ 全字段显式给值。
    order_by=2 时间正序(翻页稳定);time_type=1 发布时间;is_repeat=0 去重。"""
    return {
        "id": subject_id or "", "subjectType": 1,
        "beginTime": begin_ms, "endTime": end_ms, "timestamp": now_ms, "timeType": str(time_type),
        "infoSource": "", "attitude": list(attitude or []), "sourceRange": "",
        "newSqSourceRange": [], "newSourceRange": "", "newsMediaSourceRange": [],
        "mediaType": list(media_types or []), "shortVideoType": [], "tvChannel": [], "tvColumn": [],
        "isOcr": "", "filterType": "1", "matchRange": "", "firstRegion": "100", "wordRange": "50",
        "uniqueRegion": True, "weiboTimeFilter": False, "ignoreWeiboLocationWord": False,
        "ignoreWeiboRemindWord": False, "ignoreWeiboTopicWord": False,
        "weiboType": list(weibo_types or []), "weiboAttestType": [], "weiboState": "",
        "isRepeat": is_repeat, "browseRange": "", "isImportance": False, "noPicture": False,
        "orderBy": order_by, "isHideSummary": False, "customCondition": [], "subjectModule": 1,
        "refreshType": 1, "pageSize": limit, "sites": list(sites or []), "industryTags": [],
        "distinguishType": [], "videoDurationType": [], "regionalMatchType": [], "regionalMatch": [],
        "subjectArray": [], "sqSourceRange": [], "fansCountRange": "", "isFullscreen": False,
        "warningType": 1, "monitorType": 0, "language": 2, "offset": offset, "limitNum": limit,
        "activeNav": 1, "backTrack": False,
    }


def normalize(rec: dict) -> dict:
    """星瀚原始 record → 统一字段(供归因 + 入 senti_raw)。"""
    ai = rec.get("authorInfo") or {}
    pid = str(rec.get("infoId") or rec.get("id") or "").strip()
    sim = str(rec.get("simHash") or "").strip()
    text = rec.get("fullContent") or rec.get("content") or rec.get("summary") or rec.get("title") or ""
    att = rec.get("attitude")
    try:
        att = int(att)
        if att not in (1, 2, 3):
            att = None
    except Exception:
        att = None
    hot = rec.get("hotValue")
    try:
        hot = int(hot)
    except Exception:
        hot = None
    return {
        "post_id": pid,
        "sim_hash": sim or None,
        "dedup_key": sim or pid,                       # simHash 优先否则 post_id
        "title": _strip(rec.get("title") or "")[:300],
        "text": _strip(text),                          # 归因用(title+正文)
        "url": rec.get("url") or rec.get("originUrl"),
        "author": rec.get("author"),
        "author_uid": str(ai.get("authorUserAccountNum") or ai.get("authorSourceId") or "") or None,
        "fans_count": ai.get("authorFansCount"),
        "auth_type": ai.get("authorAuthType") or rec.get("authorAuthType"),
        "attitude": att,                               # 1正 2负 3中(原生)
        "web_name": rec.get("webName"),
        "domain": rec.get("domain"),
        "channel": rec.get("channel"),
        "media_type": rec.get("mediaType"),
        "hot_value": hot,
        "publish_time": _ts_ms(rec.get("publishTime") or rec.get("collectTime")),
    }


class XinghanWindowClient:
    """按(专题, 时间窗)翻页拉全媒体。

    last_status: ok|empty|truncated|auth_expired|rate_limited|error|no_token。
    ``truncated`` 表示达到安全页数上限但最后一页仍满页，调用方必须视为失败，
    不能把不完整窗口标成 complete。
    """

    def __init__(
        self,
        *,
        interval_sec=65,
        max_pages=30,
        rate_limit_retries=3,
        rate_limit_backoff_sec=60,
    ):
        self.token = load_token()
        self.rl = senti3.RateLimiter("infos", interval_sec)
        self.max_pages = max(1, int(max_pages))
        self.rate_limit_retries = max(0, int(rate_limit_retries))
        self.rate_limit_backoff_sec = max(0.0, float(rate_limit_backoff_sec))
        self.last_status = "ok"
        self.calls = 0
        self.billed = 0                                # 累计返回条数(≈计费条数)
        self.rate_limit_hits = 0

    def _rate_limit_wait(self, error: HTTPError, retry_index: int) -> float:
        """优先服从服务端 Retry-After，否则指数退避并封顶 5 分钟。"""
        retry_after = None
        try:
            retry_after = error.headers.get("Retry-After") if error.headers else None
            if retry_after is not None:
                retry_after = float(retry_after)
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(str(retry_after))
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                retry_after = retry_at.timestamp() - time.time()
            except (TypeError, ValueError, OverflowError):
                retry_after = None
        if retry_after is not None and retry_after >= 0:
            return min(retry_after, 300.0)
        return min(self.rate_limit_backoff_sec * (2 ** retry_index), 300.0)

    def _post(self, body: dict):
        if not self.token:
            self.last_status = "no_token"
            return [], "no_token"
        data = json.dumps(body).encode("utf-8")
        req = Request(f"{BASE}/subject/infos", data=data, method="POST",
                      headers={"Content-Type": "application/json",
                               "Authorization": "Bearer " + self.token})
        j = None
        for retry_index in range(self.rate_limit_retries + 1):
            self.rl.acquire()                          # 阻塞限频,绝不超频
            try:
                with _OPENER.open(req, timeout=TIMEOUT) as response:  # 直连(空代理),绕 VPN → 命中国内白名单
                    j = json.loads(response.read().decode("utf-8", "replace"))
                break
            except HTTPError as error:
                if error.code in (401, 403):
                    return [], "auth_expired"
                if error.code != 429:
                    return [], "error"
                self.rate_limit_hits += 1
                if retry_index >= self.rate_limit_retries:
                    return [], "rate_limited"
                time.sleep(self._rate_limit_wait(error, retry_index))
            except (URLError, Exception):
                return [], "error"
        if j is None:
            return [], "error"
        self.calls += 1
        if j.get("code") not in (200, None):
            return [], "error"
        payload = j.get("data")
        if isinstance(payload, dict) and "records" in payload:
            recs = payload.get("records")
        elif isinstance(payload, list):
            recs = payload
        else:
            # HTTP 200 但缺少明确 records 不能被解释成合法空页，否则会错误清除
            # checkpoint 并把不完整片段标成 complete。
            return [], "error"
        if recs is None:
            recs = []
        if not isinstance(recs, list):
            return [], "error"
        self.billed += len(recs)
        return recs, "ok"

    def iter_window_pages(
        self,
        *,
        subject_id,
        begin_ms,
        end_ms,
        media_types=(),
        sites=(),
        attitude=(),
        snapshot_timestamp_ms=None,
        start_offset=0,
        max_pages=None,
    ):
        """逐页拉取同一 API 快照，供调用方每页原子落库并保存 checkpoint。

        星瀚契约要求翻页时一直复用第一页的 ``timestamp``。恢复任务必须传回持久化
        的 ``snapshot_timestamp_ms`` 与 ``start_offset``；否则虽然发布时间水位大多
        能推进，却无法覆盖同一时间戳拥挤和迟到旧帖造成的排序变化。
        """
        snapshot_ms = int(snapshot_timestamp_ms or int(time.time() * 1000))
        offset = max(0, int(start_offset))
        page_limit = self.max_pages if max_pages is None else max(1, int(max_pages))
        self.last_status = "ok"
        for _page_index in range(page_limit):
            body = build_body(
                subject_id=subject_id,
                begin_ms=begin_ms,
                end_ms=end_ms,
                now_ms=snapshot_ms,
                media_types=media_types,
                sites=sites,
                attitude=attitude,
                limit=PAGE_MAX,
                offset=offset,
            )
            recs, status = self._post(body)
            self.last_status = status
            if status != "ok":
                return
            raw_count = len(recs)
            terminal = raw_count < PAGE_MAX            # 官方契约：短页即无下一页
            normalized = [normalize(record) for record in recs]
            if terminal:
                self.last_status = "empty" if offset == 0 and not recs else "ok"
            yield XinghanPage(
                records=normalized,
                offset=offset,
                next_offset=offset + PAGE_MAX,
                terminal=terminal,
                raw_count=raw_count,
            )
            if terminal:
                return
            offset += PAGE_MAX
        self.last_status = "truncated"

    def fetch_window(
        self,
        *,
        subject_id,
        begin_ms,
        end_ms,
        media_types=(),
        sites=(),
        attitude=(),
        snapshot_timestamp_ms=None,
        start_offset=0,
    ) -> list[dict]:
        """兼容旧调用：在内存中合并多页；新窗口编排应使用 ``iter_window_pages``。"""
        out, seen = [], set()
        for page in self.iter_window_pages(
            subject_id=subject_id,
            begin_ms=begin_ms,
            end_ms=end_ms,
            media_types=media_types,
            sites=sites,
            attitude=attitude,
            snapshot_timestamp_ms=snapshot_timestamp_ms,
            start_offset=start_offset,
        ):
            for record in page.records:
                key = record["dedup_key"]
                if key and key not in seen:
                    seen.add(key)
                    out.append(record)
        return out


if __name__ == "__main__":
    # 经验性探测:近 24h,id=""(全部监测池),报平台分布(确认雪球/各源是否在池内,不预判)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sub = sys.argv[1] if len(sys.argv) > 1 else ""
    hours = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    now = datetime.now(timezone(timedelta(hours=8)))
    cli = XinghanWindowClient(max_pages=2)             # 探测封顶 2 页省计费
    recs = cli.fetch_window(subject_id=sub, begin_ms=senti3.to_ms(now - timedelta(hours=hours)),
                            end_ms=senti3.to_ms(now))
    print(f"status={cli.last_status} calls={cli.calls} billed={cli.billed} records={len(recs)}")
    from collections import Counter
    layers = Counter()
    webs = Counter()
    for n in recs:
        lay, plat = senti3.classify_platform(n["web_name"], n["domain"], n["media_type"], n["channel"])
        layers[f"{lay}/{plat}"] += 1
        webs[(n["web_name"] or "?")[:20]] += 1
    print("层/平台分布:", dict(layers))
    print("webName Top:", dict(webs.most_common(12)))
