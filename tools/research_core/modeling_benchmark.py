from __future__ import annotations

"""Deterministic benchmark for progressive modeling-Skill loading.

This measures the local control plane only.  It deliberately does not claim to
measure LLM inference, web search, PDF extraction, or a historical production
run that was not instrumented at the time.
"""

import argparse
import json
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any

from .brief import compile_research_brief
from .model_routing import route_modeling_skills


ROOT = Path(__file__).resolve().parents[2]


CASES: tuple[dict[str, Any], ...] = (
    {
        "case": "普通盈利公司未来利润",
        "track": "c",
        "title": "公司未来利润",
        "question": "预测某上市公司未来三年收入、利润、EPS、ROE和ROA",
    },
    {
        "case": "普通公司估值",
        "track": "c",
        "title": "公司估值",
        "question": "判断某上市公司合理价值、高估或低估，并解释市场隐含预期",
    },
    {
        "case": "外部竞争冲击",
        "track": "c",
        "title": "新竞争者进入与供需冲击",
        "question": "判断新竞争者进入概率、可争夺市场空间，并量化对公司利润和估值的影响",
    },
    {
        "case": "强周期资源公司",
        "track": "b",
        "title": "周期股正常化利润与估值",
        "question": "分析某上市资源公司的正常化利润、PB-ROE、PB-ROA和合理估值",
        "requirements": ["识别商品周期顶部和底部，不能直接套用当前PE"],
    },
    {
        "case": "银行估值",
        "track": "c",
        "title": "银行资产回报与估值",
        "question": "预测上市银行未来利润、ROE和ROA，并进行PB-ROE估值",
    },
    {
        "case": "亏损公司",
        "track": "c",
        "title": "亏损公司估值",
        "question": "对亏损上市公司使用PS和反向估值判断合理价值",
    },
    {
        "case": "纯行业市场空间",
        "track": "a",
        "title": "行业市场空间与供需",
        "question": "测算高端设备市场规模、有效供给和未来供需缺口",
    },
    {
        "case": "单纯证据核验",
        "track": "c",
        "title": "新闻、专利与招聘核验",
        "question": "只核验某公司的新闻、专利和招聘事实，不做财务预测或估值",
    },
)


def _skill_bytes() -> dict[str, int]:
    routes = route_modeling_skills(
        track="c",
        title="公司估值与行业供需事件冲击",
        research_question="预测公司利润和估值，分析市场空间、供需与竞争者进入概率",
    )
    result: dict[str, int] = {}
    for route in routes:
        path = ROOT / route.skill_path
        result[route.skill_name] = len(path.read_bytes())
    return result


def benchmark(*, iterations: int = 100) -> dict[str, Any]:
    if iterations < 1:
        raise ValueError("iterations 必须大于 0")
    sizes = _skill_bytes()
    eager_bytes = sum(sizes.values())
    rows: list[dict[str, Any]] = []
    for case in CASES:
        requirements = list(case.get("requirements") or [])
        elapsed: list[float] = []
        brief = None
        for _ in range(iterations):
            started = perf_counter()
            brief = compile_research_brief(
                track=case["track"],
                title=case["title"],
                research_question=case["question"],
                prompt_requirements=requirements,
            )
            elapsed.append((perf_counter() - started) * 1000)
        assert brief is not None
        selected = [item["skill_name"] for item in brief.modeling_routes]
        routed_bytes = sum(sizes[name] for name in selected)
        tasks = list(brief.search_plan.get("tasks") or [])
        rows.append({
            "case": case["case"],
            "selected_skills": selected,
            "selected_skill_count": len(selected),
            "eager_skill_count_proxy": len(sizes),
            "routed_skill_context_bytes": routed_bytes,
            "eager_all_skill_context_bytes_proxy": eager_bytes,
            "context_reduction_pct": round((1 - routed_bytes / eager_bytes) * 100, 2) if eager_bytes else 0.0,
            "compile_mean_ms": round(mean(elapsed), 4),
            "search_task_count": len(tasks),
            "report_search_task_count": sum(item.get("source_channel") == "report" for item in tasks),
            "web_search_task_count": sum(item.get("source_channel") == "web" for item in tasks),
            "second_round_search_task_count": sum(bool(item.get("gap_trigger")) for item in tasks),
        })
    return {
        "benchmark_contract": "research.modeling_routing.benchmark.v1",
        "measurement_scope": "本地确定性路由、ResearchBrief编译和四个SKILL.md正文载入量",
        "excluded_from_measurement": ["模型推理", "网络检索", "PDF解析", "正文生成", "业务数据库写入"],
        "baseline_disclosure": "eager_* 是假设旧流程每次加载四个建模Skill正文的对照代理，不是补造的历史生产实测。",
        "agent_call_disclosure": "selected_skill_count只是所需模型producer调用数量的保守代理；独立reviewer未删除，也未计入降幅。",
        "iterations_per_case": iterations,
        "skill_file_bytes": sizes,
        "cases": rows,
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# 建模 Skill 按需加载性能审计",
        "",
        result["baseline_disclosure"],
        "",
        result["agent_call_disclosure"],
        "",
        "| 任务 | 实际加载 Skill | Skill 数 | 上下文 bytes | 全量代理 bytes | 减少 | 编译均值 ms | 研报/网络任务 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["cases"]:
        lines.append(
            "| {case} | {skills} | {count} | {routed} | {eager} | {reduction:.2f}% | {latency:.4f} | {report}/{web} |".format(
                case=row["case"],
                skills="、".join(row["selected_skills"]) or "不加载建模 Skill",
                count=row["selected_skill_count"],
                routed=row["routed_skill_context_bytes"],
                eager=row["eager_all_skill_context_bytes_proxy"],
                reduction=row["context_reduction_pct"],
                latency=row["compile_mean_ms"],
                report=row["report_search_task_count"],
                web=row["web_search_task_count"],
            )
        )
    lines.extend([
        "",
        "## 边界",
        "",
        "该结果证明控制层已经按问题只路由必要 Skill，并且研报与网络任务独立生成。真实研究总耗时还取决于模型、搜索、PDF和复核，不能用本微基准替代端到端计时。",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="建模Skill按需加载与搜索渠道隔离微基准")
    parser.add_argument("--iterations", type=int, default=100)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    args = parser.parse_args()
    result = benchmark(iterations=args.iterations)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
