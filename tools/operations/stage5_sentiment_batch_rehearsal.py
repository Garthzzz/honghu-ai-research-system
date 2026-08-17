from __future__ import annotations

"""Exercise the exact Stage 5 sentiment batch function on isolated PostgreSQL."""

import argparse
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.migration.stage4_apply_postgresql_migrations import (
    MIGRATION_IDENTIFIERS,
    render_schema_migration,
)


MIGRATIONS = (
    "0001_user_content_notes_expand.sql",
    "0002_user_content_notes_cutover_expand.sql",
    "0003_stage4_migration_staging.sql",
    "0010_remaining_units_common_data_plane.sql",
    "0014_stage5_delegated_unit_writers.sql",
    "0015_stage5_initial_overlay_revision.sql",
    "0016_stage5_bounded_mutation_batch_result.sql",
    "0017_stage5_set_based_sentiment_delete_batch.sql",
)
REQUIRED_ROLES = (
    "honghu_viewer_reader",
    "honghu_controller",
    "honghu_audit_reader",
    "honghu_writer_financial_data",
    "honghu_writer_research_publication",
    "honghu_writer_dynamic_intelligence",
    "honghu_writer_operations_governance",
    "honghu_writer_investment_hypotheses",
    "honghu_writer_opportunity_lens",
    "honghu_writer_sentiment_analytics",
)


class RehearsalError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_json(value: Any) -> str:
    return _sha256_bytes(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    )


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _expect_sqlstate(call, expected: str) -> None:
    try:
        call()
    except Exception as exc:
        if getattr(exc, "sqlstate", None) != expected:
            raise RehearsalError(
                f"expected SQLSTATE {expected}, received {getattr(exc, 'sqlstate', None)}"
            ) from exc
    else:
        raise RehearsalError(f"expected SQLSTATE {expected}")


def _mutation(key: str, *, revision: int = 1, delete: bool = True) -> dict[str, Any]:
    payload = {"id": key, "body": f"fixture-{key}"}
    mutation = {
        "source_database": "sentiment.db",
        "source_table": "senti_raw",
        "source_key": key,
        "payload": payload,
        "row_sha256": _sha256_json(payload),
        "expected_revision": revision,
        "delete": delete,
    }
    mutation["request_sha256"] = _sha256_json(mutation)
    return mutation


def _call_batch(
    connection: Any,
    *,
    scope: str,
    key: str,
    mutations: list[dict[str, Any]],
    writer: str = "honghu_writer_sentiment_analytics",
    request_sha: str | None = None,
) -> dict[str, Any]:
    request_sha = request_sha or _sha256_json(mutations)
    row = connection.execute(
        "SELECT domain_data.apply_mutation_batch_v1(%s,%s,%s,%s,%s::jsonb,%s,%s)",
        (
            "sentiment_analytics",
            scope,
            key,
            request_sha,
            json.dumps(mutations, ensure_ascii=False, separators=(",", ":")),
            writer,
            "principal:stage5-rehearsal",
        ),
    ).fetchone()
    if row is None or not isinstance(row[0], dict):
        raise RehearsalError("batch function returned no JSON object")
    return row[0]


def _apply_migrations(connection: Any, root: Path) -> list[dict[str, str]]:
    applied: list[dict[str, str]] = []
    for name in MIGRATIONS:
        path = root / "migrations" / "postgresql" / name
        digest = _sha256_bytes(path.read_bytes())
        rendered = render_schema_migration(
            path.read_text(encoding="utf-8"),
            digest,
            identifiers=MIGRATION_IDENTIFIERS.get(name),
        )
        connection.execute(rendered)
        recorded = connection.execute(
            "SELECT migration_sha256 FROM operations.schema_migration WHERE migration_id=%s",
            (path.stem,),
        ).fetchone()
        if recorded is None or recorded[0] != digest:
            raise RehearsalError(f"migration identity mismatch: {name}")
        applied.append({"migration_id": path.stem, "sha256": digest})
    return applied


