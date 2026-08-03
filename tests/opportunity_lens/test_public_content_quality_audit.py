from __future__ import annotations

import json
from pathlib import Path

from tools.opportunity_lens.public_content_quality_audit import (
    PUBLIC_AUDIT_FIELD,
    audit_markdown_scope,
    audit_run_pack,
    build_pack_audit_attestation,
    main,
    parse_markdown_tables,
    run_audit,
    validate_pack_audit_attestation,
)


def _natural_body(extra: str = "") -> str:
    return f"""我们要回答的问题是：现有资料是否支持这个判断？

公司年报和产品规格数据显示了当前进度，公开资料也保留了反方证据。^src:source_ref:SRC-1

我们先比较主体、时间和产品阶段，再按照公开数据进行估算。综合来看，可以认为当前结论有依据，但不能把产品展示等同于客户量产。

当前结论最受具名客户认证、重复订单和专项收入缺失影响；这些证据一旦出现，将直接改变商业化阶段判断。{extra}
"""


def _good_pack() -> dict:
    return {
        "slug": "byd_luxshare_human_quality_fixture",
        "display_title": "比亚迪与立讯进入高速光模块的研究",
        "research_question": "比亚迪与立讯进入后会怎样影响中际旭创和新易盛的财务与估值？",
        # 合法生产字段不属于公开正文，审计不得误报。
        "intake": {"canonical": "internal-only"},
        "sections": [
            {
                "section_key": "summary",
                "section_title": "摘要",
                "body_markdown": _natural_body(),
            },
            {
                "section_key": "probability",
                "section_title": "比亚迪和立讯未来三至五年能否形成有意义供应",
                "body_markdown": _natural_body(
                    """

| 公司 | 三年进入判断 | 五年进入判断 | 主要依据 |
|---|---:|---:|---|
| 比亚迪电子 | 约13% | 约31% | 尚缺产品和客户闭环 |
| 立讯精密 | 约46% | 约65% | 已有产品，头部客户尚未闭环 |

| 联合事件 | 三年判断 | 五年判断 | 为什么 |
|---|---:|---:|---|
| 至少一家进入 | 约50% | 约72% | 两家公司共享需求与认证约束 |
| 两家均进入 | 约9% | 约25% | 同时跨越客户和量产门槛更难 |
"""
                ),
            },
            {
                "section_key": "financial",
                "section_title": "竞争加剧会怎样影响龙头盈利和估值",
                "body_markdown": _natural_body(
                    """

| 公司 | 2023收入实际值 | 2024收入实际值 | 2025收入实际值 | 2025自由现金流 |
|---|---:|---:|---:|---:|
| 中际旭创 | 107.18 | 238.62 | 382.40 | 81.36 |
| 新易盛 | 30.98 | 86.47 | 248.42 | 63.81 |

| 公司 | 2031基准收入 | 2031竞争情景收入 | 2031净利润变化 | 2031自由现金流变化 |
|---|---:|---:|---:|---:|
| 中际旭创 | 500 | 455 | -12% | -16% |
| 新易盛 | 360 | 320 | -14% | -18% |

| 高速光模块收入暴露比例 | 中际旭创估值变化 | 新易盛估值变化 | 对结论的影响 |
|---:|---:|---:|---|
| 50% | -8% | -9% | 市场增长可吸收部分新增供应 |
| 75% | -13% | -15% | 需要更高安全边际 |
| 100% | -19% | -21% | 这是全公司收入暴露的上限压力测试 |
"""
                ),
            },
        ],
        "entity_sections": [
            {
                "entity_key": "byd",
                "section_title": "比亚迪电子距离高速光模块量产还有多远",
                "body_markdown": _natural_body(),
            }
        ],
    }


def _assembled_report(pack: dict) -> str:
    lines = [f"# {pack['display_title']}", ""]
    for section in pack["sections"]:
        lines.extend([f"## {section['section_title']}", "", section["body_markdown"], ""])
    for section in pack["entity_sections"]:
        lines.extend([f"## {section['section_title']}", "", section["body_markdown"], ""])
    return "\n".join(lines)


