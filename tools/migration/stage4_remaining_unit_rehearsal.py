from __future__ import annotations

"""Exercise the common remaining-unit authority contract on isolated PostgreSQL.

This command is intentionally incapable of targeting the production database:
it accepts loopback only and requires ``rehearsal`` in the database name.  It
proves the real SQL functions, role fencing, S1/S2/S3 transition, release-to-
snapshot binding, idempotent replay, stale revision rejection and ownership
fence without touching SQLite or production authority.
"""

import argparse
import hashlib
import json
import re
import tempfile
import uuid
from pathlib import Path
from typing import Any


class RemainingUnitRehearsalError(RuntimeError):
    pass


REPRESENTATIVE_OBJECTS = {
    "financial_data": ("financial.db", "financial_observation"),
    "research_publication": ("research.db", "source"),
    "dynamic_intelligence": ("research.db", "event"),
    "operations_governance": ("research.db", "fetch_schedule"),
    "investment_hypotheses": ("research.db", "hypothesis"),
    "opportunity_lens": ("opportunity_lens.db", "opportunity_run"),
    "sentiment_analytics": ("sentiment.db", "senti_company"),
}


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def validate_target(host: str, dbname: str) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise RemainingUnitRehearsalError("rehearsal target must be loopback")
    if "rehearsal" not in dbname.casefold():
        raise RemainingUnitRehearsalError("database name must identify an isolated rehearsal")


