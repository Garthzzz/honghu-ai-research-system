from __future__ import annotations

"""Build the live SQLite watermark and the first-unit writer-fence evidence.

The module never writes SQLite.  Windows process, listener and Scheduled Task
observations are collected by the paired PowerShell orchestrator and are
validated here before the evidence can satisfy the S2 controller.
"""

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.migration.stage4_json_io import read_json
from tools.release.manager import verify_release


class WriterFenceError(RuntimeError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _parse_audit_timestamp(value: str) -> datetime:
    """Parse RFC 3339 timestamps emitted by Python or PowerShell.

    Windows PowerShell's round-trip ``o`` formatter emits seven fractional
    second digits (100 ns ticks), while Python 3.10 accepts at most six.  The
    seventh digit is below Python's datetime precision, so truncate only that
    fractional tail and keep the timezone/offset fail-closed.
    """

    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    normalized = re.sub(r"(?<=\.\d{6})\d+(?=[+-]\d{2}:\d{2}$)", "", normalized)
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError("audit timestamp must include a timezone")
    return parsed


def capture_sqlite_watermark(database: Path) -> dict[str, Any]:
    database = database.resolve()
    if not database.is_file():
        raise WriterFenceError("research.db is missing")
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        columns = [
            str(row[1])
            for row in connection.execute("PRAGMA table_info(analyst_note)").fetchall()
        ]
        if not {"id", "entity_type", "entity_id", "content"}.issubset(columns):
            raise WriterFenceError("analyst_note schema is not the approved legacy contract")
        selected = [
            name
            for name in (
                "id",
                "entity_type",
                "entity_id",
                "q_number",
                "note_type",
                "title",
                "content",
                "author",
                "created_at",
                "updated_at",
            )
            if name in columns
        ]
        rows = connection.execute(
            f"SELECT {','.join(selected)} FROM analyst_note ORDER BY id"
        ).fetchall()
        schema_version = int(connection.execute("PRAGMA schema_version").fetchone()[0])
        user_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        integrity = str(connection.execute("PRAGMA quick_check").fetchone()[0])
        if integrity.lower() != "ok":
            raise WriterFenceError("research.db quick_check failed")
        row_payload = [dict(zip(selected, row)) for row in rows]
        core = {
            "database": "research.db",
            "table": "analyst_note",
            "transaction_contract": "one_explicit_query_only_transaction",
            "query_only": True,
            "schema_version": schema_version,
            "user_version": user_version,
            "columns": selected,
            "analyst_note_count": len(row_payload),
            "max_id": max((int(row["id"]) for row in row_payload), default=None),
            "rows_sha256": _sha(row_payload),
            "quick_check": "ok",
        }
        return {**core, "watermark_sha256": _sha(core)}
    finally:
        connection.rollback()
        connection.close()


def compile_writer_fence(
    *,
    before: dict[str, Any],
    after: dict[str, Any],
    windows_observation: dict[str, Any],
    application_commit_sha: str,
    release_manifest_sha256: str,
) -> dict[str, Any]:
    if len(application_commit_sha) != 40 or any(
        character not in "0123456789abcdef" for character in application_commit_sha
    ):
        raise WriterFenceError("release application commit is invalid")
    if len(release_manifest_sha256) != 64:
        raise WriterFenceError("release manifest identity is invalid")
    if before != after:
        raise WriterFenceError("SQLite analyst_note watermark changed during writer fencing")
    if windows_observation.get("schema_version") != "honghu.user_content_windows_fence.v1":
        raise WriterFenceError("unsupported Windows fence observation")
    required_true = (
        "preflight_query_succeeded",
        "legacy_health_was_reachable",
        "legacy_listener_identity_verified",
        "legacy_listener_stopped",
        "legacy_service_fence_verified",
        "post_stop_listener_absent",
        "post_stop_health_unreachable",
        "scheduled_task_query_succeeded",
        "process_query_succeeded",
    )
    missing = [name for name in required_true if windows_observation.get(name) is not True]
    if missing:
        raise WriterFenceError("Windows writer-fence observation failed: " + ", ".join(missing))
    if windows_observation.get("scheduled_writer_matches"):
        raise WriterFenceError("a scheduled analyst-note writer remains enabled")
    if windows_observation.get("writer_process_matches"):
        raise WriterFenceError("an analyst-note SQLite writer process remains active")
    stopped_pids = windows_observation.get("stopped_listener_pids")
    if not isinstance(stopped_pids, list) or not stopped_pids:
        raise WriterFenceError("legacy Viewer stop has no verified listener identity")
    captured_at = str(windows_observation.get("captured_at_utc") or "")
    if not captured_at:
        raise WriterFenceError("Windows fence observation has no capture time")
    # Parseability is part of the audit contract; this does not impose an
    # arbitrary age limit on a short, operator-controlled maintenance window.
    _parse_audit_timestamp(captured_at)
    observation_core = {
        key: value
        for key, value in windows_observation.items()
        if key != "observation_sha256"
    }
    observed_sha = windows_observation.get("observation_sha256")
    if observed_sha != _sha(observation_core):
        raise WriterFenceError("Windows fence observation identity mismatch")
    core = {
        "schema_version": "honghu.user_content_writer_fence.v1",
        "verified": True,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "sqlite_writer_fenced": True,
        "old_listener_absent": True,
        "scheduled_writer_absent": True,
        "production_8080_stopped_for_cutover": True,
        "sqlite_final_watermark": after,
        "application_commit_sha": application_commit_sha,
        "release_manifest_sha256": release_manifest_sha256,
        "watermark_stable_across_fence": True,
        "windows_observation_sha256": observed_sha,
        "stopped_listener_pids": [int(item) for item in stopped_pids],
        "stopped_service_identities": windows_observation.get(
            "stopped_service_identities", []
        ),
        "scheduled_writer_matches": [],
        "writer_process_matches": [],
    }
    return {**core, "evidence_sha256": _sha(core)}


def _object(path: Path) -> dict[str, Any]:
    value = read_json(path)
    if not isinstance(value, dict):
        raise WriterFenceError(f"JSON object required: {path}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    capture = subparsers.add_parser("capture")
    capture.add_argument("--database", type=Path, required=True)
    capture.add_argument("--output", type=Path, required=True)
    seal = subparsers.add_parser("seal-windows")
    seal.add_argument("--input", type=Path, required=True)
    seal.add_argument("--output", type=Path, required=True)
    compile_parser = subparsers.add_parser("compile")
    compile_parser.add_argument("--before", type=Path, required=True)
    compile_parser.add_argument("--after", type=Path, required=True)
    compile_parser.add_argument("--windows-observation", type=Path, required=True)
    compile_parser.add_argument("--release-dir", type=Path, required=True)
    compile_parser.add_argument("--expected-commit", required=True)
    compile_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "capture":
        result = capture_sqlite_watermark(args.database)
    elif args.action == "seal-windows":
        core = _object(args.input)
        if "observation_sha256" in core:
            raise WriterFenceError("unsealed Windows observation must not carry an identity")
        result = {**core, "observation_sha256": _sha(core)}
    else:
        release = verify_release(args.release_dir)
        if release.get("commit_sha") != args.expected_commit:
            raise WriterFenceError("writer fence release is not the approved commit")
        result = compile_writer_fence(
            before=_object(args.before),
            after=_object(args.after),
            windows_observation=_object(args.windows_observation),
            application_commit_sha=str(release["commit_sha"]),
            release_manifest_sha256=str(release["manifest_sha256"]),
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
