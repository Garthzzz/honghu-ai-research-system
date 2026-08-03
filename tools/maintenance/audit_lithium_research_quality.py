from __future__ import annotations

"""Deterministic quality audit for the rebuilt lithium research libraries."""

import argparse
import json
import re
from pathlib import Path
from typing import Any

from tools.pipeline.lithium_research_content import make_documents
from tools.pipeline.lithium_research_data import SOURCE_SPECS


ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "cache" / "lithium_research" / "models"
COMPANIES = (
    "赣锋锂业",
    "融捷股份",
    "盛新锂能",
    "盐湖股份",
    "大中矿业",
    "雅化集团",
    "天华新能",
    "天齐锂业",
    "永杉锂业",
    "中矿资源",
    "藏格矿业",
    "西藏城投",
    "永兴材料",
)
STALE_OR_FORBIDDEN = (
    "2026年-4万吨、2027年-4万吨、2028年-8万吨",
    "2028年基准缺口为0.35",
    "2026年的-0.02百万吨缺口",
    "2028年的-0.35百万吨",
    "2028年基准供给2.91",
    "字段完成情况",
    "参数 owner",
    "决策验证债",
    "联合情景树、概率更新与破坏程度",
)


def _load(name: str) -> dict[str, Any]:
    return json.loads((MODEL_DIR / name).read_text(encoding="utf-8"))


def _model_checks() -> list[str]:
    issues: list[str] = []
    lithium = _load("lithium_supply_demand_model_v1.json")
    carbonate = _load("carbonate_supply_demand_model_v1.json")
    expected = {
        2025: (1.491, 1.376),
        2026: (1.716, 1.572),
        2027: (1.945, 1.795),
        2028: (2.150, 2.033),
        2029: (2.276, 2.229),
        2030: (2.379, 2.411),
        2031: (2.636, 2.641),
    }
    rows = {int(row["year"]): row for row in lithium["base_rows"]}
    if set(rows) != set(expected):
        issues.append("全球锂官方基准年份不是2025—2031完整序列")
    for year, (supply, demand) in expected.items():
        row = rows.get(year) or {}
        if abs(float(row.get("available_supply_mt_lce", -99)) - supply) > 1e-9:
            issues.append(f"全球锂{year}供给未对齐澳大利亚政府基准")
        if abs(float(row.get("demand_mt_lce", -99)) - demand) > 1e-9:
            issues.append(f"全球锂{year}需求未对齐澳大利亚政府基准")
        if abs(
            float(row.get("balance_mt_lce", -99)) - round(supply - demand, 3)
        ) > 1e-9:
            issues.append(f"全球锂{year}余额无法复算")
    country = lithium.get("country_mine_2025") or {}
    if abs(float(country.get("cr3_pct", 0)) - 72.41) > 0.01:
        issues.append("全球锂矿国家CR3错误")
    if abs(float(country.get("cr5_pct", 0)) - 90.00) > 0.01:
        issues.append("全球锂矿国家CR5错误")

    observed = carbonate.get("observed_2026_h1") or {}
    if observed.get("domestic_output_range_mt") != [0.5936, 0.63]:
        issues.append("2026H1国内碳酸锂产量区间错误")
    if abs(float(observed.get("imports_mt", 0)) - 0.179) > 1e-9:
        issues.append("2026H1碳酸锂进口错误")
    if abs(float(observed.get("exports_mt", 0)) - 0.002348) > 1e-9:
        issues.append("2026H1碳酸锂出口错误")
    for row in carbonate["rows"]:
        available = (
            float(row["domestic_output_mt"])
            + float(row["imports_mt"])
            - float(row["exports_mt"])
        )
        if abs(available - float(row["available_supply_mt"])) > 1e-6:
            issues.append(f"碳酸锂{row['year']}表观供给无法复算")
        if abs(
            available - float(row["demand_mt"]) - float(row["balance_mt"])
        ) > 1e-6:
            issues.append(f"碳酸锂{row['year']}余额无法复算")
    return issues


