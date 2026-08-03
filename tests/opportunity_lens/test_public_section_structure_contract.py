from tools.opportunity_lens.run_pack_contract import (
    _structured_public_body_issues,
    public_markdown_character_count,
)
from tools.research_core.config import resolve_track_config


def test_explicit_problem_method_analysis_summary_structure_passes() -> None:
    body = """### 问题
这一部分明确提出需要回答的研究问题，不把用户的完整请求原样粘贴进来。

### 研究方法与数据
这一部分说明采用的公司公告、行业数据和计算方法，以及数据口径和局限。

### 研究与分析
这一部分解释事实怎样传导到经营、现金流和估值，并讨论反方证据。

### 总结
这一部分直接写明研究主体、期限、事件和影响，形成可独立阅读的结论。
"""
    assert _structured_public_body_issues(body, "section") == []


def test_continuous_long_text_without_visible_structure_fails() -> None:
    body = "研究问题、数据、方法、分析和总结全部揉在一个很长的连续段落中。" * 20
    issues = _structured_public_body_issues(body, "section")
    assert len(issues) == 4
    assert {issue.code for issue in issues} == {"public_section_structure"}


def test_structure_requires_fixed_order_and_substantive_content() -> None:
    body = """### 问题
内容足够长，用于提出当前章节需要回答的具体问题和判断期限。

### 研究与分析
内容足够长，用于说明证据如何传导到当前研究判断和反方情景。

### 研究方法与数据
内容足够长，用于说明数据来源、估算方法、口径和必要限制。

### 总结
短。
"""
    issues = _structured_public_body_issues(body, "section")
    assert len(issues) == 1
    assert issues[0].code == "public_section_structure"


def test_current_c_track_character_floors_are_800_and_1200() -> None:
    profile = resolve_track_config("c")
    assert profile["fallback_minimum_characters"] == {
        "report_section": 800,
        "entity_section": 1200,
    }
    assert profile["deep_research_minimum_characters"] == {
        "report_section": 800,
        "entity_section": 1200,
    }


def test_homepage_character_count_ignores_markdown_routes_and_syntax() -> None:
    body = "### 总结\n\n**优先[合合信息](/company/669)，谨慎高估值公司。**"
    assert public_markdown_character_count(body) == len(
        "总结优先合合信息谨慎高估值公司"
    )
