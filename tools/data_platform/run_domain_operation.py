from __future__ import annotations

"""Run one audited domain mutation with a stable operation identity.

This is the temporary Stage 4 runner boundary.  It does not move a Windows
Scheduled Task or change data authority.  It supplies the identity required by
the PostgreSQL compatibility adapter and holds one process lock per cutover
unit, preventing an accidental second writer instance during the mixed window.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


PRODUCTION_UNITS = {
    "financial_data",
    "research_publication",
    "dynamic_intelligence",
    "operations_governance",
    "investment_hypotheses",
    "opportunity_lens",
    "sentiment_analytics",
}


def install_operation_context(
    *, cutover_unit: str, operation_scope: str, logical_window: str
) -> str:
    """Install one retry-stable identity for an existing production runner.

    The runner host and Scheduled Task definition do not change during Stage 4.
    The identity is derived from the audited business window rather than a
    random process id, so a crash/retry of the same logical run reuses it.  An
    explicitly supplied identity wins, allowing the controlled wrapper to bind
    a stronger upstream checkpoint when available.
    """

    if cutover_unit not in PRODUCTION_UNITS:
        raise ValueError(f"unknown production cutover unit: {cutover_unit}")
    scope = operation_scope.strip()
    window = logical_window.strip()
    if not scope or not window or any(value in window for value in ("\r", "\n")):
        raise ValueError("operation scope and logical window are required")
    generated = f"{cutover_unit}:{scope}:{window}"
    existing = os.environ.get("HONGHU_OPERATION_ID", "").strip()
    if existing:
        return existing
    os.environ["HONGHU_OPERATION_ID"] = generated
    return generated


def derived_operation_id(step: str) -> str:
    """Return a retry-stable identity for one child/connection stream."""

    value = step.strip()
    if not value or any(char in value for char in "\r\n"):
        raise ValueError("operation step is required")
    root = os.environ.get("HONGHU_OPERATION_ID", "").strip()
    if not root:
        raise RuntimeError("root operation identity is unavailable")
    return f"{root}:step:{value}"


def derived_operation_environment(step: str) -> dict[str, str]:
    """Return an environment with a retry-stable child/step identity.

    A fresh compatibility connection starts its transaction counter at one.
    Parent and child processes must therefore not reuse the same operation id
    for independent mutation streams.
    """

    environment = dict(os.environ)
    environment["HONGHU_OPERATION_ID"] = derived_operation_id(step)
    return environment


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def trusted_os_principal() -> str:
    """Resolve the operating-system principal without trusting caller text."""

    if os.name == "nt":
        system_root = Path(os.environ.get("SystemRoot") or r"C:\Windows").resolve()
        executable = system_root / "System32" / "whoami.exe"
        if not executable.is_file():
            raise RuntimeError("trusted Windows principal resolver is unavailable")
        value = subprocess.run(
            [str(executable)], capture_output=True, text=True, check=True
        ).stdout.strip()
    else:
        value = f"uid:{os.geteuid()}"
    if not value:
        raise RuntimeError("trusted operating-system principal is empty")
    return "principal:os:" + value


@contextmanager
def _unit_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError(f"cutover-unit runner is already active: {path.stem}") from exc
        yield
    finally:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        handle.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--unit", required=True, choices=sorted(PRODUCTION_UNITS))
    parser.add_argument("--operation-id", required=True)
    parser.add_argument("--runtime-dir", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    operation_id = args.operation_id.strip()
    actor = trusted_os_principal()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not operation_id or not command:
        parser.error("stable operation identity and command are required")
    runtime = args.runtime_dir.resolve()
    evidence_dir = runtime / "domain_operations"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    operation_hash = hashlib.sha256(operation_id.encode("utf-8")).hexdigest()
    evidence_path = evidence_dir / f"{args.unit}-{operation_hash}.json"
    if evidence_path.exists():
        prior = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
        if prior.get("operation_id_sha256") != operation_hash:
            raise RuntimeError("operation evidence identity collision")
    environment = dict(os.environ)
    environment["HONGHU_OPERATION_ID"] = operation_id
    environment["HONGHU_AUDIT_ACTOR"] = actor
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    started = _utc_now()
    with _unit_lock(runtime / "locks" / f"{args.unit}.writer.lock"):
        completed = subprocess.run(command, env=environment, check=False)
    result = {
        "schema_version": "honghu.domain_operation_runner.v1",
        "cutover_unit": args.unit,
        "operation_id_sha256": operation_hash,
        "actor": actor,
        "command_sha256": hashlib.sha256(
            json.dumps(command, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "started_at_utc": started,
        "finished_at_utc": _utc_now(),
        "returncode": completed.returncode,
    }
    evidence_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
