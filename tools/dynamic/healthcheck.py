#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stage 3 平台/数据桥健康探测(P0-3:四档判断)

四档:
  healthy        2xx                         端点正常
  auth_required  400/401/403/舆情认证失败    端点或上游认证异常
  unhealthy      其他 4xx / 5xx              端点异常/限流(Nitter 多属此 → 剔除)
  dead           DNS失败/超时/拒连/SSL err   端点死(剔除)

微博 KOL 检查舆情 API 作者匹配状态，不请求微博网页；其他平台仍只探端点、不存内容。
用法:python tools/dynamic/healthcheck.py
"""
from __future__ import annotations
import sys, io, ssl
from pathlib import Path
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = ROOT / "tools" / "dynamic" / "config.yaml"
OUT = ROOT / "cache" / f"dynamic_healthcheck_{datetime.now().date().isoformat()}.md"
sys.path.insert(0, str(ROOT))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
TIMEOUT = 8
import yaml
CFG = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
from tools.dynamic.fetchers.voice_fetcher import WeiboFetcher
from tools.dynamic import quiet_hours
_ctx = ssl.create_default_context(); _ctx.check_hostname = False; _ctx.verify_mode = ssl.CERT_NONE
TIERS = ["healthy", "auth_required", "unhealthy", "dead"]


def probe(url: str) -> dict:
    """四档判断。"""
    req = Request(url, headers={"User-Agent": UA, "Accept": "*/*"}, method="GET")
    try:
        with urlopen(req, timeout=TIMEOUT, context=_ctx) as r:
            return {"url": url, "code": r.status, "tier": "healthy", "note": f"HTTP {r.status} OK"}
    except HTTPError as e:
        if e.code in (400, 401, 403):
            return {"url": url, "code": e.code, "tier": "auth_required", "note": f"HTTP {e.code} 需 cookie/登录"}
        return {"url": url, "code": e.code, "tier": "unhealthy", "note": f"HTTP {e.code} 服务端异常/限流"}
    except (URLError, TimeoutError) as e:
        return {"url": url, "code": None, "tier": "dead", "note": f"DEAD: {getattr(e, 'reason', e)}"}
    except Exception as e:
        return {"url": url, "code": None, "tier": "dead", "note": f"DEAD: {type(e).__name__} {e}"}


def probe_weibo_api(author_uid: str) -> dict:
    cfg = CFG["platforms"].get("weibo", {}) or {}
    fetcher = WeiboFetcher(cfg)
    try:
        posts = fetcher.fetch({"account_handle": author_uid})
        status = str(fetcher.last_status or "system_error")
    except Exception as exc:
        posts = []
        status = f"system_error:{type(exc).__name__}"
    if status == "ok" and posts:
        tier = "healthy"
    elif status.startswith("auth_expired"):
        tier = "auth_required"
    elif status in {"empty", "rate_limited", "cached_stale", "api_miss"}:
        tier = "unhealthy"
    else:
        tier = "dead"
    return {
        "url": "yuqing-api:subject/infos#exact-author-uid",
        "code": None,
        "tier": tier,
        "note": f"{status}: matched_posts={len(posts)}",
    }


def main():
    if quiet_hours.is_weekend():
        return
    leaders = {L["platform"]: L for L in CFG["opinion_leaders"]}
    results = []  # (group, label, platform, result)

    if "xueqiu" in leaders:
        h = leaders["xueqiu"]["handle"]
        for tpl in CFG["platforms"]["xueqiu"]["priority_urls"]:
            results.append(("雪球 P1", "汤诗语", "xueqiu", probe(tpl.format(handle=h))))
    for leader in (L for L in CFG["opinion_leaders"] if L["platform"] == "weibo"):
        results.append(
            (
                "微博 KOL 舆情 API",
                f"{leader['name']}({leader['handle']})",
                "weibo",
                probe_weibo_api(str(leader["handle"])),
            )
        )
    xh = next((L["handle"] for L in CFG["opinion_leaders"] if L["platform"] == "twitter"), "GavinSBaker")
    for inst in CFG["platforms"]["twitter"]["nitter_instances"]:
        results.append(("X/Nitter", f"@{xh}", "twitter", probe(inst.format(handle=xh))))

    grouped = {t: [] for t in TIERS}
    for grp, label, plat, r in results:
        grouped[r["tier"]].append((grp, label, plat, r))

    lines = [f"# Stage 3 平台健康探测(四档)— {datetime.now().isoformat(timespec='seconds')}", "",
             "> 微博 KOL 仅检查舆情 API 的作者 UID 精确匹配，不登录或请求微博网页；其他项仅探端点。", ""]
    print("=== 四档健康探测 ===")
    icon = {
        "healthy": "[OK]",
        "auth_required": "[AUTH]",
        "unhealthy": "[WARN]",
        "dead": "[DEAD]",
    }
    for t in TIERS:
        lines.append(f"## {icon[t]} {t}({len(grouped[t])})")
        for grp, label, plat, r in grouped[t]:
            lines.append(f"- [{grp}] {label}  code={r['code']}  {r['note']}  | {r['url']}")
            print(f"  {icon[t]} {t:<14}[{grp}] {label} code={r['code']}")
        lines.append("")

    # 建议
    lines.append("## 建议(3-D 实施时)")
    nitter_alive = [r["url"] for g, l, p, r in results if g == "X/Nitter" and r["tier"] == "healthy"]
    nitter_drop = [r["url"] for g, l, p, r in results if g == "X/Nitter" and r["tier"] in ("unhealthy", "dead")]
    xueqiu_auth = [f"{l}({r['tier']})" for g, l, p, r in results if p == "xueqiu"]
    weibo_api = [f"{l}({r['tier']})" for g, l, p, r in results if p == "weibo"]
    lines.append(f"- X/Nitter 健康实例:{nitter_alive or '无 healthy → X 优先级1 不可用,直接降级 playwright/手动粘贴'}")
    lines.append(f"- X/Nitter 剔除(unhealthy/dead):{nitter_drop or '无'}")
    lines.append(f"- 雪球:{xueqiu_auth}(auth_required=需 user cookie)")
    lines.append(f"- 微博:{weibo_api}(舆情 API 重点账号池 + UID 精确匹配；不配置微博 cookie)")
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n四档统计: " + " ".join(f"{t}={len(grouped[t])}" for t in TIERS))
    print(f"报告 → {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
