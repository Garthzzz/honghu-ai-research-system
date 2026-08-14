from __future__ import annotations

"""Reusable cutover authority validation for recovery and deployment gates."""

from collections.abc import Iterable, Mapping
from typing import Any


class AuthorityControlError(RuntimeError):
    pass


def authority_snapshot(
    row: Any,
    *,
    cutover_unit: str | None = None,
    allow_s2: bool = False,
) -> dict[str, Any]:
    if row is None:
        label = cutover_unit or "requested cutover unit"
        raise AuthorityControlError(f"{label} authority row is missing")

    if isinstance(row, Mapping):
        observed_unit = str(row.get("cutover_unit") or cutover_unit or "")
        values = [
            row.get("state"),
            row.get("authoritative_backend"),
            row.get("writer_identity"),
            row.get("cutover_epoch"),
            row.get("sqlite_final_watermark"),
            row.get("postgresql_first_formal_commit"),
            row.get("state_revision"),
            row.get("approval_reference"),
        ]
    else:
        values = list(row)
        if len(values) == 9:
            observed_unit = str(values.pop(0))
        elif len(values) == 8:
            observed_unit = str(cutover_unit or "")
        else:
            raise AuthorityControlError("authority row has an unsupported shape")

    if not observed_unit:
        raise AuthorityControlError("authority row has no cutover unit identity")
    if cutover_unit is not None and observed_unit != cutover_unit:
        raise AuthorityControlError("authority row belongs to another cutover unit")

    snapshot = {
        "cutover_unit": observed_unit,
        "state": str(values[0]),
        "authoritative_backend": str(values[1]),
        "writer_identity": str(values[2]) if values[2] is not None else None,
        "cutover_epoch": str(values[3]) if values[3] is not None else None,
        "sqlite_final_watermark": str(values[4]) if values[4] is not None else None,
        "postgresql_first_formal_commit": (
            str(values[5]) if values[5] is not None else None
        ),
        "state_revision": int(values[6]),
        "approval_reference": str(values[7] or ""),
    }
    state = snapshot["state"]
    if state in {"S0", "S1"}:
        if snapshot["authoritative_backend"] != "sqlite_transition" or any(
            snapshot[key] is not None
            for key in (
                "writer_identity",
                "cutover_epoch",
                "sqlite_final_watermark",
                "postgresql_first_formal_commit",
            )
        ):
            raise AuthorityControlError("S0/S1 authority snapshot is inconsistent")
    elif state == "S2":
        if not allow_s2:
            raise AuthorityControlError(
                "recovery rehearsal is forbidden during the short S2 cutover fence"
            )
        if (
            snapshot["authoritative_backend"] != "postgresql_production"
            or not snapshot["writer_identity"]
            or not snapshot["cutover_epoch"]
            or not snapshot["sqlite_final_watermark"]
            or snapshot["postgresql_first_formal_commit"] is not None
        ):
            raise AuthorityControlError("S2 authority snapshot is inconsistent")
    elif state in {"S3", "S4"}:
        if snapshot["authoritative_backend"] != "postgresql_production" or any(
            not snapshot[key]
            for key in (
                "writer_identity",
                "cutover_epoch",
                "sqlite_final_watermark",
                "postgresql_first_formal_commit",
            )
        ):
            raise AuthorityControlError("S3/S4 authority snapshot is incomplete")
    else:
        raise AuthorityControlError(f"unsupported authority state: {state}")
    if snapshot["state_revision"] < 1 or not snapshot["approval_reference"].strip():
        raise AuthorityControlError("authority revision/approval evidence is incomplete")
    return snapshot


def read_authority_snapshots(
    connection: Any,
    *,
    required_units: Iterable[str] | None = None,
    allow_s2: bool = False,
) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT cutover_unit, state, authoritative_backend, writer_identity,
               cutover_epoch, sqlite_final_watermark::text,
               postgresql_first_formal_commit::text, state_revision,
               approval_reference
          FROM operations.cutover_unit_authority
         ORDER BY cutover_unit
        """
    ).fetchall()
    snapshots: dict[str, dict[str, Any]] = {}
    for row in rows:
        snapshot = authority_snapshot(row, allow_s2=allow_s2)
        unit = snapshot["cutover_unit"]
        if unit in snapshots:
            raise AuthorityControlError(f"duplicate authority row: {unit}")
        snapshots[unit] = snapshot
    if not snapshots:
        raise AuthorityControlError("authority control table is empty")
    missing = sorted(set(required_units or ()) - set(snapshots))
    if missing:
        raise AuthorityControlError(f"required authority rows are missing: {missing}")
    return snapshots