def validate_application_commit(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise RemainingUnitRehearsalError(
            "rehearsal requires an exact lowercase application commit"
        )
    return value


def _connect(host: str, port: int, dbname: str, user: str) -> Any:
    import psycopg

    # Dev/test roles are deliberately NOLOGIN.  A cluster-local superuser may
    # assume their session authorization in this isolated database so SQL that
    # fences on session_user is rehearsed exactly without weakening role DDL.
    connection = psycopg.connect(
        host=host, port=port, dbname=dbname, user="honghu_devtest"
    )
    if user != "honghu_devtest":
        if not re.fullmatch(r"honghu_[a-z_]+", user):
            connection.close()
            raise RemainingUnitRehearsalError("unsafe rehearsal role identity")
        connection.execute(f'SET SESSION AUTHORIZATION "{user}"')
        # SET starts an implicit transaction in psycopg.  Commit it before the
        # rehearsal's explicit transaction blocks, otherwise their contexts
        # become savepoints and can retain authority-row locks.
        connection.commit()
    return connection


def run_rehearsal(
    *, host: str, port: int, dbname: str, unit: str, application_commit_sha: str
) -> dict[str, Any]:
    validate_target(host, dbname)
    adapter_release = validate_application_commit(application_commit_sha)
    try:
        source_database, source_table = REPRESENTATIVE_OBJECTS[unit]
    except KeyError as exc:
        raise RemainingUnitRehearsalError(
            "unit has no representative rehearsal object"
        ) from exc
    admin = _connect(host, port, dbname, "honghu_devtest")
    controller = _connect(host, port, dbname, "honghu_controller")
    writer_name = f"honghu_writer_{unit}"
    writer = _connect(host, port, dbname, writer_name)
    snapshot_id = f"rehearsal:{uuid.uuid4().hex}"
    epoch = f"rehearsal:{uuid.uuid4().hex}"
    approval = "rehearsal-only-not-production-approval"
    source_release = "b" * 40
    source_payload = {"id": 1, "value": "baseline"}
    source_key = _sha([["id", 1]])
    row_sha = _sha(source_payload)
    schema = {
        "columns": [
            {"cid": 0, "name": "id", "type": "INTEGER", "notnull": 1, "default": None, "pk": 1},
            {"cid": 1, "name": "value", "type": "TEXT", "notnull": 0, "default": None, "pk": 0},
        ],
        "indexes": [],
        "foreign_keys": [],
    }
    watermark = {
        "tables": [
            {
                "source_database": source_database,
                "source_table": source_table,
                "schema": schema,
                "row_count": 1,
            }
        ]
    }
    content_sha = hashlib.sha256(
        (json.dumps((source_database, source_table, 1, source_key, row_sha), separators=(",", ":")) + "\n").encode("utf-8")
    ).hexdigest()
    reconciliation = {
        "status": "pass",
        "source_row_count": 1,
        "target_row_count": 1,
        "source_content_sha256": content_sha,
        "target_content_sha256": content_sha,
    }
    request_sha = _sha(
        {
            "cutover_unit": unit,
            "source_snapshot_id": snapshot_id,
            "application_commit_sha": adapter_release,
            "approval_reference": approval,
        }
    )
    try:
        with admin.transaction():
            # Rehearsal databases are intentionally reusable.  Authority audit
            # revisions are append-only in production, so they do not cascade
            # when the synthetic authority row is reset; remove only this
            # synthetic unit's prior rehearsal records before seeding revision
            # 1 again.
            admin.execute(
                "DELETE FROM audit.domain_record_revision WHERE cutover_unit=%s",
                (unit,),
            )
            admin.execute(
                "DELETE FROM audit.cutover_unit_authority_revision WHERE cutover_unit=%s",
                (unit,),
            )
            admin.execute(
                "DELETE FROM domain_data.mutation_result WHERE cutover_unit=%s",
                (unit,),
            )
            admin.execute(
                "DELETE FROM domain_data.record_overlay WHERE cutover_unit=%s",
                (unit,),
            )
            admin.execute(
                "DELETE FROM domain_data.formal_unit_snapshot WHERE cutover_unit=%s",
                (unit,),
            )
            if unit == "financial_data":
                admin.execute("DELETE FROM financial_data.legacy_record")
                admin.execute("DELETE FROM financial_data.unit_snapshot")
            admin.execute(
                "DELETE FROM operations.cutover_unit_authority WHERE cutover_unit=%s",
                (unit,),
            )
            admin.execute(
                """INSERT INTO operations.cutover_unit_authority(
                    cutover_unit,state,authoritative_backend,state_revision,
                    approval_reference,updated_by
                ) VALUES(%s,'S1','sqlite_transition',1,%s,%s)""",
                (unit, approval, "principal:rehearsal-controller"),
            )
            admin.execute(
                """INSERT INTO migration.unit_snapshot(
                    snapshot_id,cutover_unit,source_identity_sha256,
                    application_commit_sha,registry_sha256,source_created_at,
                    source_watermark,target_watermark,reconciliation,
                    lifecycle_state,formal_business_data
                ) VALUES(%s,%s,%s,%s,%s,clock_timestamp(),%s::jsonb,%s::jsonb,%s::jsonb,'reconciled',false)""",
                (
                    snapshot_id,
                    unit,
                    "c" * 64,
                    source_release,
                    "d" * 64,
                    json.dumps(watermark),
                    json.dumps({"row_count": 1, "content_sha256": content_sha, "formal_business_data": False}),
                    json.dumps(reconciliation),
                ),
            )
            admin.execute(
                """INSERT INTO migration.source_row(
                    snapshot_id,cutover_unit,source_database,source_table,
                    source_ordinal,source_key,row_sha256,payload
                ) VALUES(%s,%s,%s,%s,1,%s,%s,%s::jsonb)""",
                (
                    snapshot_id,
                    unit,
                    source_database,
                    source_table,
                    source_key,
                    row_sha,
                    json.dumps(source_payload),
                ),
            )
            if unit == "financial_data":
                admin.execute(
                    """INSERT INTO financial_data.unit_snapshot(
                        cutover_unit,source_snapshot_id,source_identity_sha256,
                        shared_identity_snapshot_id,shared_identity_mapping_sha256,
                        source_row_count,target_row_count,source_content_sha256,
                        target_content_sha256,authority_state,formal_business_data
                    ) VALUES(
                        'financial_data',%s,%s,'rehearsal-shared',%s,
                        1,1,%s,%s,'S1',false
                    )""",
                    (snapshot_id, "c" * 64, "e" * 64, content_sha, content_sha),
                )
                admin.execute(
                    """INSERT INTO financial_data.legacy_record(
                        source_table,legacy_id,stable_key,row_sha256,payload,
                        source_snapshot_id,source_ordinal,formal_business_data
                    ) VALUES('financial_observation','1','rehearsal:1',%s,%s::jsonb,%s,1,false)""",
                    (row_sha, json.dumps(source_payload), snapshot_id),
                )
        with controller.transaction():
            transitioned = controller.execute(
                """SELECT * FROM operations.transition_remaining_unit(
                    %s,'S1',1,'S2',%s,%s,%s::jsonb,%s,%s,%s
                )""",
                (
                    unit,
                    writer_name,
                    epoch,
                    json.dumps({"snapshot_id": snapshot_id, "row_count": 1}),
                    "principal:rehearsal-controller",
                    approval,
                    "isolated rehearsal",
                ),
            ).fetchone()
        if transitioned is None or str(transitioned[1]) != "S2":
            raise RemainingUnitRehearsalError("S1 to S2 transition failed")
        with writer.transaction():
            activated = writer.execute(
                """SELECT domain_data.activate_unit_snapshot_v1(
                    %s,%s,2,%s,%s,%s,%s,%s
                )""",
                (
                    unit,
                    snapshot_id,
                    f"activate:{uuid.uuid4().hex}",
                    request_sha,
                    adapter_release,
                    writer_name,
                    "principal:rehearsal-writer",
                ),
            ).fetchone()
        if activated is None:
            raise RemainingUnitRehearsalError("S2 activation returned no result")
        mutation = {
            "source_database": source_database,
            "source_table": source_table,
            "source_key": source_key,
            "payload": {"id": 1, "value": "updated"},
            "row_sha256": _sha({"id": 1, "value": "updated"}),
            "expected_revision": 1,
            "delete": False,
        }
        mutation["request_sha256"] = _sha(mutation)
        operation_key = f"mutation:{uuid.uuid4().hex}"
        batch_sha = _sha([mutation])
        with writer.transaction():
            first = writer.execute(
                "SELECT domain_data.apply_mutation_batch_v1(%s,%s,%s,%s,%s::jsonb,%s,%s)",
                (unit, "rehearsal", operation_key, batch_sha, json.dumps([mutation]), writer_name, "principal:rehearsal-writer"),
            ).fetchone()[0]
        with writer.transaction():
            replay = writer.execute(
                "SELECT domain_data.apply_mutation_batch_v1(%s,%s,%s,%s,%s::jsonb,%s,%s)",
                (unit, "rehearsal", operation_key, batch_sha, json.dumps([mutation]), writer_name, "principal:rehearsal-writer"),
            ).fetchone()[0]
        if first != replay:
            raise RemainingUnitRehearsalError("idempotent replay changed result")
        persistent_projection_verified = False
        if unit == "sentiment_analytics":
            from tools.data_platform.sentiment_projection import (
                PersistentSentimentProjection,
            )

            with tempfile.TemporaryDirectory(prefix="honghu-sentiment-rehearsal-") as raw:
                projection = PersistentSentimentProjection(
                    Path(raw),
                    lambda: _connect(host, port, dbname, "honghu_viewer_reader"),
                )
                compatibility = projection.connect_writer(
                    lambda: _connect(host, port, dbname, writer_name),
                    writer_identity=writer_name,
                    operation_scope="sentiment-rehearsal",
                    operation_id=f"persistent:{uuid.uuid4().hex}",
                    actor="principal:rehearsal-writer",
                )
                try:
                    before_value = compatibility.execute(
                        f'SELECT value FROM "{source_table}" WHERE id=1'
                    ).fetchone()[0]
                    compatibility.execute(
                        f'UPDATE "{source_table}" SET value=? WHERE id=1',
                        ("persistent-updated",),
                    )
                    compatibility.commit()
                finally:
                    compatibility.close()
                projected = projection.connect_readonly()
                try:
                    after_value = projected.execute(
                        f'SELECT value FROM "{source_table}" WHERE id=1'
                    ).fetchone()[0]
                finally:
                    projected.close()
                persistent_projection_verified = (
                    before_value == "updated"
                    and after_value == "persistent-updated"
                    and projection.database_path.is_file()
                )
            if not persistent_projection_verified:
                raise RemainingUnitRehearsalError(
                    "persistent sentiment projection roundtrip failed"
                )
        stale_rejected = False
        outside_rejected = False
        try:
            stale = dict(mutation)
            stale["payload"] = {"id": 1, "value": "stale"}
            stale["row_sha256"] = _sha(stale["payload"])
            stale["request_sha256"] = _sha(stale)
            with writer.transaction():
                writer.execute(
                    "SELECT domain_data.apply_mutation_batch_v1(%s,%s,%s,%s,%s::jsonb,%s,%s)",
                    (unit, "rehearsal-stale", f"stale:{uuid.uuid4().hex}", _sha([stale]), json.dumps([stale]), writer_name, "principal:rehearsal-writer"),
                ).fetchone()
        except Exception:
            stale_rejected = True
            writer.rollback()
        try:
            outside = dict(mutation)
            outside.update(source_table="outside_reviewed_ownership", expected_revision=0)
            outside["request_sha256"] = _sha(outside)
            with writer.transaction():
                writer.execute(
                    "SELECT domain_data.apply_mutation_batch_v1(%s,%s,%s,%s,%s::jsonb,%s,%s)",
                    (unit, "rehearsal-outside", f"outside:{uuid.uuid4().hex}", _sha([outside]), json.dumps([outside]), writer_name, "principal:rehearsal-writer"),
                ).fetchone()
        except Exception:
            outside_rejected = True
            writer.rollback()
        final = admin.execute(
            """SELECT a.state,a.authoritative_backend,a.writer_identity,
                      s.application_commit_sha,s.source_snapshot_id,
                      (SELECT count(*) FROM audit.domain_record_revision WHERE cutover_unit=%s)
                 FROM operations.cutover_unit_authority a
                 JOIN domain_data.formal_unit_snapshot s USING(cutover_unit)
                WHERE a.cutover_unit=%s""",
            (unit, unit),
        ).fetchone()
        expected_audit_count = 2 if unit == "sentiment_analytics" else 1
        if final is None or tuple(final[:5]) != (
            "S3", "postgresql_production", writer_name, adapter_release, snapshot_id
        ) or int(final[5]) != expected_audit_count or not stale_rejected or not outside_rejected:
            raise RemainingUnitRehearsalError("final rehearsal contract is not green")
        core = {
            "schema_version": "honghu.remaining_unit_postgresql_rehearsal.v1",
            "database": dbname,
            "cutover_unit": unit,
            "state": "S3",
            "authoritative_backend": "postgresql_production",
            "source_snapshot_application_commit_sha": source_release,
            "adapter_application_commit_sha": adapter_release,
            "idempotent_replay": True,
            "stale_revision_rejected": stale_rejected,
            "outside_ownership_rejected": outside_rejected,
            "audit_revision_count": int(final[5]),
            "persistent_projection_verified": persistent_projection_verified,
            "legacy_sqlite_opened": False,
            "production_target_permitted": False,
        }
        return {**core, "evidence_sha256": _sha(core)}
    finally:
        writer.close()
        controller.close()
        admin.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=55432)
    parser.add_argument("--dbname", required=True)
    parser.add_argument("--unit", choices=sorted(REPRESENTATIVE_OBJECTS), required=True)
    parser.add_argument("--application-commit-sha", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = run_rehearsal(
        host=args.host,
        port=args.port,
        dbname=args.dbname,
        unit=args.unit,
        application_commit_sha=args.application_commit_sha,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