def _document_checks(
    industry_filter: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    source_ids = {
        str(source["source_ref"]): index
        for index, source in enumerate(SOURCE_SPECS, start=1)
    }
    summary: dict[str, Any] = {}
    for industry, industry_id in (("锂", 27), ("碳酸锂", 28)):
        if industry_filter and industry != industry_filter:
            continue
        docs = make_documents(industry, industry_id, source_ids)
        total_chars = sum(len(text) for text in docs.values())
        citations = {
            int(value)
            for text in docs.values()
            for value in re.findall(r"\^src:(\d+)", text)
        }
        tables = sum(text.count("|---") for text in docs.values())
        summary[industry] = {
            "document_count": len(docs),
            "total_characters": total_chars,
            "unique_citations": len(citations),
            "table_count": tables,
        }
        if len(docs) != 11:
            issues.append(f"{industry}文档数不是11")
        if total_chars < 50_000:
            issues.append(f"{industry}总正文少于5万字节级字符")
        if len(citations) < 20:
            issues.append(f"{industry}独立公开来源覆盖不足20")
        for filename, text in docs.items():
            is_q_document = bool(re.search(r"_Q[0-7]_", filename))
            if is_q_document:
                if "## 本章综述" not in text:
                    issues.append(f"{filename}缺少本章综述")
                required_topic_sections = (
                    "### 问题",
                    "### 研究方法与数据",
                    "### 研究与分析",
                    "### 总结",
                )
                section_counts = {
                    section: len(re.findall(rf"(?m)^{re.escape(section)}\s*$", text))
                    for section in required_topic_sections
                }
                if any(count == 0 for count in section_counts.values()):
                    missing = [
                        section.removeprefix("### ")
                        for section, count in section_counts.items()
                        if count == 0
                    ]
                    issues.append(f"{filename}缺少专题结构：{','.join(missing)}")
                elif len(set(section_counts.values())) != 1:
                    issues.append(
                        f"{filename}专题结构数量不一致：{section_counts}"
                    )
            lines = text.splitlines()
            index = 0
            while index < len(lines):
                if not lines[index].startswith("|"):
                    index += 1
                    continue
                start = index
                block: list[str] = []
                while index < len(lines) and lines[index].startswith("|"):
                    block.append(lines[index])
                    index += 1
                column_counts = [
                    len(re.findall(r"(?<!\\)\|", line)) - 1 for line in block
                ]
                if len(set(column_counts)) > 1:
                    issues.append(
                        f"{filename}:{start + 1}表格列数不一致{column_counts}"
                    )
            if filename.endswith("_公司透视.md"):
                for company in COMPANIES:
                    # 公司章节标题现在包含可视“公司”标签和详情页链接；
                    # 独立章节应按 H3 语义与规范链接识别，而不是要求公司名
                    # 必须紧跟在 ``### `` 后。
                    if not re.search(
                        rf"^###\s+.*\[{re.escape(company)}\]\(/company/\d+\)",
                        text,
                        flags=re.MULTILINE,
                    ):
                        issues.append(f"{filename}缺少{company}独立章节")
                    if not re.search(
                        rf"\[{re.escape(company)}\]\(/company/\d+\)", text
                    ):
                        issues.append(f"{filename}缺少{company}公司页链接")
                for phrase in (
                    "建模与外部对账",
                    "估值与交易观察",
                    "偏积极验证点",
                    "下修或回避条件",
                ):
                    if phrase not in text:
                        issues.append(f"{filename}缺少{phrase}")
            if filename.endswith("_估值对比.md"):
                for phrase in (
                    "正常化PE",
                    "PB—ROE",
                    "股权自由现金流",
                    "三情景",
                    "当前市场隐含预期",
                    "最近两个季度",
                ):
                    if phrase not in text:
                        issues.append(f"{filename}缺少{phrase}")
            for phrase in STALE_OR_FORBIDDEN:
                if phrase in text:
                    issues.append(f"{filename}仍包含旧结论或机器表达：{phrase}")
            if "\ufffd" in text or "???" in text:
                issues.append(f"{filename}包含损坏字符")
            for bad_punctuation in ("。；", "；。", "。。"):
                if bad_punctuation in text:
                    issues.append(
                        f"{filename}包含不自然的连续标点：{bad_punctuation}"
                    )
    return summary, issues


def audit(industry_filter: str | None = None) -> dict[str, Any]:
    model_issues = _model_checks()
    document_summary, document_issues = _document_checks(industry_filter)
    issues = model_issues + document_issues
    return {
        "status": "GREEN" if not issues else "RED",
        "model_issues": model_issues,
        "document_summary": document_summary,
        "document_issues": document_issues,
        "issues": issues,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "cache" / "lithium_research" / "quality_audit.json",
    )
    parser.add_argument("--industry", choices=("锂", "碳酸锂"))
    args = parser.parse_args()
    result = audit(args.industry)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "GREEN" else 1


if __name__ == "__main__":
    raise SystemExit(main())
