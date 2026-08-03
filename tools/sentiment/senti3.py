#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""三层情绪系统公共件:桶模型 / 闭集归因 / 平台分层 / 统一限流器 / 来源权重。

被 senti_fetch_xinghan / senti_fetch_guba / senti_score / senti_aggregate_3layer / retail_window_tick 共用。
只含纯逻辑 + 文件级限流,不直接写库(写库由各脚本经 common.assert_senti_only 守门)。
"""
from __future__ import annotations
import re, sys, time, json, hashlib, random
from dataclasses import dataclass
from pathlib import Path
from datetime import date, datetime, time as clock_time, timedelta, timezone

ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_YUQING = ROOT / "cache" / "yuqing"
FETCHER_DIR = ROOT / "tools" / "dynamic" / "fetchers"
if str(FETCHER_DIR) not in sys.path:
    sys.path.insert(0, str(FETCHER_DIR))
from yuqing_rate_limit import DEFAULT_INTERVAL_SECONDS, SharedSubjectInfosLimiter
TZ = timezone(timedelta(hours=8))

# ── 来源权重(散户层;仅散户层加权。可被 config 覆盖)──
#   2026-06-24:星瀚新增 同花顺(ths)/东方财富(eastmoney) 平台;微博低权重,其余高权重。
DEFAULT_RETAIL_WEIGHTS = {"xueqiu": 1.0, "eastmoney": 1.0, "ths": 1.0, "guba": 1.0}
SIGNIFICANCE_MIN = 10                    # valid_count > 10 才显著
NEWS_PLATFORMS = ("sina_news", "netease_news", "ifeng", "toutiao", "weixin")
RETAIL_PLATFORMS = ("xueqiu", "eastmoney", "ths", "guba")


# ════════════════════ 桶模型(M-SCHEDULE)════════════════════
# 日间 4 桶 span=3h:[08-11)[11-14)[14-17)[17-20);隔夜 1 桶 span=12h:[20-次日08)
DAY_STARTS = (8, 11, 14, 17)             # 日间桶起点小时
OVERNIGHT_START = 20


# ════════════════════ 市场窗口 V2（交易日对齐）════════════════════
#
# V1 的 08/11/14/17/20 桶仍保留给旧表兼容。新抓取、V2 聚合和公司页应使用
# 下列三个窗口；窗口 id 以“归属交易日”而不是自然日起点命名，避免隔夜情绪
# 被错误归到前一日。
MARKET_WINDOW_VERSION = "retail.market_window.v2"
MARKET_WINDOW_SLOTS = ("preopen", "morning", "afternoon")
MARKET_WINDOW_RUN_TIMES = {
    "preopen": clock_time(10, 0),
    "morning": clock_time(14, 0),
    "afternoon": clock_time(17, 0),
}


def _local_datetime(day: date, at: clock_time) -> datetime:
    return datetime.combine(day, at, tzinfo=TZ)


def is_market_session_day(day: date, trading_days: set[date] | None = None) -> bool:
    """返回是否为可抓取交易日。

    传入 ``trading_days`` 时它是权威日历；未传时只做周一至周五的保守回退。
    周末无论如何都不会成为 session day。
    """
    if day.weekday() >= 5:
        return False
    return day in trading_days if trading_days is not None else True


def previous_market_session(day: date, trading_days: set[date] | None = None) -> date:
    cur = day - timedelta(days=1)
    for _ in range(370):
        if is_market_session_day(cur, trading_days):
            return cur
        cur -= timedelta(days=1)
    raise ValueError(f"无法在 {day} 前 370 天内找到交易日")


def next_market_session(day: date, trading_days: set[date] | None = None) -> date:
    cur = day + timedelta(days=1)
    for _ in range(370):
        if is_market_session_day(cur, trading_days):
            return cur
        cur += timedelta(days=1)
    raise ValueError(f"无法在 {day} 后 370 天内找到交易日")


@dataclass(frozen=True)
class MarketWindow:
    """一个可幂等执行的散户情绪市场窗口。

    ``segments`` 是实际允许抓取/计费的半开区间。preopen 在周一或长假后会
    拆成“前一交易日 16:00-24:00”和“本交易日 00:00-09:30”，从而明确
    排除周末与休市日，而不是先抓后丢。
    """

    session_date: date
    slot: str
    window_start: datetime
    window_end: datetime
    scheduled_for: datetime
    segments: tuple[tuple[datetime, datetime], ...]
    effective_minutes: int
    version: str = MARKET_WINDOW_VERSION

    @property
    def window_id(self) -> str:
        return f"{self.session_date.isoformat()}:{self.slot}"


def market_window(
    session_date: date,
    slot: str,
    trading_days: set[date] | None = None,
) -> MarketWindow:
    """构造交易日 ``session_date`` 的精确半开窗口。"""
    if slot not in MARKET_WINDOW_SLOTS:
        raise ValueError(f"未知 market window slot: {slot}")
    if not is_market_session_day(session_date, trading_days):
        raise ValueError(f"{session_date} 不是交易日")

    if slot == "preopen":
        previous = previous_market_session(session_date, trading_days)
        start = _local_datetime(previous, clock_time(16, 0))
        end = _local_datetime(session_date, clock_time(9, 30))
        previous_midnight = _local_datetime(previous + timedelta(days=1), clock_time(0, 0))
        current_midnight = _local_datetime(session_date, clock_time(0, 0))
        segments = ((start, previous_midnight), (current_midnight, end))
    elif slot == "morning":
        start = _local_datetime(session_date, clock_time(9, 30))
        end = _local_datetime(session_date, clock_time(13, 0))
        segments = ((start, end),)
    else:
        start = _local_datetime(session_date, clock_time(13, 0))
        end = _local_datetime(session_date, clock_time(16, 0))
        segments = ((start, end),)

    effective_minutes = sum(int((end_ - start_).total_seconds() // 60) for start_, end_ in segments)
    return MarketWindow(
        session_date=session_date,
        slot=slot,
        window_start=start,
        window_end=end,
        scheduled_for=_local_datetime(session_date, MARKET_WINDOW_RUN_TIMES[slot]),
        segments=segments,
        effective_minutes=effective_minutes,
    )


def market_window_for_timestamp(
    value: datetime,
    trading_days: set[date] | None = None,
) -> MarketWindow | None:
    """把发布时间映射到唯一 V2 窗口；周末/休市日返回 ``None``。

    边界严格为：09:30 属 morning，13:00 属 afternoon，16:00 属下一
    交易日 preopen。拒绝 naive datetime，防止服务器本地时区造成静默错桶。
    """
    if value.tzinfo is None:
        raise ValueError("market window mapping requires timezone-aware datetime")
    local = value.astimezone(TZ)
    day = local.date()
    if not is_market_session_day(day, trading_days):
        return None
    tod = local.timetz().replace(tzinfo=None)
    if tod < clock_time(9, 30):
        return market_window(day, "preopen", trading_days)
    if tod < clock_time(13, 0):
        return market_window(day, "morning", trading_days)
    if tod < clock_time(16, 0):
        return market_window(day, "afternoon", trading_days)
    return market_window(next_market_session(day, trading_days), "preopen", trading_days)


def scheduled_slot_for_time(
    value: datetime,
    trading_days: set[date] | None = None,
) -> str | None:
    """给 Task Scheduler 的迟到补跑选择当前已到期的最近 slot。"""
    if value.tzinfo is None:
        raise ValueError("scheduled slot selection requires timezone-aware datetime")
    local = value.astimezone(TZ)
    if not is_market_session_day(local.date(), trading_days):
        return None
    tod = local.timetz().replace(tzinfo=None)
    if tod >= MARKET_WINDOW_RUN_TIMES["afternoon"]:
        return "afternoon"
    if tod >= MARKET_WINDOW_RUN_TIMES["morning"]:
        return "morning"
    if tod >= MARKET_WINDOW_RUN_TIMES["preopen"]:
        return "preopen"
    return None


def bucket_for(dt: datetime) -> dict:
    """某时刻 → 所属桶。返回 {bucket_id,bucket_start(iso),bucket_end(iso),span_hours}。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    h = dt.hour
    d0 = dt.replace(minute=0, second=0, microsecond=0)
    if h < 8:                            # 凌晨 → 昨夜隔夜桶
        start = (d0 - timedelta(days=1)).replace(hour=OVERNIGHT_START)
        span = 12
    elif h >= OVERNIGHT_START:           # 当晚隔夜桶
        start = d0.replace(hour=OVERNIGHT_START)
        span = 12
    else:                                # 日间
        sh = max(s for s in DAY_STARTS if s <= h)
        start = d0.replace(hour=sh)
        span = 3
    end = start + timedelta(hours=span)
    return {"bucket_id": start.strftime("%Y-%m-%dT%H:00"),
            "bucket_start": start.isoformat(timespec="minutes"),
            "bucket_end": end.isoformat(timespec="minutes"),
            "span_hours": span}


