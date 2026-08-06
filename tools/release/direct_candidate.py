from __future__ import annotations

"""Start the candidate in the listener-owning base interpreter.

On Windows, a venv ``python.exe`` can be a redirector process whose child owns
the socket. The release contract records and stops the listener itself, so the
deployer launches the verified base interpreter with ``-S`` and adds only the
already verified venv site-packages before entering the release CLI.
"""

import argparse
import sys
from pathlib import Path


def prepare_import_path(site_packages: str | Path) -> tuple[Path, Path]:
    locked_site = Path(site_packages).resolve()
    if not locked_site.is_dir():
        raise RuntimeError(f"locked site-packages directory is missing: {locked_site}")
    release_root = Path(__file__).resolve().parents[2]
    retained = []
    for item in sys.path:
        if not item:
            continue
        resolved = Path(item).resolve()
        if "site-packages" in {part.casefold() for part in resolved.parts}:
            continue
        if resolved not in {release_root, locked_site}:
            retained.append(item)
    sys.path[:] = [str(release_root), str(locked_site), *retained]
    return release_root, locked_site


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-packages", required=True)
    parser.add_argument("--module", choices=["tools.release.cli"], required=True)
    args, remainder = parser.parse_known_args(argv)
    prepare_import_path(args.site_packages)
    if not remainder:
        raise RuntimeError("candidate CLI command is missing")
    from tools.release.cli import main as release_cli_main

    return int(release_cli_main(remainder))


if __name__ == "__main__":
    raise SystemExit(main())
