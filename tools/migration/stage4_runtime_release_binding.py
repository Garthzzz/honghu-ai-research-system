from __future__ import annotations

"""Bind verified PostgreSQL infrastructure metadata to one exact app release.

The original bootstrap runtime remains an immutable infrastructure fact.  A
release-bound derivative carries the currently approved application commit to
recovery, S1 and Viewer configuration without pretending PostgreSQL was
reinstalled for every application release.
"""

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.migration.stage4_json_io import read_json


class RuntimeBindingError(RuntimeError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def bind_runtime(source: dict[str, Any], *, commit_sha: str) -> dict[str, Any]:
    if source.get("schema_version") != "honghu.postgresql_production_runtime.v1":
        raise RuntimeBindingError("unsupported production runtime")
    if source.get("environment_id") != "production":
        raise RuntimeBindingError("runtime is not production scoped")
    if source.get("application_route") != "sqlite_transition":
        raise RuntimeBindingError("infrastructure runtime authority is not the frozen SQLite baseline")
    if source.get("sslmode") != "verify-full":
        raise RuntimeBindingError("production runtime does not enforce verify-full")
    if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
        raise RuntimeBindingError("application release must be a lowercase full SHA")
    source_identity = _sha(source)
    core = {
        **source,
        "application_commit_sha": commit_sha,
        "runtime_binding": {
            "schema_version": "honghu.postgresql_runtime_release_binding.v1",
            "source_runtime_identity_sha256": source_identity,
            "source_application_commit_sha": source.get("application_commit_sha"),
            "bound_application_commit_sha": commit_sha,
            "infrastructure_reinstalled": False,
            "authority_changed": False,
        },
    }
    binding_core = {
        "source_runtime_identity_sha256": source_identity,
        "application_commit_sha": commit_sha,
        "environment_id": source["environment_id"],
        "service_name": source.get("service_name"),
        "host": source.get("host"),
        "port": source.get("port"),
        "dbname": source.get("dbname"),
    }
    return {
        **core,
        "runtime_binding_identity_sha256": _sha(binding_core),
        "runtime_bound_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--application-commit-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    source = read_json(args.source)
    if not isinstance(source, dict):
        raise RuntimeBindingError("runtime must be a JSON object")
    result = bind_runtime(source, commit_sha=args.application_commit_sha)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "application_commit_sha": result["application_commit_sha"],
                "runtime_binding_identity_sha256": result[
                    "runtime_binding_identity_sha256"
                ],
                "authority_changed": False,
                "secret_recorded": False,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
