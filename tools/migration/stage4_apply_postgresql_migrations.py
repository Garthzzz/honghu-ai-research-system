from __future__ import annotations

"""Apply an exact reviewed PostgreSQL migration set with the break-glass role.

The command is migration-only: it neither changes application routes nor
authority state.  Secret material is read from Windows Credential Manager and
is never accepted through argv, environment variables, logs, or evidence.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from tools.migration.stage4_json_io import read_json


class MigrationApplyError(RuntimeError):
    pass


REVIEWED_MIGRATIONS = (
    "0005_shared_identity_expand.sql",
    "0006_shared_identity_cutover_expand.sql",
    "0007_shared_identity_mutation_expand.sql",
    "0008_financial_data_expand.sql",
    "0009_stage4_s1_authority_read_grant.sql",
    "0010_remaining_units_common_data_plane.sql",
    "0011_sentiment_persistent_projection.sql",
)

MIGRATION_IDENTIFIERS = {
    "0005_shared_identity_expand.sql": {
        "migration_role": "honghu_migration",
        "reader_role": "honghu_viewer_reader",
    },
    "0008_financial_data_expand.sql": {
        "migration_role": "honghu_migration",
        "reader_role": "honghu_viewer_reader",
    },
    "0009_stage4_s1_authority_read_grant.sql": {
        "migration_role": "honghu_migration",
    },
    "0010_remaining_units_common_data_plane.sql": {
        "reader_role": "honghu_viewer_reader",
        "controller_role": "honghu_controller",
        "audit_reader_role": "honghu_audit_reader",
        "writer_financial_data": "honghu_writer_financial_data",
        "writer_research_publication": "honghu_writer_research_publication",
        "writer_dynamic_intelligence": "honghu_writer_dynamic_intelligence",
        "writer_operations_governance": "honghu_writer_operations_governance",
        "writer_investment_hypotheses": "honghu_writer_investment_hypotheses",
        "writer_opportunity_lens": "honghu_writer_opportunity_lens",
        "writer_sentiment_analytics": "honghu_writer_sentiment_analytics",
    },
    "0011_sentiment_persistent_projection.sql": {
        "reader_role": "honghu_viewer_reader",
    },
}


def _sha_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render_schema_migration(
    text: str,
    migration_sha256: str,
    *,
    identifiers: dict[str, str] | None = None,
) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", migration_sha256):
        raise MigrationApplyError("invalid migration SHA256")
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("\\")]
    rendered = "\n".join(lines).replace(
        ":'migration_sha256'", "'" + migration_sha256 + "'"
    )
    if identifiers:
        rendered = render_role_grant(rendered, identifiers)
    if ":'migration_sha256'" in rendered or "\\set" in rendered:
        raise MigrationApplyError("unrendered psql migration variable remains")
    return rendered


def render_role_grant(text: str, identifiers: dict[str, str]) -> str:
    rendered = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("\\")
    )
    for variable, identifier in identifiers.items():
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", identifier):
            raise MigrationApplyError(f"unsafe role identifier: {variable}")
        rendered = rendered.replace(f':"{variable}"', f'"{identifier}"')
    if re.search(r':"[a-z_][a-z0-9_]*"', rendered):
        raise MigrationApplyError("unrendered role variable remains")
    return rendered


def _admin_connection(runtime_path: Path) -> Any:
    runtime = read_json(runtime_path)
    if (
        runtime.get("schema_version") != "honghu.postgresql_production_runtime.v1"
        or runtime.get("environment_id") != "production"
    ):
        raise MigrationApplyError("production runtime evidence is required")
    account = runtime.get("break_glass") or {}
    service = str(account.get("credential_service") or "")
    credential_account = str(account.get("credential_account") or "")
    username = str(account.get("user") or "")
    if not service or not credential_account or not username:
        raise MigrationApplyError("break-glass credential identity is incomplete")
    import keyring
    import psycopg

    password = keyring.get_password(service, credential_account)
    if not password:
        raise MigrationApplyError("break-glass credential is unavailable")
    return psycopg.connect(
        host=runtime["host"],
        port=int(runtime["port"]),
        dbname=runtime["dbname"],
        user=username,
        password=password,
        sslmode=runtime.get("sslmode") or "verify-full",
        sslrootcert=runtime.get("sslrootcert"),
        connect_timeout=5,
        autocommit=True,
    )


def apply_reviewed_migrations(
    connection: Any, *, repo_root: Path, names: tuple[str, ...]
) -> dict[str, Any]:
    if not names or any(name not in REVIEWED_MIGRATIONS for name in names):
        raise MigrationApplyError("migration set contains an unreviewed file")
    applied: list[dict[str, str]] = []
    for name in names:
        path = (repo_root / "migrations/postgresql" / name).resolve()
        if path.parent != (repo_root / "migrations/postgresql").resolve() or not path.is_file():
            raise MigrationApplyError(f"migration file is missing: {name}")
        migration_sha = _sha_file(path)
        migration_id = path.stem
        existing = connection.execute(
            "SELECT migration_sha256 FROM operations.schema_migration WHERE migration_id=%s",
            (migration_id,),
        ).fetchone()
        if existing is not None:
            if str(existing[0]) != migration_sha:
                raise MigrationApplyError(
                    f"migration ledger SHA mismatch: {migration_id}"
                )
            applied.append(
                {"migration_id": migration_id, "sha256": migration_sha, "status": "already_exact"}
            )
            continue
        identifiers = MIGRATION_IDENTIFIERS.get(name)
        connection.execute(
            render_schema_migration(
                path.read_text(encoding="utf-8"),
                migration_sha,
                identifiers=identifiers,
            )
        )
        recorded = connection.execute(
            "SELECT migration_sha256 FROM operations.schema_migration WHERE migration_id=%s",
            (migration_id,),
        ).fetchone()
        if recorded is None or str(recorded[0]) != migration_sha:
            raise MigrationApplyError(f"migration was not recorded exactly: {migration_id}")
        applied.append(
            {"migration_id": migration_id, "sha256": migration_sha, "status": "applied"}
        )

    for name, roles in (
        (
            "0006_shared_identity_role_grants.sql",
            {
                "writer_role": "honghu_writer_shared_identity",
                "reader_role": "honghu_viewer_reader",
                "controller_role": "honghu_controller",
                "audit_reader_role": "honghu_audit_reader",
            },
        ),
        (
            "0007_shared_identity_role_grants.sql",
            {
                "writer_role": "honghu_writer_shared_identity",
                "audit_reader_role": "honghu_audit_reader",
            },
        ),
    ):
        path = repo_root / "migrations/postgresql" / name
        connection.execute(render_role_grant(path.read_text(encoding="utf-8"), roles))
    core = {
        "schema_version": "honghu.stage4_postgresql_migration_apply.v1",
        "environment_id": "production",
        "migrations": applied,
        "shared_identity_role_grants_applied": True,
        "authority_transition_performed": False,
        "formal_business_mutation_performed": False,
        "secret_recorded": False,
    }
    core["evidence_sha256"] = hashlib.sha256(
        json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return core


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--migration", action="append", dest="migrations")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    names = tuple(args.migrations or REVIEWED_MIGRATIONS)
    connection = _admin_connection(args.runtime)
    try:
        result = apply_reviewed_migrations(
            connection, repo_root=args.repo_root.resolve(), names=names
        )
    finally:
        connection.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
