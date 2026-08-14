from __future__ import annotations

"""Exercise the shared-identity S1→S2→S3 contract on an isolated PostgreSQL DB.

This tool is a rehearsal helper, not a production cutover command.  It proves
the authority transition, writer fence, atomic snapshot activation and
idempotent uncertain-response replay against real PostgreSQL semantics.
"""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from tools.migration.stage4_s1_loader import _connection_from_runtime


class SharedIdentityRehearsalError(RuntimeError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def rehearse_shared_identity_cutover(
    connection: Any,
    *,
    expected_snapshot_id: str,
    writer_identity: str,
    cutover_epoch: str,
    actor: str,
    approval_reference: str,
) -> dict[str, Any]:
    previous_autocommit = bool(connection.autocommit)
    connection.autocommit = True
    try:
        before = connection.execute(
            """
            SELECT a.state,a.state_revision,a.authoritative_backend,
                   s.source_snapshot_id,s.target_row_count,s.formal_business_data
              FROM operations.cutover_unit_authority a
              JOIN shared_identity.unit_snapshot s USING (cutover_unit)
             WHERE a.cutover_unit='shared_identity'
            """
        ).fetchone()
        if before is None or tuple(before[:3]) != ("S1", int(before[1]), "sqlite_transition"):
            raise SharedIdentityRehearsalError("shared_identity is not a reconciled S1 target")
        if str(before[3]) != expected_snapshot_id or bool(before[5]):
            raise SharedIdentityRehearsalError("shared_identity S1 snapshot identity is stale")

        sqlite_watermark = {
            "rehearsal": True,
            "source_snapshot_id": expected_snapshot_id,
            "row_count": int(before[4]),
        }
        transition = connection.execute(
            """
            SELECT * FROM operations.transition_shared_identity(
                %s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s
            )
            """,
            (
                "S1",
                int(before[1]),
                "S2",
                writer_identity,
                cutover_epoch,
                json.dumps(sqlite_watermark),
                actor,
                approval_reference,
                "isolated shared identity cutover rehearsal",
            ),
        ).fetchone()
        if transition is None or tuple(transition[1:]) != ("S2", int(before[1]) + 1):
            raise SharedIdentityRehearsalError("shared_identity did not enter S2")

        request = {
            "operation": "activate_snapshot_v1",
            "snapshot_id": expected_snapshot_id,
            "writer_identity": writer_identity,
        }
        request_sha = _sha(request)
        idempotency_key = f"rehearsal:{cutover_epoch}"

        wrong_writer_rejected = False
        try:
            connection.execute(
                "SELECT shared_identity.activate_snapshot_v1(%s,%s,%s,%s,%s,%s)",
                (
                    expected_snapshot_id,
                    int(transition[2]),
                    idempotency_key,
                    request_sha,
                    writer_identity + ":wrong",
                    actor,
                ),
            ).fetchone()
        except Exception:
            wrong_writer_rejected = True
        if not wrong_writer_rejected:
            raise SharedIdentityRehearsalError("wrong writer was not fenced")

        result = connection.execute(
            "SELECT shared_identity.activate_snapshot_v1(%s,%s,%s,%s,%s,%s)",
            (
                expected_snapshot_id,
                int(transition[2]),
                idempotency_key,
                request_sha,
                writer_identity,
                actor,
            ),
        ).fetchone()[0]
        replay = connection.execute(
            "SELECT shared_identity.activate_snapshot_v1(%s,%s,%s,%s,%s,%s)",
            (
                expected_snapshot_id,
                int(transition[2]),
                idempotency_key,
                request_sha,
                writer_identity,
                actor,
            ),
        ).fetchone()[0]
        if result != replay:
            raise SharedIdentityRehearsalError("idempotent activation replay changed result")

        conflicting_replay_rejected = False
        try:
            connection.execute(
                "SELECT shared_identity.activate_snapshot_v1(%s,%s,%s,%s,%s,%s)",
                (
                    expected_snapshot_id,
                    int(transition[2]),
                    idempotency_key,
                    "0" * 64,
                    writer_identity,
                    actor,
                ),
            ).fetchone()
        except Exception:
            conflicting_replay_rejected = True
        if not conflicting_replay_rejected:
            raise SharedIdentityRehearsalError("conflicting idempotency replay was accepted")

        after = connection.execute(
            """
            SELECT a.state,a.state_revision,a.authoritative_backend,a.writer_identity,
                   a.postgresql_first_formal_commit,
                   s.authority_state,s.formal_business_data,s.current_formal_row_count,
                   (SELECT count(*) FROM shared_identity.legacy_record
                     WHERE formal_business_data=true)
              FROM operations.cutover_unit_authority a
              JOIN shared_identity.unit_snapshot s USING (cutover_unit)
             WHERE a.cutover_unit='shared_identity'
            """
        ).fetchone()
        if after is None:
            raise SharedIdentityRehearsalError("shared_identity authority disappeared")
        if tuple(after[:4]) != (
            "S3",
            int(transition[2]) + 1,
            "postgresql_production",
            writer_identity,
        ):
            raise SharedIdentityRehearsalError("shared_identity S3 authority is inconsistent")
        if after[4] is None or str(after[5]) != "S3" or not bool(after[6]):
            raise SharedIdentityRehearsalError("first formal activation was not atomic with S3")
        if int(after[7]) != int(after[8]) or int(after[7]) != int(before[4]):
            raise SharedIdentityRehearsalError("formal shared_identity row count is inconsistent")

        researcher_request_sha = _sha(
            {
                "operation": "create_researcher_v1",
                "name": "__stage4_rehearsal_researcher__",
            }
        )
        researcher = connection.execute(
            """SELECT shared_identity.create_researcher_v1(
                %s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s
            )""",
            (
                "__stage4_rehearsal_researcher__",
                "Stage 4 Rehearsal Researcher",
                "isolated rehearsal only",
                "[]",
                None,
                "rehearsal:create-researcher",
                researcher_request_sha,
                writer_identity,
                actor,
            ),
        ).fetchone()[0]
        researcher_replay = connection.execute(
            """SELECT shared_identity.create_researcher_v1(
                %s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s
            )""",
            (
                "__stage4_rehearsal_researcher__",
                "Stage 4 Rehearsal Researcher",
                "isolated rehearsal only",
                "[]",
                None,
                "rehearsal:create-researcher",
                researcher_request_sha,
                writer_identity,
                actor,
            ),
        ).fetchone()[0]
        if researcher != researcher_replay:
            raise SharedIdentityRehearsalError(
                "researcher uncertain-response replay changed result"
            )

        company_request_sha = _sha(
            {
                "operation": "ensure_listed_company_v1",
                "ticker": "999999.SH",
                "venue": "shanghai",
            }
        )
        company = connection.execute(
            """SELECT shared_identity.ensure_listed_company_v1(
                %s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s
            )""",
            (
                "__stage4_rehearsal_company__",
                "999999.SH",
                "A股",
                "listed",
                "stage4-rehearsal-only",
                "[]",
                "company:security:999999.SH:venue:shanghai",
                "rehearsal:ensure-company",
                company_request_sha,
                writer_identity,
                actor,
            ),
        ).fetchone()[0]
        company_replay = connection.execute(
            """SELECT shared_identity.ensure_listed_company_v1(
                %s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s
            )""",
            (
                "__stage4_rehearsal_company__",
                "999999.SH",
                "A股",
                "listed",
                "stage4-rehearsal-only",
                "[]",
                "company:security:999999.SH:venue:shanghai",
                "rehearsal:ensure-company",
                company_request_sha,
                writer_identity,
                actor,
            ),
        ).fetchone()[0]
        if company != company_replay:
            raise SharedIdentityRehearsalError(
                "listed-company uncertain-response replay changed result"
            )
        final_counts = connection.execute(
            """SELECT s.current_formal_row_count,
                      (SELECT count(*) FROM shared_identity.legacy_record
                        WHERE formal_business_data=true),
                      (SELECT count(*) FROM shared_identity.mutation_audit)
                 FROM shared_identity.unit_snapshot s
                WHERE s.cutover_unit='shared_identity'"""
        ).fetchone()
        if final_counts is None or int(final_counts[0]) != int(before[4]) + 5:
            raise SharedIdentityRehearsalError(
                "formal shared identity mutations did not update the snapshot watermark"
            )
        if int(final_counts[0]) != int(final_counts[1]) or int(final_counts[2]) != 2:
            raise SharedIdentityRehearsalError(
                "formal mutation rows or audit evidence are inconsistent"
            )

        core = {
            "schema_version": "honghu.shared_identity_cutover_rehearsal.v1",
            "cutover_unit": "shared_identity",
            "source_snapshot_id": expected_snapshot_id,
            "source_row_count": int(before[4]),
            "authority_before": "S1",
            "authority_after": "S3",
            "state_revision_after": int(after[1]),
            "authoritative_backend_after": str(after[2]),
            "wrong_writer_rejected": wrong_writer_rejected,
            "idempotent_replay_equal": result == replay,
            "conflicting_replay_rejected": conflicting_replay_rejected,
            "formal_row_count": int(after[7]),
            "formal_row_count_after_mutations": int(final_counts[0]),
            "researcher_idempotent_replay_equal": researcher == researcher_replay,
            "company_idempotent_replay_equal": company == company_replay,
            "mutation_audit_count": int(final_counts[2]),
            "isolated_rehearsal_only": True,
        }
        return {**core, "evidence_sha256": _sha(core)}
    finally:
        connection.autocommit = previous_autocommit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--expected-snapshot-id", required=True)
    parser.add_argument("--writer-identity", required=True)
    parser.add_argument("--cutover-epoch", required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--approval-reference", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    connection = _connection_from_runtime(args.runtime, "migration")
    try:
        result = rehearse_shared_identity_cutover(
            connection,
            expected_snapshot_id=args.expected_snapshot_id,
            writer_identity=args.writer_identity,
            cutover_epoch=args.cutover_epoch,
            actor=args.actor,
            approval_reference=args.approval_reference,
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
