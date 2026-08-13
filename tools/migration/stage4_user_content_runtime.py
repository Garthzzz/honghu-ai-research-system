from __future__ import annotations

"""Compile the production bootstrap identity into Viewer runtime configuration.

The compiler never reads credentials.  It carries only Credential Manager
identities and the exact TLS root path into the application-facing v2 contract.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from tools.migration.stage4_json_io import read_json


class UserContentRuntimeError(RuntimeError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def compile_viewer_runtime(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != "honghu.postgresql_production_runtime.v1":
        raise UserContentRuntimeError("unsupported production bootstrap runtime")
    if payload.get("environment_id") != "production":
        raise UserContentRuntimeError("bootstrap runtime is not production-scoped")
    if payload.get("application_route") != "sqlite_transition":
        raise UserContentRuntimeError("bootstrap authority is no longer the approved SQLite baseline")
    if payload.get("sslmode") != "verify-full":
        raise UserContentRuntimeError("Viewer runtime requires verify-full TLS")
    root = Path(str(payload.get("sslrootcert") or "")).resolve()
    if not root.is_file():
        raise UserContentRuntimeError("production TLS root certificate is missing")
    roles = payload.get("roles") or {}

    def role(name: str) -> dict[str, str]:
        value = roles.get(name)
        if not isinstance(value, dict):
            raise UserContentRuntimeError(f"production role is missing: {name}")
        result = {
            "user": str(value.get("user") or ""),
            "credential_service": str(value.get("credential_service") or ""),
            "credential_account": str(value.get("credential_account") or ""),
        }
        if not all(result.values()):
            raise UserContentRuntimeError(f"production role identity is incomplete: {name}")
        return result

    reader = role("reader")
    writer = role("writer")
    if reader["user"] == writer["user"]:
        raise UserContentRuntimeError("reader and writer roles must remain distinct")
    core = {
        "schema_version": "honghu.postgresql_runtime.v2",
        "enabled": True,
        "environment_id": "production",
        "host": str(payload.get("host") or ""),
        "port": int(payload.get("port") or 0),
        "dbname": str(payload.get("dbname") or ""),
        "sslmode": "verify-full",
        "sslrootcert": str(root),
        "connect_timeout_seconds": 5,
        "reader": reader,
        "writer": writer,
        "source_runtime_identity_sha256": _sha(payload),
    }
    if not core["host"] or not 1 <= core["port"] <= 65535 or not core["dbname"]:
        raise UserContentRuntimeError("production connection identity is incomplete")
    return {**core, "runtime_identity_sha256": _sha(core)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    source = read_json(args.source)
    if not isinstance(source, dict):
        raise UserContentRuntimeError("production runtime must be an object")
    result = compile_viewer_runtime(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "runtime_identity_sha256": result["runtime_identity_sha256"],
        "source_runtime_identity_sha256": result["source_runtime_identity_sha256"],
        "secret_recorded": False,
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
