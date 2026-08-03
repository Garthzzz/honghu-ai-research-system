from __future__ import annotations

import sqlite3

from .db import dict_row


def default_market_state(entity_type: str, external_ref_type: str | None) -> tuple[str, str, str]:
    if entity_type != "company":
        return ("not_applicable", "not_applicable", "非公司机会对象没有直接交易证券。")
    if external_ref_type in {"ticker", "security"}:
        return ("unnoticed", "unknown", "存在直接证券映射，但尚未提供市场反应数据。")
    return ("market_data_missing", "unknown", "公司缺少已复核的直接证券或代理映射。")


def upsert_market_reaction(
    conn: sqlite3.Connection,
    run_id: int,
    entity_id: int,
    composite_score_id: int,
    entity_type: str,
    external_ref_type: str | None,
) -> int:
    state, region, reason = default_market_state(entity_type, external_ref_type)
    row = conn.execute(
        """
        INSERT INTO opportunity_market_reaction(
            run_id, entity_id, composite_score_id, market_reflection_state,
            benchmark_region, proxy_mapping_status, proxy_reason,
            reaction_multiplier, evidence_ref_uri
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            entity_id,
            composite_score_id,
            state,
            region,
            "not_required" if state == "not_applicable" else "insufficient_evidence",
            reason,
            1.0,
            f"opp://composite_score/{composite_score_id}",
        ),
    )
    return int(row.lastrowid)


def get_market_reaction(conn: sqlite3.Connection, entity_id: int, composite_score_id: int | None = None) -> dict | None:
    params: list[int] = [entity_id]
    clause = ""
    if composite_score_id is not None:
        clause = " AND composite_score_id=?"
        params.append(composite_score_id)
    return dict_row(
        conn.execute(
            f"""
            SELECT *
            FROM opportunity_market_reaction
            WHERE entity_id=? {clause}
            ORDER BY id DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
    )
