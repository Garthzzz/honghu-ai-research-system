from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.migration.stage4_s1_loader import _connection_from_runtime
from tools.migration.stage4_json_io import read_json


class ProductionVerificationError(RuntimeError):
    pass


EXPECTED_ROLES = {
    "migration",
    "reader",
    "controller",
    "audit_reader",
    "backup",
    "writer_user_content_notes",
    "writer_shared_identity",
    "writer_financial_data",
    "writer_research_publication",
    "writer_dynamic_intelligence",
    "writer_operations_governance",
    "writer_investment_hypotheses",
    "writer_opportunity_lens",
    "writer_sentiment_analytics",
}


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()


def verify_production_candidate(
    *, repo_root: Path, runtime_path: Path, application_commit_sha: str
) -> dict[str, Any]:
    runtime = read_json(runtime_path)
    if runtime.get("schema_version") != "honghu.postgresql_production_runtime.v1":
        raise ProductionVerificationError("unsupported production runtime schema")
    if runtime.get("environment_id") != "production":
        raise ProductionVerificationError("runtime is not production-scoped")
    if runtime.get("application_commit_sha") != application_commit_sha:
        raise ProductionVerificationError("runtime belongs to another application commit")
    if runtime.get("application_route") != "sqlite_transition":
        raise ProductionVerificationError("application route is not SQLite")
    route_path = repo_root / "config/migration/user_content_backend_route.json"
    route = read_json(route_path)
    if not (
        route.get("authority_state") in {"S0", "S1"}
        and route.get("backend") == "sqlite_transition"
        and route.get("sqlite_writer_enabled") is True
        and route.get("production_postgresql_enabled") is False
    ):
        raise ProductionVerificationError("tracked authority route exceeds S0/S1")
    roles = runtime.get("roles") or {}
    missing_roles = sorted(EXPECTED_ROLES - set(roles))
    if missing_roles:
        raise ProductionVerificationError(f"runtime roles missing: {missing_roles}")

    credential_presence: dict[str, bool] = {}
    import keyring

    for name, record in roles.items():
        credential_presence[name] = bool(
            keyring.get_password(
                str(record.get("credential_service") or ""),
                str(record.get("credential_account") or ""),
            )
        )
    if not all(credential_presence.values()):
        raise ProductionVerificationError("one or more production role credentials are unavailable")

    connection = _connection_from_runtime(runtime_path, "migration")
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT current_setting('server_version'), current_database(),
                       current_setting('listen_addresses'),
                       current_setting('port'),
                       current_setting('ssl'),
                       current_setting('archive_mode'),
                       current_setting('archive_command')
                """
            )
            server = cursor.fetchone()
            cursor.execute(
                """
                SELECT current_setting('server_encoding'),
                       current_setting('default_text_search_config'),
                       current_setting('data_checksums')
                """
            )
            cluster_settings = cursor.fetchone()
            cursor.execute(
                """
                SELECT pg_encoding_to_char(encoding),datlocprovider,datlocale
                  FROM pg_database WHERE datname=current_database()
                """
            )
            database_locale = cursor.fetchone()
            cursor.execute(
                "SELECT ssl,version,cipher FROM pg_stat_ssl WHERE pid=pg_backend_pid()"
            )
            tls = cursor.fetchone()
            cursor.execute(
                """
                SELECT migration_id,migration_sha256,phase,forward_only
                  FROM operations.schema_migration ORDER BY migration_id
                """
            )
            migrations = [list(row) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT cutover_unit,state,authoritative_backend,writer_identity,
                       cutover_epoch,postgresql_first_formal_commit
                  FROM operations.cutover_unit_authority ORDER BY cutover_unit
                """
            )
            authority = [list(row) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT cutover_unit,lifecycle_state,count(*)
                  FROM migration.unit_snapshot
                 GROUP BY cutover_unit,lifecycle_state ORDER BY cutover_unit,lifecycle_state
                """
            )
            unit_snapshots = [list(row) for row in cursor.fetchall()]
            cursor.execute(
                """
                SELECT count(*) FROM operations.idempotency_record
                 WHERE operation_scope IN (
                   'user_content.put_analyst_note_v2',
                   'user_content.soft_delete_analyst_note_v2'
                 )
                """
            )
            formal_idempotency_records = int(cursor.fetchone()[0])
            cursor.execute(
                """
                SELECT r.rolname,r.rolsuper,r.rolcreaterole,r.rolcreatedb,
                       r.rolreplication,r.rolcanlogin
                  FROM pg_roles r
                 WHERE r.rolname LIKE 'honghu_%' ORDER BY r.rolname
                """
            )
            role_attributes = [list(row) for row in cursor.fetchall()]
    finally:
        connection.close()

    if not str(server[0]).startswith("17.10"):
        raise ProductionVerificationError("production candidate is not PostgreSQL 17.10")
    if server[1] != runtime["dbname"] or server[2] != "127.0.0.1":
        raise ProductionVerificationError("database/listener identity differs from reviewed topology")
    if str(server[3]) != str(runtime["port"]) or server[4] != "on" or server[5] != "on":
        raise ProductionVerificationError("port/TLS/WAL archive contract is not active")
    if not tls or tls[0] is not True:
        raise ProductionVerificationError("verified production connection is not protected by TLS")
    expected_cluster = runtime.get("cluster_contract") or {}
    if not (
        cluster_settings[0] == expected_cluster.get("encoding") == "UTF8"
        and str(cluster_settings[1]).endswith(".simple")
        and expected_cluster.get("text_search_config") == "simple"
        and cluster_settings[2] == "on"
        and expected_cluster.get("data_checksums") is True
        and database_locale[0] == "UTF8"
        and database_locale[1] == "b"
        and database_locale[2] == expected_cluster.get("builtin_locale") == "C.UTF-8"
        and expected_cluster.get("locale_provider") == "builtin"
    ):
        raise ProductionVerificationError(
            "cluster locale/encoding/checksum identity differs from reviewed contract"
        )
    expected_migrations = []
    for name in (
        "0001_user_content_notes_expand.sql",
        "0002_user_content_notes_cutover_expand.sql",
        "0003_stage4_migration_staging.sql",
        "0004_user_content_writer_identity_separation.sql",
    ):
        expected_migrations.append([name.removesuffix(".sql"), _sha_file(repo_root / "migrations/postgresql" / name)])
    observed = {row[0]: row[1] for row in migrations}
    for migration_id, migration_sha in expected_migrations:
        if observed.get(migration_id) != migration_sha:
            raise ProductionVerificationError(f"migration identity mismatch: {migration_id}")
    for row in authority:
        if row[1] not in {"S0", "S1"} or row[2] != "sqlite_transition" or any(
            value is not None for value in row[3:]
        ):
            raise ProductionVerificationError("authority control exceeds S0/S1")
    if formal_idempotency_records:
        raise ProductionVerificationError("formal PostgreSQL application mutations already exist")
    if not str(server[6]).strip() or str(server[6]).strip() in {"(disabled)", ""}:
        raise ProductionVerificationError("WAL archive command is not configured")

    core = {
        "schema_version": "honghu.stage4_production_postgresql_verification.v1",
        "environment_id": "production",
        "application_commit_sha": application_commit_sha,
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_config_sha256": _sha_file(runtime_path),
        "tracked_route_sha256": _sha_file(route_path),
        "server": {
            "version": server[0],
            "database": server[1],
            "listen_addresses": server[2],
            "port": int(server[3]),
            "ssl": server[4],
            "archive_mode": server[5],
            "archive_command_configured": True,
        },
        "cluster_contract": {
            "server_encoding": cluster_settings[0],
            "default_text_search_config": cluster_settings[1],
            "data_checksums": cluster_settings[2],
            "database_encoding": database_locale[0],
            "database_locale_provider": database_locale[1],
            "database_locale": database_locale[2],
        },
        "tls": {"verified": bool(tls[0]), "version": tls[1], "cipher": tls[2]},
        "credential_presence": credential_presence,
        "role_attributes": role_attributes,
        "migrations": migrations,
        "authority": authority,
        "unit_snapshots": unit_snapshots,
        "formal_application_idempotency_records": formal_idempotency_records,
        "application_authority": "sqlite_transition",
        "production_cutover_authorized": False,
    }
    return {**core, "evidence_sha256": _sha(core)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--application-commit-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = verify_production_candidate(
        repo_root=args.repo_root.resolve(),
        runtime_path=args.runtime.resolve(),
        application_commit_sha=args.application_commit_sha,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
