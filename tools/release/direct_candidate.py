from __future__ import annotations

"""Start the candidate in the listener-owning base interpreter.

On Windows, a venv ``python.exe`` can be a redirector process whose child owns
the socket. The release contract records and stops the listener itself, so the
deployer launches the verified base interpreter with ``-I -B -S`` and adds only
the already verified venv site-packages before entering an allowlisted release
module.  The same bootstrap is used by one-shot project commands so a caller's
``PYTHONPATH`` cannot choose the imported ``tools`` package and no bytecode is
written into an immutable release.
"""

import argparse
import importlib
import os
import sys
from pathlib import Path


ALLOWED_MODULES = {
    "tools.release.cli": "main",
    "tools.release.readonly_smoke": "main",
    "tools.release.user_content_production": "main",
    "tools.operations.task_runner": "main",
    "tools.operations.task_child": "main",
    "tools.operations.task_credential_transfer": "main",
    "tools.operations.task_service_preflight": "main",
    "tools.operations.task_enable_evidence": "main",
    "tools.operations.backup_credential_transfer": "main",
    "tools.operations.wal_offvm_sync": "main",
    "tools.operations.stage5_recovery_cycle": "main",
    "tools.operations.storage_identity_transition": "main",
    "tools.operations.recovery_health": "main",
    "tools.operations.stage5_health": "main",
    "tools.migration.stage4_apply_postgresql_migrations": "main",
    "tools.migration.stage4_runtime_release_binding": "main",
    "tools.pipeline.apply_fiber_company_production_delta": "main",
    "tools.financial.valuation_tracker_identity_seed": "main",
    "tools.financial.valuation_tracker_seed": "main",
    "tools.financial.valuation_tracker_production_setup": "main",
    "tools.financial.fiber_yfinance_valuation_history": "main",
}


_DLL_DIRECTORY_HANDLES: list[object] = []


def configure_utf8_stdio() -> None:
    """Make project JSON output independent of the inherited Windows code page.

    Isolated mode intentionally ignores ``PYTHONUTF8`` and
    ``PYTHONIOENCODING``.  The bootstrap must therefore set the streams before
    importing any project entrypoint.  Without this, a cp1252 runner cannot
    emit evidence containing Chinese text even though the evidence file itself
    is correctly written as UTF-8.
    """

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="strict")


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
    # pywin32 installs its extension modules below ``win32`` and helper
    # modules below ``win32/lib`` through a .pth file.  Isolated mode rightly
    # avoids processing arbitrary .pth code, so include only these reviewed
    # directories from the already hash-locked environment when present.
    locked_extensions = [
        candidate
        for candidate in (locked_site / "win32", locked_site / "win32" / "lib")
        if candidate.is_dir()
    ]
    # pywin32 extension modules import ``pywintypes`` from a sibling DLL
    # directory.  ``-I -S`` intentionally ignores the install-time .pth hook,
    # so register only this reviewed directory and retain its handle for the
    # process lifetime.  Merely adding ``win32`` to sys.path is insufficient
    # on current Windows DLL search semantics.
    dll_directory = locked_site / "pywin32_system32"
    if os.name == "nt" and dll_directory.is_dir():
        _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(dll_directory)))
    sys.path[:] = [
        str(release_root),
        str(locked_site),
        *(str(path) for path in locked_extensions),
        *retained,
    ]
    return release_root, locked_site


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-packages", required=True)
    parser.add_argument("--module", choices=sorted(ALLOWED_MODULES), required=True)
    args, remainder = parser.parse_known_args(argv)
    # Keep arguments for the allowlisted child module behind an explicit
    # option boundary.  Without this, argparse also consumes child options
    # that share a name with this bootstrap (notably --site-packages), and a
    # Scheduled Task reaches the child parser with a required option missing.
    if remainder[:1] == ["--"]:
        remainder = remainder[1:]
    prepare_import_path(args.site_packages)
    if not remainder:
        raise RuntimeError("candidate CLI command is missing")
    module = importlib.import_module(args.module)
    entrypoint = getattr(module, ALLOWED_MODULES[args.module])
    return int(entrypoint(remainder))


if __name__ == "__main__":
    raise SystemExit(main())