def test_good_pack_passes_without_requiring_fixed_subheadings():
    issues, metrics = audit_run_pack(_good_pack(), artifact="fixture.json", profile="auto")
    assert issues == []
    assert metrics["sections"] == 3
    assert metrics["entity_sections"] == 1
    assert metrics["main_tables"] == 5
    assert metrics["public_surface_values"] >= 6


def test_machine_terms_paths_urls_json_and_formula_source_are_blocked():
    body = """### 问题
字段完成情况与 canonical intake 如下，参数 owner 使用 D0/D1/D2 和 A—F、P/H/C。
[未知] 本节专属缺口；下一次更新见 D:\\quant\\industry_demo\\cache\\x.json。
裸地址 https://example.com/a，内部地址 opp://source/1，source_ref:ABC。
```json
{"low": 1, "mode": 2, "high": 3}
```
Wilson区间为 $center=(p+z^2/(2*n))/(1+z^2/n)$，并展示P10/P90。
"""
    result = audit_markdown_scope(
        body,
        artifact="bad.md",
        scope="bad",
        title="坏报告",
        role="section",
        target_profile=True,
    )
    codes = {issue.code for issue in result.issues}
    assert {
        "machine_term_canonical",
        "machine_term_intake",
        "machine_term_field_completion",
        "machine_term_parameter_owner",
        "machine_term_debt_code",
        "machine_term_scenario_code",
        "machine_term_architecture_code",
        "machine_term_quantile",
        "machine_term_wilson",
        "bad_label_unknown",
        "bad_label_section_boundary",
        "bad_label_next_update",
        "disk_path",
        "bare_url",
        "raw_internal_uri",
        "raw_source_ref",
        "raw_json",
        "formula_source_assignment",
    }.issubset(codes)


def test_markdown_link_and_citation_token_are_not_mistaken_for_bare_machine_output():
    body = _natural_body(
        "\n可在[交易所公告](https://example.com/report.pdf)中复核。正常公式 $P(A)=0.5$ 不应被当作源码。"
    )
    result = audit_markdown_scope(body, artifact="good.md", scope="good", title="这项判断是否成立", role="section")
    assert "bare_url" not in {issue.code for issue in result.issues}
    assert "raw_source_ref" not in {issue.code for issue in result.issues}
    assert "formula_source_assignment" not in {issue.code for issue in result.issues}


def test_bold_summary_is_not_mistaken_for_programming_exponent():
    body = _natural_body(
        "\n### 总结\n\n**正泰光伏的盈利质量需要现金回收验证。**"
    )
    result = audit_markdown_scope(
        body,
        artifact="good.md",
        scope="good",
        title="盈利质量是否改善",
        role="section",
    )
    assert "formula_programming_expression" not in {
        issue.code for issue in result.issues
    }


def test_tex_command_outside_math_boundary_is_rejected():
    result = audit_markdown_scope(
        _natural_body("\n未转译命令为 \\sqrt{x}。"),
        artifact="bad.md",
        scope="formula",
        title="这个公式如何计算",
        role="section",
    )
    assert "formula_raw_tex_command" in {issue.code for issue in result.issues}


def test_tables_require_consistent_columns_and_no_duplicate_headers_or_rows():
    text = """| 公司 | 结论 | 结论 |
|---|---|---|
| 甲 | 保持 | 保持 |
| 甲 | 保持 | 保持 |
| 乙 | 下调 |

| 公司 | 结论 | 结论 |
|---|---|---|
| 甲 | 保持 | 保持 |
"""
    tables = parse_markdown_tables(text, artifact="bad.md", scope="tables")
    assert len(tables) == 2
    result = audit_markdown_scope(text, artifact="bad.md", scope="tables", title="表格", role="report", enforce_structure=False)
    codes = [issue.code for issue in result.issues]
    assert "table_duplicate_column" in codes
    assert "table_duplicate_header" in codes
    assert "table_duplicate_row" in codes
    assert "table_duplicate_row_across_tables" in codes
    assert "table_column_count_mismatch" in codes


