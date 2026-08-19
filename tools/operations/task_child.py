from __future__ import annotations

"""Run one reviewed production-task module inside the exact release process."""

import argparse
import runpy
import sys

from tools.operations.windows_job import ensure_self_killing_job


ALLOWED_TASK_MODULES = {
    "tools.dynamic.scheduler",
    "tools.sentiment.event_ingest",
    "tools.sentiment.recruit_weekly",
    "tools.sentiment.retail_window_tick",
    "tools.maintenance.sentiment_retention",
    "tools.sentiment.recruit_scrape",
    "tools.sentiment.recruit_classify",
    "tools.sentiment.senti_fetch_guba",
    "tools.sentiment.senti_fetch_xinghan",
    "tools.sentiment.senti_score",
    "tools.sentiment.stock_kline_fetch",
    "tools.dynamic.event_sources.conference_loader",
    "tools.dynamic.event_sources.earnings_fetcher",
    "tools.dynamic.voice_ingest",
    "tools.dynamic.news_ingest",
    "tools.financial.valuation_market_refresh",
    "tools.financial.valuation_ai_refresh",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-module", choices=sorted(ALLOWED_TASK_MODULES), required=True)
    args, remainder = parser.parse_known_args(argv)
    if remainder[:1] == ["--"]:
        remainder = remainder[1:]
    # Enrol before importing the producer.  All producer descendants then
    # share one OS-enforced lifetime even if the task root is killed.
    ensure_self_killing_job()
    sys.argv = [args.task_module, *remainder]
    try:
        runpy.run_module(args.task_module, run_name="__main__", alter_sys=False)
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
