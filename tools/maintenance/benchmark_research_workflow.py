from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from uuid import uuid4

from tools.research_core.brief import compile_research_brief
from tools.research_core.config import clear_workflow_config_cache, load_workflow_config, resolve_track_config
from tools.research_core.content_cache import ContentAddressedCache
from tools.research_core.workflow import ResearchWorkflowRun


def _mean_ms(callable_, iterations: int) -> float:
    started = perf_counter()
    for _ in range(iterations):
        callable_()
    return (perf_counter() - started) * 1000 / iterations


def benchmark(iterations: int = 200) -> dict:
    requirements = [f"benchmark-question-{index}" for index in range(30)]
    clear_workflow_config_cache()
    started = perf_counter()
    load_workflow_config()
    config_cold_ms = (perf_counter() - started) * 1000
    result = {
        "scope": "research_workflow_control_plane_only",
        "excludes": ["network_search", "pdf_extraction", "model_inference", "report_writing", "database_ingest"],
        "iterations": iterations,
        "config_cold_ms": config_cold_ms,
        "config_cached_ms": _mean_ms(load_workflow_config, iterations),
        "resolve_track_b_ms": _mean_ms(lambda: resolve_track_config("b"), iterations),
        "brief_compile_30_requirements_ms": _mean_ms(
            lambda: compile_research_brief(
                track="b",
                title="benchmark",
                research_question="benchmark",
                prompt_requirements=requirements,
            ),
            iterations,
        ),
    }
    blob = b"0123456789abcdef" * 65536
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        cache = ContentAddressedCache(root / "cache")
        started = perf_counter()
        cache.put_bytes(blob, suffix=".txt", metadata={"url": "https://example.com/benchmark"})
        result["cache_1mib_cold_ms"] = (perf_counter() - started) * 1000
        result["cache_1mib_hit_ms"] = _mean_ms(
            lambda: cache.put_bytes(blob, suffix=".txt", metadata={"url": "https://example.com/benchmark"}),
            min(iterations, 50),
        )
        result["workflow_start_ms"] = _mean_ms(
            lambda: ResearchWorkflowRun.start(
                run_dir=root / "runs" / uuid4().hex,
                run_key=uuid4().hex,
                track="b",
                title="benchmark",
                research_question="benchmark",
                prompt_requirements=requirements,
            ),
            min(iterations, 50),
        )
    return {
        key: round(value, 4) if isinstance(value, float) else value
        for key, value in result.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="研究工作流控制层微基准；不包含检索、模型、PDF 或业务 DB")
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.iterations < 1:
        raise ValueError("iterations 必须大于 0")
    result = benchmark(args.iterations)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