def buckets_in_range(d_start: datetime, d_end: datetime) -> list[dict]:
    """[d_start, d_end] 跨度内全部桶(按 bucket_start 升序,去重)。含端点当天全部桶。"""
    if d_start.tzinfo is None:
        d_start = d_start.replace(tzinfo=TZ)
    if d_end.tzinfo is None:
        d_end = d_end.replace(tzinfo=TZ)
    out, seen = [], set()
    day = d_start.replace(hour=0, minute=0, second=0, microsecond=0)
    last = d_end.replace(hour=23, minute=59)
    while day <= last:
        for sh in DAY_STARTS:
            b = bucket_for(day.replace(hour=sh, minute=1))
            if b["bucket_id"] not in seen:
                seen.add(b["bucket_id"]); out.append(b)
        b = bucket_for(day.replace(hour=OVERNIGHT_START, minute=1))
        if b["bucket_id"] not in seen:
            seen.add(b["bucket_id"]); out.append(b)
        day += timedelta(days=1)
    out.sort(key=lambda x: x["bucket_start"])
    # 只保留 bucket_start 落在 [d_start当天0点, d_end] 的桶
    return [b for b in out if b["bucket_start"][:16] <= last.isoformat(timespec="minutes")]


def to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def iso_to_dt(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


# ════════════════════ 平台分层(星瀚记录 → source_layer/platform)════════════════════
def classify_platform(web_name: str, domain: str, media_type, channel: str = "") -> tuple:
    """星瀚记录归到 (source_layer, platform)。不在三层定义内 → (None,None) 丢弃。
    股吧(guba)不走星瀚,由 guba fetcher 直接打 platform='guba'。"""
    web = (web_name or "") + " " + (domain or "") + " " + (channel or "")
    low = web.lower()
    mt = media_type
    try:
        mt = int(mt)
    except Exception:
        mt = None
    # ── 散户 ──
    # 微博已退出散户情绪；微博 KOL 由 dynamic 的舆情 API 作者链路独立处理。
    if mt == 4 or "微博" in web or "weibo" in low:
        return (None, None)
    if "雪球" in web or "xueqiu" in low:
        return ("retail", "xueqiu")
    if "同花顺" in web or "10jqka" in low or "ths" in low:
        return ("retail", "ths")
    # 东方财富生态(股吧/财富号/各股吧):星瀚 API 供给,原生态度。与自爬 guba 分列。
    if "股吧" in web or "东方财富" in web or "eastmoney" in low or "财富号" in web or "guba" in low:
        return ("retail", "eastmoney")
    # ── 新闻 ──
    if mt == 6 or "微信" in web or "weixin" in low or "mp.weixin" in low:
        return ("news", "weixin")
    if "新浪" in web or "sina" in low:
        return ("news", "sina_news")
    if "网易" in web or "163.com" in low or "netease" in low:
        return ("news", "netease_news")
    if "凤凰" in web or "ifeng" in low:
        return ("news", "ifeng")
    if "今日头条" in web or "toutiao" in low:
        return ("news", "toutiao")
    return (None, None)


# ════════════════════ 闭集归因(别名 → company_id)════════════════════
class AliasIndex:
    """company_alias → 文本归因。code 型用数字边界正则防误判;其余子串匹配。命中多家则多归。"""

    def __init__(self, con):
        self.plain = []      # [(alias_lower, company_id, ticker)]
        self.codes = []      # [(compiled_regex, company_id, ticker)]
        for r in con.execute("SELECT company_id, ticker, alias, alias_type FROM company_alias"):
            a = (r["alias"] or "").strip()
            if not a:
                continue
            if r["alias_type"] == "code":
                self.codes.append((re.compile(rf"(?<!\d){re.escape(a)}(?!\d)"), r["company_id"], r["ticker"]))
            else:
                self.plain.append((a.lower(), r["company_id"], r["ticker"]))
        # 长别名优先(信息量),但全部命中都收(多归)
        self.plain.sort(key=lambda x: -len(x[0]))

    def attribute(self, text: str) -> list[tuple]:
        """返回 [(company_id, ticker)] 去重。无命中 → []。"""
        if not text:
            return []
        low = text.lower()
        hits = {}
        for a, cid, tk in self.plain:
            if a in low:
                hits[cid] = tk
        for rgx, cid, tk in self.codes:
            if rgx.search(text):
                hits[cid] = tk
        return list(hits.items())


# ════════════════════ 统一限流器(令牌桶,文件持久,跨 subprocess)════════════════════
class RateLimiter:
    """兼容包装；``infos`` 始终走所有舆情客户端共用的原子账号级令牌。"""

    def __init__(self, key: str, interval_sec: float):
        CACHE_YUQING.mkdir(parents=True, exist_ok=True)
        self.path = CACHE_YUQING / f"rl_{key}.txt"
        self.interval = (
            max(float(interval_sec), DEFAULT_INTERVAL_SECONDS)
            if key == "infos" else float(interval_sec)
        )
        self._shared = (
            SharedSubjectInfosLimiter(
                cache_dir=CACHE_YUQING,
                interval_seconds=self.interval,
            )
            if key == "infos" else None
        )

    def _last(self) -> float:
        try:
            return float(self.path.read_text().strip())
        except Exception:
            return 0.0

    def acquire(self):
        if self._shared is not None:
            self._shared.acquire()
            return
        wait = self.interval - (time.time() - self._last())
        if wait > 0:
            time.sleep(wait)
        self.path.write_text(str(time.time()))


# ════════════════════ 来源权重(散户加权)════════════════════
def retail_weight(platform: str, weights: dict | None = None) -> float:
    w = weights or DEFAULT_RETAIL_WEIGHTS
    return float(w.get(platform, 1.0))


# ════════════════════ senti_raw 统一写入(抽公共,两个 fetcher 共用)════════════════════
RAW_COLS = ["bucket_id", "company_id", "ticker", "source_layer", "platform", "attitude", "attitude_src",
            "dedup_key", "post_id", "title", "url", "author", "author_uid", "fans_count", "auth_type",
            "web_name", "domain", "channel", "media_type", "hot_value", "read_count", "reply_count",
            "heat_value", "sampled", "sim_hash", "publish_time",
            "reason", "as_of", "fetched_at", "backfilled"]
_RAW_SQL = (f"INSERT OR IGNORE INTO senti_raw({','.join(RAW_COLS)}) "
            f"VALUES({','.join('?' * len(RAW_COLS))})")


def insert_raw(con, **kw) -> int:
    """统一写 senti_raw(去重 UNIQUE(company_id,source_layer,dedup_key))。返回 1 入库 / 0 命中去重。
    缺省字段填 None;调用方至少给 bucket_id/company_id/ticker/source_layer/platform/dedup_key/attitude_src/fetched_at。"""
    cur = con.execute(_RAW_SQL, [kw.get(c) for c in RAW_COLS])
    return cur.rowcount


def load_layer_config() -> dict:
    """读 config.yaml 的 sentiment_layers(缺省回落默认)。"""
    cfg_path = ROOT / "tools" / "dynamic" / "config.yaml"
    try:
        import yaml
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        return cfg.get("sentiment_layers", {}) or {}
    except Exception:
        return {}


# ════════════════════ 热度值 / 分层抽样(替换"每桶前N条")════════════════════
DEFAULT_SAMPLING = {"max_per_bucket": 50, "top_by_heat": 40, "random_floor": 10,
                    "reply_heat_weight": 3, "coverage_low": 0.5}


def load_sampling_config() -> dict:
    """读 sentiment_layers.sampling(缺省回落 DEFAULT_SAMPLING)。"""
    s = (load_layer_config().get("sampling") or {})
    return {**DEFAULT_SAMPLING, **s}


def heat_value(platform: str, hot_value, read_count, reply_count, reply_weight: int = 3) -> int:
    """每帖热度。星瀚帖(雪球/微博/新闻)= hot_value(相似信息条数);
    股吧帖 = read + reply*reply_weight(评论比浏览更费力,权重更高)。无热度 → 0(只进随机池,不进 Top)。"""
    if platform == "guba":
        return int((read_count or 0) + (reply_count or 0) * reply_weight)
    return int(hot_value or 0)


def _stable_seed(s: str) -> int:
    """稳定 hash(不受 PYTHONHASHSEED 影响,跨进程可复现)。"""
    return int.from_bytes(hashlib.sha1(s.encode("utf-8")).digest()[:8], "big")


def select_sample(items, *, max_per_bucket=50, top_by_heat=40, random_floor=10, seed=0):
    """单个 (platform, company, bucket) 组的分层抽样。
    items: 可迭代 (key, heat_value, scored_bool)。scored=已打分(算进配额,不浪费已有结果)。
    返回 (sampled_keys:set, excluded_keys:set)。
      - 组内帖数 ≤ max_per_bucket:全部入样本(全覆盖)。
      - > max_per_bucket:已打分先占配额 → 余额按 heat 降序取 Top(预留 random_floor 个真随机槽)→ 真随机补足。
      - ??真随机:random.Random(seed) 打乱后取前 N,seed 稳定可复现,绝不退化成"取后 N 条"。"""
    items = [(k, (h or 0), bool(s)) for k, h, s in items]
    keys = [it[0] for it in items]
    total = len(keys)
    if total <= max_per_bucket:
        return set(keys), set()                       # 全覆盖
    target = max_per_bucket
    sampled = {it[0] for it in items if it[2]}          # 已打分算进配额
    unscored = [(it[0], it[1]) for it in items if not it[2]]
    quota = target - len(sampled)
    if quota > 0 and unscored:
        hot = sorted([u for u in unscored if u[1] > 0], key=lambda x: -x[1])   # 有热度 → 可进 Top
        cold = [u for u in unscored if u[1] <= 0]                              # 无热度 → 只进随机池
        # 预留 random_floor 个真随机槽(材料够且配额 > 保底时)
        reserve = random_floor if (len(unscored) > quota and quota > random_floor) else 0
        n_top = max(0, min(top_by_heat, quota - reserve, len(hot)))
        sampled |= {k for k, _ in hot[:n_top]}
        pool = hot[n_top:] + cold                       # Top 之外的热帖 + 全部无热度帖 → 随机池
        rng = random.Random(seed)
        rng.shuffle(pool)
        n_rand = target - len(sampled)
        sampled |= {k for k, _ in pool[:n_rand]}
    excluded = set(keys) - sampled
    return sampled, excluded


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # 自测:桶模型
    now = datetime.now(TZ)
    print("now bucket:", bucket_for(now))
    print("03:30 bucket:", bucket_for(now.replace(hour=3, minute=30)))
    print("21:00 bucket:", bucket_for(now.replace(hour=21, minute=0)))
    rng = buckets_in_range(now - timedelta(days=1), now)
    print(f"近 2 日桶数: {len(rng)}")
    for b in rng[:6]:
        print("  ", b["bucket_id"], b["span_hours"], "h")
