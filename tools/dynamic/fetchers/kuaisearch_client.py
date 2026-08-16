#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
智慧星光「舆情秘书」快搜 API 客户端(国内意见领袖抓取,替代 cookies/访客流)。

模型:专题(subject)级监测,非账号时间线。主端点 subject/infos 按 `id`(专题id,""=全部)拉
data.records[],每条含 authorInfo{authorUserAccountNum,authorSourceId,authorUrl}。

?? 反 slop / 精准抓本人发言(用户硬约束:不抓"提到此人"的帖):
  拉到 records 后,**客户端按作者 UID 硬过滤** —— authorUserAccountNum / authorSourceId
  / authorUrl 命中目标 uid 才保留。绝不按昵称模糊匹配,绝不编造。

?? QPS(subject/infos 1次/60s)+ 按返回条数计费:
  同一 tick 内多个国内领袖共用**一次**拉取 —— 与 Xinghan 窗口分页共享账号级原子
  state/lock(secrets 外的 cache/yuqing/) + 短 TTL 响应缓存。窗口补抓占锁时 KOL
  请求不等待、不真实调用；旧缓存显式标 ``cached_stale``，不伪装新数据。

key:tools/dynamic/secrets/yuqing_api_key.txt(JWT,绝不入库/入日志/入 git)。
契约全文:docs/yuqing-api-info.txt。
"""
from __future__ import annotations
import sys, io, ssl, json, time, re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen, build_opener, ProxyHandler, HTTPSHandler
from urllib.error import HTTPError, URLError
try:
    from .yuqing_rate_limit import DEFAULT_INTERVAL_SECONDS, SharedSubjectInfosLimiter
except ImportError:  # 兼容 voice_fetcher 把本目录加入 sys.path 后的脚本式导入
    from yuqing_rate_limit import DEFAULT_INTERVAL_SECONDS, SharedSubjectInfosLimiter

ROOT = Path(__file__).resolve().parent.parent.parent.parent
from tools.runtime_paths import resolve_runtime_layout
RUNTIME_LAYOUT = resolve_runtime_layout(ROOT)
SECRETS = RUNTIME_LAYOUT.content_root / "tools" / "dynamic" / "secrets"
CACHEDIR = RUNTIME_LAYOUT.cache_root / "yuqing"
ALERTDIR = RUNTIME_LAYOUT.cache_root / "dynamic_alerts"
BASE = "https://dowding-gwa.istarshine.com/yqms/v4/api"
TIMEOUT = 30
_TAG = re.compile(r"<[^>]+>")
_ctx = ssl.create_default_context(); _ctx.check_hostname = False; _ctx.verify_mode = ssl.CERT_NONE
# ?? 显式空代理 = 直连,绕过系统代理/VPN。舆情白名单只放行国内直连出口 IP(如 222.71.47.150);
#   VPN 出口是 38.175.103.x 段动态轮换、无法稳定加白。本机若挂 Clash 系统代理,默认 opener 会把请求
#   套进代理→走 VPN→403。此 opener 只让舆情这一路直连,不影响 Claude Code 等其余流量。零改系统/VPN 设置。
_OPENER = build_opener(ProxyHandler({}), HTTPSHandler(context=_ctx))


def load_token() -> str | None:
    f = SECRETS / "yuqing_api_key.txt"
    if not f.exists():
        return None
    t = f.read_text(encoding="utf-8").strip()
    return t or None


def _strip(s):
    return _TAG.sub("", s or "").strip()


def _ts_ms(v):
    """epoch 毫秒 → 东八区 ISO;非数字原样返回。"""
    try:
        n = float(v)
        if n > 1e12:
            n /= 1000.0
        return datetime.fromtimestamp(n, tz=timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    except Exception:
        return str(v)[:25] if v else None


def _full_body(
    *, subject_id, begin_ms, end_ms, now_ms, media_types, weibo_types,
    account_type, sites, limit, offset,
):
    """subject/infos 完整请求体(文档警告"不传≠默认全部",故全字段显式给值)。"""
    return {
        "id": subject_id or "", "subjectType": 1,
        "beginTime": begin_ms, "endTime": end_ms, "timestamp": now_ms, "timeType": "1",
        "infoSource": "", "attitude": [], "sourceRange": "",
        "newSqSourceRange": [], "newSourceRange": "", "newsMediaSourceRange": [],
        "mediaType": list(media_types or []), "shortVideoType": [], "tvChannel": [], "tvColumn": [],
        "isOcr": "", "filterType": "1", "matchRange": "", "firstRegion": "100", "wordRange": "50",
        "uniqueRegion": True, "weiboTimeFilter": False, "ignoreWeiboLocationWord": False,
        "ignoreWeiboRemindWord": False, "ignoreWeiboTopicWord": False,
        "weiboType": list(weibo_types or []), "weiboAttestType": [], "weiboState": "",
        "isRepeat": "0", "browseRange": "", "isImportance": False, "noPicture": False, "orderBy": 1,
        "isHideSummary": False, "customCondition": [], "subjectModule": 1, "refreshType": 1,
        "pageSize": limit, "sites": list(sites or []), "industryTags": [], "distinguishType": [],
        "videoDurationType": [], "regionalMatchType": [], "regionalMatch": [], "subjectArray": [],
        "sqSourceRange": [], "fansCountRange": "", "mcnType": "",
        "accountType": str(account_type or ""), "isFullscreen": False, "warningType": 1,
        "monitorType": 0, "language": 2, "offset": offset, "limitNum": limit,
        "activeNav": 1, "backTrack": False,
    }


class KuaiSearchClient:
    """一个进程内一实例；真实调用与窗口分页共享账号级原子限流器。"""

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}
        self.token = load_token()
        self.last_status = "ok"
        # 配置(均可在 config.platforms.<p>.api 覆盖)
        self.subject_id = str(self.cfg.get("subject_id", "") or "")
        self.window_hours = int(self.cfg.get("window_hours", 3))    # 小窗:QPS 1/60s 下不分页,降重叠计费 + 提高本人帖落在单页概率
        self.cache_ttl_sec = int(self.cfg.get("cache_ttl_sec", 900))     # 同 tick 共用拉取
        self.min_interval_sec = max(
            float(self.cfg.get("min_interval_sec", DEFAULT_INTERVAL_SECONDS)),
            DEFAULT_INTERVAL_SECONDS,
        )
        self.limit = min(int(self.cfg.get("limit", 180)), 180)
        self.account_type = str(self.cfg.get("account_type", "") or "")
        self.sites = list(self.cfg.get("sites") or [])
        self.wait_for_token = bool(self.cfg.get("wait_for_token", False))
        self.wait_timeout_sec = float(self.cfg.get("wait_timeout_sec", 600))
        self.cache_dir = CACHEDIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.rate_limiter = SharedSubjectInfosLimiter(
            cache_dir=self.cache_dir,
            interval_seconds=self.min_interval_sec,
        )
        self.last_rate_limit_reason = None

    def _alert(self, msg):
        try:
            ALERTDIR.mkdir(parents=True, exist_ok=True)
            (ALERTDIR / f"{datetime.now().date().isoformat()}.md").open("a", encoding="utf-8").write(
                f"- [yuqing] {datetime.now().isoformat(timespec='seconds')} {msg}\n")
        except Exception:
            pass

    def _cache_path(self, media_types) -> Path:
        key = "all" if not media_types else "-".join(map(str, media_types))
        acct = self.account_type or "all_accounts"
        return self.cache_dir / f"infos_{self.subject_id or 'ALL'}_{key}_{acct}.json"

    def _read_cache(self, path: Path):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - obj.get("_pulled_at", 0) <= self.cache_ttl_sec:
                return obj.get("records") or []
        except Exception:
            pass
        return None

    @staticmethod
    def _read_stale_cache(path: Path):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            records = obj.get("records")
            return records if isinstance(records, list) else None
        except Exception:
            return None

    def _post(self, endpoint: str, body: dict):
        """返回 (records, status)。HTTP 非200 → 业务 status。"""
        if not self.token:
            return [], "auth_expired"
        data = json.dumps(body).encode("utf-8")
        req = Request(f"{BASE}/{endpoint}", data=data, method="POST",
                      headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.token})
        try:
            with _OPENER.open(req, timeout=TIMEOUT) as r:    # 直连(空代理),绕过 VPN → 命中国内白名单 IP
                j = json.loads(r.read().decode("utf-8", "replace"))
        except HTTPError as e:
            code = e.code
            if code in (401, 403):
                # 403 多为 IP 未白名单;401 token 失效。都按需登录态告警(不编造)。
                return [], "auth_expired"
            if code == 429:
                return [], "rate_limited"
            return [], "error"
        except (URLError, Exception):
            return [], "error"
        if j.get("code") not in (200, None):
            return [], "error"
        payload = j.get("data")
        if isinstance(payload, dict) and "records" in payload:
            recs = payload.get("records")
        elif isinstance(payload, list):
            recs = payload
        else:
            return [], "error"
        if recs is None:
            recs = []
        return (recs, "ok") if isinstance(recs, list) else ([], "error")

    def pull_recent(self, media_types):
        """拉取最近窗口内全部监测记录(共享 cache + 限频)。返回 records[]。"""
        path = self._cache_path(media_types)
        cached = self._read_cache(path)
        if cached is not None:
            self.last_status = "ok"
            self.last_rate_limit_reason = None
            return cached
        if not self.token:
            self.last_status = "auth_expired"
            return []
        # 事件/KOL 任务不等待窗口长分页释放令牌。锁忙或仍在 65 秒冷却期时，
        # 可以读取旧缓存用于诊断，但状态必须是 cached_stale，不能伪装本轮新抓成功。
        try:
            decision = (
                self.rate_limiter.acquire(timeout_seconds=self.wait_timeout_sec)
                if self.wait_for_token
                else self.rate_limiter.try_acquire()
            )
        except TimeoutError:
            decision = None
        if decision is None:
            self.last_rate_limit_reason = "wait_timeout"
            self.last_status = "rate_limited"
            return []
        if not decision.acquired:
            self.last_rate_limit_reason = (
                f"{decision.reason}:retry_after={decision.retry_after_seconds:.1f}s"
            )
            stale = self._read_stale_cache(path)
            if stale is not None:
                self.last_status = "cached_stale"
                return stale
            self.last_status = "rate_limited"
            return []
        self.last_rate_limit_reason = None
        now_ms = int(time.time() * 1000)
        begin_ms = now_ms - self.window_hours * 3600 * 1000
        # weiboType 默认排除 评论"4"/弹幕"5"(只要本人原创/转发)
        wtypes = self.cfg.get("weibo_types", ["1", "2", "3"])
        body = _full_body(subject_id=self.subject_id, begin_ms=begin_ms, end_ms=now_ms, now_ms=now_ms,
                          media_types=media_types, weibo_types=wtypes,
                          account_type=self.account_type, sites=self.sites,
                          limit=self.limit, offset=0)
        recs, status = self._post("subject/infos", body)
        self.last_status = status
        if status == "ok":
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"_pulled_at": time.time(), "records": recs}, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(path)                                    # 原子落盘,避免子进程被 kill 留半截 JSON
            if len(recs) >= self.limit:                          # 单页打满 → 可能漏抓本人帖(QPS 1/60s 无法翻页)
                self._alert(f"窗口溢出:subject_id={self.subject_id or 'ALL'} media={media_types} "
                            f"返回{len(recs)}==上限{self.limit},可能漏抓本人帖;建议指定 subject_id 或缩小 window_hours")
        return recs

    @staticmethod
    def _author_match(rec: dict, uid: str) -> bool:
        """精准:作者 UID(账号id/作者id)精确相等,或主页/链接中以非数字边界出现 uid 才算本人发言。
        绝不按昵称模糊匹配 —— 防"提到此人名字"的帖误入(用户硬约束)。"""
        uid = str(uid).strip()
        if not uid:
            return False
        ai = rec.get("authorInfo") or {}
        for k in ("authorUserAccountNum", "authorSourceId"):
            if str(ai.get(k) or "").strip() == uid:
                return True
        pat = re.compile(rf"(?<!\d){re.escape(uid)}(?!\d)")     # 数字边界,防短 uid 成更长数字的子串误判
        for u in (ai.get("authorUrl"), rec.get("url")):
            if u and pat.search(str(u)):
                return True
        return False

    @staticmethod
    def _normalize(rec: dict) -> dict:
        pid = str(rec.get("infoId") or rec.get("id") or "").strip()   # 稳定唯一 id;不用 simHash(相似哈希,非唯一)
        text = rec.get("fullContent") or rec.get("content") or rec.get("summary") or rec.get("title") or ""
        imgs = rec.get("originImgUrls") or rec.get("imgUrls") or []
        return {
            "post_id": pid,
            "post_url": rec.get("url"),
            "posted_at": _ts_ms(rec.get("publishTime") or rec.get("collectTime")),
            "content_text": _strip(text),
            "content_html": rec.get("content") or rec.get("fullContent") or "",
            "has_media": bool(imgs or rec.get("videoUrls")),
        }

    def fetch_leader_posts(self, uid: str, media_types=None) -> list[dict]:
        """某领袖本人发言:拉取(共享)→ 作者UID硬过滤 → 归一化。
        状态:ok(有本人帖)/ empty(本窗口监测池为空)/ api_miss(池非空但本人0命中)
              / cached_stale / auth_expired / rate_limited / error。
        ?? api_miss≠empty:调用方据此仍回落 cookie/visitor(0命中也可能是字段语义不符,需兜底,不武断判空)。"""
        recs = self.pull_recent(media_types)
        if self.last_status not in ("ok",):
            return []
        out, seen = [], set()
        for r in recs:
            if not self._author_match(r, uid):
                continue
            n = self._normalize(r)
            if n["post_id"] and n["post_id"] not in seen:
                seen.add(n["post_id"]); out.append(n)
        if not out:
            self.last_status = "empty" if not recs else "api_miss"
        return out