def test_empty_table_and_paragraph_in_last_column_are_rejected():
    long_text = "这是一段不应塞进表格最后一列的分析。" * 12
    text = f"""| 公司 | 分析 |
|---|---|
| 甲 | {long_text} |

| 指标 | 数值 |
|---|---:|
"""
    result = audit_markdown_scope(text, artifact="bad.md", scope="tables", title="表格", role="report", enforce_structure=False)
    codes = {issue.code for issue in result.issues}
    assert "table_last_column_prose_overload" in codes
    assert "table_without_data" in codes


def test_probability_and_finance_table_limits_and_required_finance_analysis():
    pack = _good_pack()
    probability = pack["sections"][1]
    probability["body_markdown"] += """
| 概率事件 | 三年概率 | 五年概率 |
|---|---:|---:|
| 全球客户进入 | 9% | 29% |
"""
    financial = pack["sections"][2]
    financial["body_markdown"] += """
| 财务补充 | 收入 | 利润 |
|---|---:|---:|
| 重复表 | 1 | 1 |
"""
    issues, _ = audit_run_pack(pack, artifact="bad.json", profile="byd_luxshare")
    codes = {issue.code for issue in issues}
    assert "probability_table_limit" in codes
    assert "finance_table_limit" in codes

    no_sensitivity = _good_pack()
    no_sensitivity["sections"][2]["body_markdown"] = no_sensitivity["sections"][2]["body_markdown"].split(
        "| 高速光模块收入暴露比例"
    )[0]
    issues, _ = audit_run_pack(no_sensitivity, artifact="missing.json", profile="byd_luxshare")
    assert "finance_sensitivity_analysis_missing" in {issue.code for issue in issues}

    prose_sensitivity = _good_pack()
    prose_sensitivity["sections"][2]["body_markdown"] = prose_sensitivity["sections"][2]["body_markdown"].split(
        "| 高速光模块收入暴露比例"
    )[0] + (
        "\n受影响收入敏感度显示：业务暴露每增加10个百分点，2031年净利润约下降2.1个百分点，"
        "现金流约下降4.5个百分点；这说明现金回报比收入更敏感。\n"
    )
    issues, _ = audit_run_pack(
        prose_sensitivity,
        artifact="prose.json",
        profile="byd_luxshare",
    )
    assert "finance_sensitivity_analysis_missing" not in {
        issue.code for issue in issues
    }


def test_entity_field_completion_matrix_is_rejected():
    pack = _good_pack()
    pack["entity_sections"][0]["body_markdown"] += "\n经营字段逐项完成矩阵已经完成。"
    issues, _ = audit_run_pack(pack, artifact="bad.json", profile="auto")
    codes = {issue.code for issue in issues}
    assert "entity_field_matrix" in codes
    assert "machine_term_field_completion" in codes


def test_duplicate_table_shape_across_main_sections_is_rejected():
    pack = _good_pack()
    duplicate = """
| 公司 | 三年进入判断 | 五年进入判断 | 主要依据 |
|---|---:|---:|---|
| 比亚迪电子 | 约13% | 约31% | 尚缺产品和客户闭环 |
"""
    pack["sections"][0]["body_markdown"] += duplicate
    issues, _ = audit_run_pack(pack, artifact="bad.json", profile="auto")
    codes = {issue.code for issue in issues}
    assert "table_duplicate_header_across_sections" in codes
    assert "table_duplicate_row_across_sections" in codes


