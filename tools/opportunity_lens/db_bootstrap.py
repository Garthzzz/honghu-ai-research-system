from __future__ import annotations

import argparse

from .constants import DB_PATH
from .migrate import init_db


def bootstrap(reset: bool = False, seed_fixture: bool = False) -> None:
    init_db(DB_PATH, reset=reset)
    if seed_fixture:
        from .fixture_loader import load_synthetic_fixture

        load_synthetic_fixture(DB_PATH, reset=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--seed-fixture", action="store_true")
    args = parser.parse_args()
    bootstrap(reset=args.reset, seed_fixture=args.seed_fixture)
    print(f"机会透镜 bootstrap 已完成：{DB_PATH}")


if __name__ == "__main__":
    main()
