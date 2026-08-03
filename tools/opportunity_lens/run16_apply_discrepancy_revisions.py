from __future__ import annotations

"""Apply evidence-backed Run16 forecast revisions after discrepancy review.

The script records old/new assumptions and the new facts that justified each
change.  It does not pull the model mechanically toward consensus.
"""

import argparse
import json
from pathlib import Path
from typing import Any


REVISIONS: dict[str, dict[str, Any]] = {
    "300308.SZ": {
        "reason": (
            "2026Q1法定收入194.96亿元、归母净利润57.35亿元，分别同比增长192.12%和262.28%；"
            "按2025年季节性和两份2026年5—7月机构报告复核后，原FY2026—FY2028收入路径明显低估当前放量。"
        ),
        "sources": [
            "中际旭创2026Q1报告（2026-04-17，巨潮资讯）",
            "天风证券中际旭创报告（2026-05-23）",
            "Morgan Stanley中际旭创报告（2026-07-17，调整后利润口径）",
        ],
        "metrics": {
            "revenue_growth_pct": {
                "downside": [100, 35, 15], "base": [145, 65, 40], "upside": [165, 80, 50]
            },
            "gross_margin_pct": {
                "downside": [38, 36, 34], "base": [45, 45, 44], "upside": [48, 48, 47]
            },
            "parent_net_margin_pct": {
                "downside": [25, 23, 21], "base": [31, 32.5, 33], "upside": [35, 36, 36]
            },
            "ocf_margin_pct": {
                "downside": [17, 18, 18], "base": [24, 25, 26], "upside": [30, 31, 31]
            },
            "capex_margin_pct": {
                "downside": [13, 11, 9], "base": [10, 8, 7], "upside": [9, 7, 6]
            },
            "total_assets_growth_pct": {
                "downside": [28, 18, 12], "base": [45, 40, 30], "upside": [58, 48, 38]
            },
        },
    },
    "002837.SZ": {
        "reason": (
            "2026Q1利润很弱，不能直接采用卖方高利润率；但UBS（2026-07-23）与华泰（2026-04-23）"
            "均把海外液冷放量放在2026年下半年及2027年，且2025年年报披露冷板、快接、分水器和CDU验证。"
            "因此上调收入路径，但利润率仍明显低于卖方高情景。"
        ),
        "sources": [
            "英维克2025年年报（2026-04-21）",
            "华泰证券英维克报告（2026-04-23）",
            "UBS英维克报告（2026-07-23）",
        ],
        "metrics": {
            "revenue_growth_pct": {
                "downside": [25, 20, 15], "base": [63, 45, 32], "upside": [80, 58, 42]
            },
            "gross_margin_pct": {
                "downside": [24, 24, 25], "base": [28, 30, 32], "upside": [32, 34, 35]
            },
            "parent_net_margin_pct": {
                "downside": [4, 5, 6], "base": [9, 11.5, 13.5], "upside": [12, 14.5, 16]
            },
            "ocf_margin_pct": {
                "downside": [4, 5, 6], "base": [8, 10, 12], "upside": [13, 15, 16]
            },
            "capex_margin_pct": {
                "downside": [10, 9, 8], "base": [8, 7, 6], "upside": [7, 6, 5]
            },
            "total_assets_growth_pct": {
                "downside": [15, 12, 10], "base": [30, 25, 20], "upside": [40, 34, 28]
            },
        },
    },
    "002364.SZ": {
        "reason": (
            "公司年报证明240V/336V/800V HVDC和服务器PSU产品映射，但客户与订单仍未公开；"
            "东北证券2026-05-21报告与Wind对FY2026—FY2028收入路径接近。"
            "因此只温和上调收入，仍保留小基数、验收和客户证据不足的折价。"
        ),
        "sources": [
            "中恒电气2025年年报（2026-04-21）",
            "东北证券中恒电气报告（2026-05-21）",
        ],
        "metrics": {
            "revenue_growth_pct": {
                "downside": [10, 10, 8], "base": [35, 38, 30], "upside": [50, 50, 40]
            },
        },
    },
}


def build(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    audit: list[dict[str, Any]] = []
    by_ticker = {row["ticker"]: row for row in payload["companies"]}
    for ticker, revision in REVISIONS.items():
        company = by_ticker[ticker]
        changes: list[dict[str, Any]] = []
        for metric, scenario_values in revision["metrics"].items():
            item = company["forecast_assumptions"][metric]
            for scenario, values in scenario_values.items():
                for year, value in zip(("2026", "2027", "2028"), values):
                    old = item["values"][scenario][year]
                    item["values"][scenario][year] = value
                    changes.append(
                        {"metric": metric, "scenario": scenario, "year": year, "old": old, "new": value}
                    )
            item["source_ref"] = "；".join(revision["sources"])
            item["rationale"] = revision["reason"]
        audit.append(
            {
                "ticker": ticker,
                "company": company["name"],
                "reason": revision["reason"],
                "sources": revision["sources"],
                "changes": changes,
                "mechanical_convergence_to_external_forecast": False,
            }
        )
    payload["discrepancy_revision_log"] = audit
    return payload, audit


def _markdown(audit: list[dict[str, Any]]) -> str:
    lines = [
        "# Run16 财务差异专项复查",
        "",
        "本轮先冻结独立模型，再与Wind一致预期及最近两个季度的逐份机构报告对账。只有重新核对公司公告、季度事实和报告假设后发现原模型遗漏事实时才修改；没有把模型机械拉向一致预期。",
        "",
    ]
    for row in audit:
        lines.extend(
            [
                f"## {row['company']}（{row['ticker']}）",
                "",
                row["reason"],
                "",
                "复核材料：" + "；".join(row["sources"]) + "。",
                "",
            ]
        )
    lines.extend(
        [
            "## 保留而未修改的主要分歧",
            "",
            "同花顺的收入已接近外部预测，分歧主要来自净利率，因此保留较保守的利润率；澜起科技差异主要来自投资收益和高毛利新品持续性的判断，未据此追高；润泽科技在剔除2025年资产处置收益后，独立模型保留较低正常化净利率。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-json", type=Path, required=True)
    parser.add_argument("--audit-md", type=Path, required=True)
    args = parser.parse_args()
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    payload, audit = build(payload)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.audit_json.parent.mkdir(parents=True, exist_ok=True)
    args.audit_json.write_text(json.dumps({"schema_version": "run16.discrepancy_review.v1", "companies": audit}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.audit_md.write_text(_markdown(audit) + "\n", encoding="utf-8")
    print(json.dumps({"companies_revised": len(audit), "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