def test_generic_profile_does_not_unconditionally_block_specialized_statistics():
    body = _natural_body("\n统计附注说明 Wilson 区间、P10/P90 与 Fréchet 依赖；这些术语在本通用案例中已经解释用途。")
    generic = audit_markdown_scope(
        body,
        artifact="generic.md",
        scope="generic",
        title="这个统计判断是否成立",
        role="section",
        target_profile=False,
    )
    strict = audit_markdown_scope(
        body,
        artifact="strict.md",
        scope="strict",
        title="这个统计判断是否成立",
        role="section",
        target_profile=True,
    )
    generic_codes = {issue.code for issue in generic.issues}
    strict_codes = {issue.code for issue in strict.issues}
    assert not {"machine_term_quantile", "machine_term_wilson", "machine_term_frechet"} & generic_codes
    assert {"machine_term_quantile", "machine_term_wilson", "machine_term_frechet"} <= strict_codes


def test_titles_targets_recommendations_and_visual_notes_are_public_surfaces():
    pack = _good_pack()
    pack["entity_investment_targets"] = [
        {
            "target_name": "示例标的",
            "conditional_investment_recommendation": "canonical intake 完成后再研究。",
            "target_data_points": [],
        }
    ]
    pack["visuals"] = [
        {
            "block_key": "risk",
            "title": "风险图",
            "subtitle": "显示 P10/P90 专家压力带。",
            "data": {"series_label": "架构状态 A"},
        }
    ]
    issues, _ = audit_run_pack(pack, artifact="surface.json", profile="byd_luxshare")
    codes = {issue.code for issue in issues}
    assert "machine_term_canonical" in codes
    assert "machine_term_intake" in codes
    assert "machine_term_quantile" in codes
    assert "bad_label_damage" in codes
    assert "bad_label_architecture_status" in codes


def test_source_freshness_warning_rejects_machine_codes():
    pack = _good_pack()
    pack["sources"] = [
        {
            "ref": "OLD-1",
            "freshness_warning": "SEVERE_OLD_FOR_CURRENT_JUDGMENT",
        }
    ]
    issues, _ = audit_run_pack(
        pack,
        artifact="freshness.json",
        profile="byd_luxshare",
    )
    assert "machine_term_freshness_code" in {issue.code for issue in issues}

    pack["sources"][0]["freshness_warning"] = (
        "严重时效提醒：该2024年记录只证明当时活动，不能单独证明截至2026年的量产状态。"
    )
    issues, _ = audit_run_pack(
        pack,
        artifact="freshness-human.json",
        profile="byd_luxshare",
    )
    assert "machine_term_freshness_code" not in {issue.code for issue in issues}


def test_public_surfaces_reject_machine_date_enums_but_allow_iso_dates():
    pack = _good_pack()
    pack["sections"][0]["body_markdown"] += "\n事件周期为 current_at_fetch 和2026-spring。"
    issues, _ = audit_run_pack(pack, artifact="raw-date.json", profile="byd_luxshare")
    assert "machine_term_raw_date_enum" in {issue.code for issue in issues}

    pack["sections"][0]["body_markdown"] = pack["sections"][0]["body_markdown"].replace(
        "current_at_fetch 和2026-spring", "截至本次访问和2026年春季招聘周期"
    )
    pack["sections"][0]["body_markdown"] += "\n核验日期为2026-07-18。"
    issues, _ = audit_run_pack(pack, artifact="human-date.json", profile="byd_luxshare")
    assert "machine_term_raw_date_enum" not in {issue.code for issue in issues}


def test_original_user_question_keeps_wording_but_still_blocks_safety_leaks():
    pack = _good_pack()
    pack["problem_statement"] = "判断两家公司进入后会怎样影响现有龙头。"
    pack["research_question"] = "用户原话要求比较情景 A—F 和破坏程度。"
    issues, _ = audit_run_pack(pack, artifact="request.json", profile="byd_luxshare")
    codes = {issue.code for issue in issues}
    assert "machine_term_scenario_code" not in codes
    assert "bad_label_damage" not in codes

    pack["research_question"] += " 原始路径 D:\\private\\request.json。"
    issues, _ = audit_run_pack(pack, artifact="request.json", profile="byd_luxshare")
    assert "disk_path" in {issue.code for issue in issues}