def run_rehearsal(
    *,
    root: Path,
    host: str,
    port: int,
    admin_user: str,
    database: str,
    row_count: int,
) -> dict[str, Any]:
    if host not in {"127.0.0.1", "localhost", "::1"} or port == 5432:
        raise RehearsalError("rehearsal requires a non-production loopback PostgreSQL")
    if not re.fullmatch(r"honghu_stage3_[a-z0-9_]+", database):
        raise RehearsalError("rehearsal database must use the honghu_stage3_ prefix")
    if row_count < 1000 or row_count > 100_000:
        raise RehearsalError("row_count must be between 1000 and 100000")

    started = time.perf_counter()
    import psycopg
    from psycopg import sql

    admin_options = dict(host=host, port=port, user=admin_user, dbname="postgres")
    role = f"honghu_s5_rehearsal_{os.getpid()}"
    created_role = False
    database_created = False
    try:
        with psycopg.connect(**admin_options, autocommit=True) as cluster:
            missing = [
                name
                for name in REQUIRED_ROLES
                if cluster.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname=%s", (name,)
                ).fetchone()
                is None
            ]
            if missing:
                raise RehearsalError(f"required dev/test roles are absent: {missing}")
            if cluster.execute(
                "SELECT 1 FROM pg_roles WHERE rolname=%s", (role,)
            ).fetchone():
                raise RehearsalError("ephemeral rehearsal role already exists")
            cluster.execute(sql.SQL("CREATE ROLE {} LOGIN").format(sql.Identifier(role)))
            created_role = True
            cluster.execute(
                sql.SQL("GRANT {} TO {}").format(
                    sql.Identifier("honghu_writer_sentiment_analytics"),
                    sql.Identifier(role),
                )
            )
            cluster.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database))
            )
            cluster.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
            database_created = True

        target = dict(host=host, port=port, dbname=database)
        with psycopg.connect(**target, user=admin_user, autocommit=True) as admin:
            migrations = _apply_migrations(admin, root.resolve())
            snapshot = "stage5-sentiment-rehearsal"
            watermark = {
                "tables": [
                    {"source_database": "sentiment.db", "source_table": "senti_raw"}
                ]
            }
            admin.execute(
                "INSERT INTO migration.unit_snapshot VALUES "
                "(%s,'sentiment_analytics',%s,%s,%s,clock_timestamp(),clock_timestamp(),"
                "%s::jsonb,%s::jsonb,%s::jsonb,'reconciled',false)",
                (
                    snapshot,
                    "1" * 64,
                    "1" * 40,
                    "2" * 64,
                    json.dumps(watermark, separators=(",", ":")),
                    json.dumps({"row_count": row_count + 6}, separators=(",", ":")),
                    json.dumps({"status": "pass"}, separators=(",", ":")),
                ),
            )
            rows = []
            for ordinal in range(1, row_count + 7):
                key = f"row-{ordinal:06d}"
                payload = {"id": key, "body": f"fixture-{key}"}
                rows.append(
                    (
                        snapshot,
                        "sentiment_analytics",
                        "sentiment.db",
                        "senti_raw",
                        ordinal,
                        key,
                        _sha256_json(payload),
                        json.dumps(payload, separators=(",", ":")),
                    )
                )
            with admin.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO migration.source_row VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                    rows,
                )
            admin.execute(
                "INSERT INTO domain_data.formal_unit_snapshot VALUES "
                "('sentiment_analytics',%s,%s,%s,%s,%s::jsonb,%s,1,clock_timestamp())",
                (
                    snapshot,
                    "1" * 64,
                    "3" * 64,
                    row_count + 6,
                    json.dumps(watermark, separators=(",", ":")),
                    "4" * 40,
                ),
            )
            admin.execute(
                "INSERT INTO operations.cutover_unit_authority("
                "cutover_unit,state,authoritative_backend,writer_identity,cutover_epoch,"
                "sqlite_final_watermark,postgresql_first_formal_commit,state_revision,"
                "approval_reference,updated_by) VALUES "
                "('sentiment_analytics','S3','postgresql_production',"
                "'honghu_writer_sentiment_analytics','rehearsal-epoch',%s::jsonb,%s::jsonb,"
                "4,'stage5-rehearsal','principal:stage5-rehearsal')",
                (
                    json.dumps({"source": "fixture"}, separators=(",", ":")),
                    json.dumps({"commit": "fixture"}, separators=(",", ":")),
                ),
            )

        writer_options = dict(host=host, port=port, dbname=database, user=role)
        success_mutations = [
            _mutation(f"row-{ordinal:06d}") for ordinal in range(1, row_count + 1)
        ]
        with psycopg.connect(**writer_options, autocommit=True) as writer:
            success_started = time.perf_counter()
            summary = _call_batch(
                writer,
                scope="rehearsal_success",
                key="success-batch",
                mutations=success_mutations,
            )
            success_seconds = time.perf_counter() - success_started
            if summary.get("mutation_count") != row_count:
                raise RehearsalError("set-based success count mismatch")
            if summary.get("execution_mode") != "set_based_delete" or "mutations" in summary:
                raise RehearsalError("set-based result is not a bounded summary")

            with psycopg.connect(**target, user=admin_user, autocommit=True) as verify:
                before_replay = verify.execute(
                    "SELECT "
                    "(SELECT count(*) FROM domain_data.record_overlay),"
                    "(SELECT count(*) FROM audit.domain_record_revision),"
                    "(SELECT count(*) FROM domain_data.mutation_result)"
                ).fetchone()
            replay = _call_batch(
                writer,
                scope="rehearsal_success",
                key="success-batch",
                mutations=success_mutations,
            )
            with psycopg.connect(**target, user=admin_user, autocommit=True) as verify:
                after_replay = verify.execute(
                    "SELECT "
                    "(SELECT count(*) FROM domain_data.record_overlay),"
                    "(SELECT count(*) FROM audit.domain_record_revision),"
                    "(SELECT count(*) FROM domain_data.mutation_result)"
                ).fetchone()
            if replay != summary or after_replay != before_replay:
                raise RehearsalError("exact replay changed result or durable counts")

            _expect_sqlstate(
                lambda: _call_batch(
                    writer,
                    scope="rehearsal_success",
                    key="success-batch",
                    mutations=success_mutations,
                    request_sha="f" * 64,
                ),
                "23505",
            )
            _expect_sqlstate(
                lambda: _call_batch(
                    writer,
                    scope="wrong_writer",
                    key="wrong-writer",
                    mutations=[_mutation(f"row-{row_count + 3:06d}")],
                    writer="honghu_writer_dynamic_intelligence",
                ),
                "42501",
            )

            atomic_a_key = f"row-{row_count + 1:06d}"
            atomic_b_key = f"row-{row_count + 2:06d}"
            atomic_a = [_mutation(atomic_a_key)]
            atomic_b = [_mutation(atomic_b_key, revision=99)]
            _expect_sqlstate(
                lambda: _atomic_two_batch_failure(writer, atomic_a, atomic_b),
                "40001",
            )

            _expect_sqlstate(
                lambda: _call_batch(
                    writer,
                    scope="duplicate",
                    key="duplicate",
                    mutations=[
                        _mutation(f"row-{row_count + 4:06d}"),
                        _mutation(f"row-{row_count + 4:06d}"),
                    ],
                ),
                "22023",
            )
            outside = _mutation(f"row-{row_count + 5:06d}")
            outside["source_table"] = "not_owned"
            outside["request_sha256"] = _sha256_json(outside)
            _expect_sqlstate(
                lambda: _call_batch(
                    writer, scope="outside", key="outside", mutations=[outside]
                ),
                "42501",
            )

        with psycopg.connect(**target, user=admin_user, autocommit=True) as admin:
            atomic_residue = admin.execute(
                "SELECT "
                "(SELECT count(*) FROM domain_data.record_overlay WHERE source_key=%s),"
                "(SELECT count(*) FROM audit.domain_record_revision WHERE source_key=%s),"
                "(SELECT count(*) FROM domain_data.mutation_result WHERE idempotency_key LIKE 'atomic-a%%')",
                (atomic_a_key, atomic_a_key),
            ).fetchone()
            if atomic_residue != (0, 0, 0):
                raise RehearsalError("multi-chunk failure left durable partial writes")
            admin.execute(
                "UPDATE operations.cutover_unit_authority SET state='S2',"
                "postgresql_first_formal_commit=NULL WHERE cutover_unit='sentiment_analytics'"
            )
        try:
            with psycopg.connect(**writer_options, autocommit=True) as writer:
                _expect_sqlstate(
                    lambda: _call_batch(
                        writer,
                        scope="s2_fence",
                        key="s2-fence",
                        mutations=[_mutation(f"row-{row_count + 6:06d}")],
                    ),
                    "42501",
                )
        finally:
            with psycopg.connect(**target, user=admin_user, autocommit=True) as admin:
                admin.execute(
                    "UPDATE operations.cutover_unit_authority SET state='S3',"
                    "postgresql_first_formal_commit=%s::jsonb "
                    "WHERE cutover_unit='sentiment_analytics'",
                    (json.dumps({"commit": "fixture"}, separators=(",", ":")),),
                )

        with psycopg.connect(**writer_options, autocommit=True) as writer:
            mixed = _call_batch(
                writer,
                scope="mixed_fallback",
                key="mixed-upsert",
                mutations=[_mutation(f"row-{row_count + 6:06d}", delete=False)],
            )
            if mixed.get("execution_mode") != "row_fenced":
                raise RehearsalError("mixed/upsert batch bypassed the row-fenced path")

        return {
            "schema_version": "honghu.stage5_sentiment_batch_rehearsal.v1",
            "status": "pass",
            "checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "backend": "isolated_loopback_postgresql",
            "database": database,
            "row_count": row_count,
            "success_elapsed_seconds": round(success_seconds, 3),
            "bounded_summary": summary,
            "exact_replay_unchanged": True,
            "same_key_different_request_rejected": True,
            "multi_chunk_failure_zero_partial_writes": True,
            "duplicate_rejected": True,
            "outside_ownership_rejected": True,
            "wrong_writer_rejected": True,
            "s2_writer_fence_rejected": True,
            "mixed_upsert_execution_mode": mixed["execution_mode"],
            "migrations": migrations,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    finally:
        with psycopg.connect(**admin_options, autocommit=True) as cluster:
            if database_created:
                cluster.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname=%s AND pid<>pg_backend_pid()",
                    (database,),
                )
                cluster.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(database))
                )
            if created_role:
                cluster.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(role)))


def _atomic_two_batch_failure(
    writer: Any,
    first: list[dict[str, Any]],
    second: list[dict[str, Any]],
) -> None:
    with writer.transaction():
        _call_batch(writer, scope="atomic", key="atomic-a", mutations=first)
        _call_batch(writer, scope="atomic", key="atomic-b", mutations=second)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=55432)
    parser.add_argument("--admin-user", default="honghu_devtest")
    parser.add_argument("--database", default="honghu_stage3_sentiment_batch_rehearsal")
    parser.add_argument("--row-count", type=int, default=10_000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run_rehearsal(
        root=args.repo_root,
        host=args.host,
        port=args.port,
        admin_user=args.admin_user,
        database=args.database,
        row_count=args.row_count,
    )
    result["identity_sha256"] = _sha256_json(result)
    _write_json_atomic(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