def test_long_paragraph_repetition_across_sections_is_rejected():
    pack = _good_pack()
    repeated = "这段分析逐项解释主体、时期、证据、计算和结论，并说明反方证据怎样改变最终判断。" * 8
    pack["sections"][0]["body_markdown"] += f"\n\n{repeated}"
    pack["sections"][1]["body_markdown"] += f"\n\n{repeated}"
    issues, _ = audit_run_pack(pack, artifact="duplicate.json", profile="generic")
    assert "long_paragraph_duplicate" in {issue.code for issue in issues}


def test_embedded_audit_becomes_stale_after_public_content_changes():
    pack = _good_pack()
    pack[PUBLIC_AUDIT_FIELD] = build_pack_audit_attestation(pack, profile="auto")
    _, errors = validate_pack_audit_attestation(pack, profile="auto")
    assert errors == []
    pack["display_title"] += "（修订）"
    _, errors = validate_pack_audit_attestation(pack, profile="auto")
    assert any("已失效" in error and "pack_sha256" in error for error in errors)


def test_cli_writes_readable_json_and_markdown(tmp_path: Path):
    pack_path = tmp_path / "run_pack.json"
    report_path = tmp_path / "final_report.md"
    json_output = tmp_path / "audit.json"
    markdown_output = tmp_path / "audit.md"
    pack = _good_pack()
    pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
    report_path.write_text(_assembled_report(pack), encoding="utf-8")
    exit_code = main(
        [
            "--run-pack",
            str(pack_path),
            "--report",
            str(report_path),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
        ]
    )
    assert exit_code == 0
    result = json.loads(json_output.read_text(encoding="utf-8"))
    assert result["status"] == "PASS"
    assert result["summary"]["errors"] == 0
    assert "结果：**PASS**" in markdown_output.read_text(encoding="utf-8")


def test_final_report_title_and_section_completeness_are_enforced(tmp_path: Path):
    pack_path = tmp_path / "run_pack.json"
    report_path = tmp_path / "final_report.md"
    pack = _good_pack()
    pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
    report_path.write_text("# 错误标题\n\n## 摘要\n\n只保留一个章节。", encoding="utf-8")
    result = run_audit(run_pack_path=pack_path, report_path=report_path, profile="auto")
    codes = {issue["code"] for issue in result["issues"]}
    assert result["status"] == "FAIL"
    assert "final_report_title_mismatch" in codes
    assert "final_report_section_missing" in codes


def test_final_report_does_not_repeat_separate_entity_pages(tmp_path: Path):
    pack_path = tmp_path / "run_pack.json"
    report_path = tmp_path / "final_report.md"
    pack = _good_pack()
    pack_path.write_text(json.dumps(pack, ensure_ascii=False), encoding="utf-8")
    lines = [f"# {pack['display_title']}", ""]
    for section in pack["sections"]:
        lines.extend(
            [f"## {section['section_title']}", "", section["body_markdown"], ""]
        )
    report_path.write_text("\n".join(lines), encoding="utf-8")
    result = run_audit(
        run_pack_path=pack_path,
        report_path=report_path,
        profile="auto",
    )
    entity_consistency_codes = {
        issue["code"]
        for issue in result["issues"]
        if str(issue["scope"]).startswith("entity:")
    }
    assert not {
        "final_report_section_missing",
        "final_report_section_incomplete",
    } & entity_consistency_codes


def test_run_audit_is_stable_for_the_same_inputs(tmp_path: Path):
    pack_path = tmp_path / "run_pack.json"
    pack_path.write_text(json.dumps(_good_pack(), ensure_ascii=False), encoding="utf-8")
    first = run_audit(run_pack_path=pack_path, report_path=None, profile="auto")
    second = run_audit(run_pack_path=pack_path, report_path=None, profile="auto")
    assert first == second
