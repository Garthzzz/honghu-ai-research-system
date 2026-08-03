from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from .constants import (
    DB_PATH,
    EARLY_SIGNAL_RULE_VERSION,
    EVIDENCE_POLICY_VERSION,
    INTAKE_CONTRACT_VERSION,
    RESEARCH_WORKFLOW_CONTRACT_VERSION,
    RUN_PACK_SCHEMA_VERSION,
    SCHEMA_VERSION,
    VERSION_BUNDLE,
)
from .db import connect, execute_schema, table_names
from .score_trace import hash_json

REQUIRED_TABLES = {
    "opportunity_run",
    "opportunity_run_manifest",
    "opportunity_intake_contract",
    "opportunity_run_stats",
    "opportunity_search_plan",
    "opportunity_search_task",
    "opportunity_search_log",
    "opportunity_source_cluster",
    "opportunity_source_discovery",
    "opportunity_source",
    "opportunity_entity",
    "opportunity_entity_maturation",
    "opportunity_entity_research_profile",
    "opportunity_research_data_point",
    "opportunity_candidate_entity",
    "opportunity_entity_mapping",
    "opportunity_claim_evidence",
    "opportunity_data_point",
    "opportunity_ab_reference_link",
    "opportunity_factor_readiness",
    "opportunity_metric_slot",
    "opportunity_slot_data_point_link",
    "opportunity_score_batch",
    "opportunity_factor_score",
    "opportunity_composite_score",
    "opportunity_early_signal_aggregate",
    "opportunity_veto_status",
    "opportunity_market_reaction",
    "opportunity_entity_investment_target",
    "opportunity_target_data_point",
    "opportunity_event_ledger",
    "opportunity_audit_issue",
    "opportunity_review_queue",
    "opportunity_agent_review_log",
    "opportunity_quality_gate_result",
    "opportunity_supplement_request",
    "opportunity_handoff_package",
    "opportunity_report_section",
    "opportunity_section_evidence_link",
    "opportunity_visual_block",
    "opportunity_visual_evidence_link",
    "opportunity_navigation_index",
    "opportunity_export_job",
    "opportunity_state_transition",
    "opportunity_score_replay_record",
}


POLICY_FIELD_DEFAULTS = {
    "opportunity_source_discovery": (
        ("policy_evidence_role", "TEXT NOT NULL DEFAULT 'needs_review'"),
        ("policy_gate_verdict", "TEXT NOT NULL DEFAULT 'needs_review'"),
        ("scoring_eligibility", "TEXT NOT NULL DEFAULT 'reference_only'"),
    ),
    "opportunity_source": (
        ("policy_evidence_role", "TEXT NOT NULL DEFAULT 'core_evidence'"),
        ("policy_gate_verdict", "TEXT NOT NULL DEFAULT 'pass_core'"),
        ("scoring_eligibility", "TEXT NOT NULL DEFAULT 'core_eligible'"),
    ),
    "opportunity_claim_evidence": (
        ("policy_evidence_role", "TEXT NOT NULL DEFAULT 'core_evidence'"),
        ("policy_gate_verdict", "TEXT NOT NULL DEFAULT 'pass_core'"),
        ("scoring_eligibility", "TEXT NOT NULL DEFAULT 'core_eligible'"),
    ),
    "opportunity_data_point": (
        ("policy_evidence_role", "TEXT NOT NULL DEFAULT 'core_evidence'"),
        ("policy_gate_verdict", "TEXT NOT NULL DEFAULT 'pass_core'"),
        ("scoring_eligibility", "TEXT NOT NULL DEFAULT 'core_eligible'"),
    ),
    "opportunity_metric_slot": (
        ("policy_evidence_role", "TEXT NOT NULL DEFAULT 'core_evidence'"),
        ("policy_gate_verdict", "TEXT NOT NULL DEFAULT 'pass_core'"),
        ("scoring_eligibility", "TEXT NOT NULL DEFAULT 'core_eligible'"),
    ),
    "opportunity_event_ledger": (
        ("policy_evidence_role", "TEXT NOT NULL DEFAULT 'reference_only'"),
        ("policy_gate_verdict", "TEXT NOT NULL DEFAULT 'pass_reference'"),
        ("scoring_eligibility", "TEXT NOT NULL DEFAULT 'reference_only'"),
    ),
}

SEARCH_CHANNEL_FIELD_DEFAULTS = {
    "opportunity_search_task": (("source_channel", "TEXT NOT NULL DEFAULT 'legacy_unspecified'"),),
    "opportunity_search_log": (("source_channel", "TEXT NOT NULL DEFAULT 'legacy_unspecified'"),),
    "opportunity_source_discovery": (("source_channel", "TEXT NOT NULL DEFAULT 'legacy_unspecified'"),),
    "opportunity_source": (("source_channel", "TEXT NOT NULL DEFAULT 'legacy_unspecified'"),),
}


TARGET_RESEARCH_FIELD_DEFAULTS = (
    ("target_priority", "TEXT"),
    ("target_quality_label", "TEXT"),
    ("relative_preference", "TEXT"),
    ("confirmed_scenario_action", "TEXT"),
    ("falsified_scenario_action", "TEXT"),
    ("target_profile_markdown", "TEXT"),
    ("target_deep_research_markdown", "TEXT"),
    ("entity_relation_markdown", "TEXT"),
    ("parent_research_relation_markdown", "TEXT"),
    ("conditional_investment_recommendation", "TEXT"),
    ("financial_data_status", "TEXT"),
)

SOURCE_TRANSLATION_FIELD_DEFAULTS = (
    ("title_zh", "TEXT"),
    ("excerpt_zh", "TEXT"),
)

SOURCE_DATE_FIELD_DEFAULTS = (
    ("event_date", "TEXT"),
    ("fetch_date", "TEXT"),
    ("local_locator", "TEXT"),
)

TARGET_DATA_POINT_TRANSLATION_FIELD_DEFAULTS = (
    ("source_title_zh", "TEXT"),
    ("source_excerpt_zh", "TEXT"),
    ("source_language", "TEXT"),
)

EXCERPT_TRANSLATION_TABLES = (
    "opportunity_claim_evidence",
    "opportunity_data_point",
    "opportunity_research_data_point",
)


REQUIRED_COLUMNS = {
    "opportunity_run": {"research_question", "display_title", "evidence_policy"},
    "opportunity_search_task": {"source_channel"},
    "opportunity_search_log": {"source_channel"},
    "opportunity_source_discovery": {"source_channel"},
    "opportunity_source": {"source_channel"},
    "opportunity_run_manifest": {
        "intake_contract_version",
        "evidence_policy_version",
        "early_signal_rule_version",
        "workflow_contract_version",
        "pack_schema_version",
    },
    "opportunity_intake_contract": {
        "research_question",
        "available_materials_choice",
        "intake_material_type",
        "materials_delivery_note",
        "evidence_policy",
        "intake_contract_hash",
    },
    "opportunity_early_signal_aggregate": {
        "early_signal_score",
        "research_priority_score",
        "core_score_changed_by_overlay",
    },
    "opportunity_entity_investment_target": {
        "target_name",
        "target_type",
        "exposure_rationale",
        "research_action",
        "investment_view",
        "risk_note",
        "target_priority",
        "target_quality_label",
        "relative_preference",
        "confirmed_scenario_action",
        "falsified_scenario_action",
        "target_profile_markdown",
        "target_deep_research_markdown",
        "entity_relation_markdown",
        "parent_research_relation_markdown",
        "conditional_investment_recommendation",
        "financial_data_status",
        "link_status",
        "support_status",
    },
    "opportunity_target_data_point": {
        "run_id",
        "entity_id",
        "target_id",
        "metric_name",
        "metric_category",
        "value_text",
        "evidence_ref_uri",
        "direction",
        "credibility_weight",
        "numeric_weight",
        "direction_score",
        "weighted_contribution",
        "source_title_zh",
        "source_excerpt_zh",
        "source_language",
    },
    "opportunity_entity_research_profile": {
        "run_id",
        "entity_id",
        "entity_research_mode",
        "research_question",
        "literature_review_markdown",
        "analysis_markdown",
        "answer_markdown",
        "conclusion_markdown",
    },
    "opportunity_research_data_point": {
        "run_id",
        "entity_id",
        "data_point_title",
        "research_category",
        "metric",
        "source_excerpt",
        "source_excerpt_zh",
        "interpretation",
        "research_use",
        "evidence_ref_uri",
    },
    "opportunity_agent_review_log": {
        "review_stage",
        "reviewer_id",
        "review_kind",
        "input_artifact_hash",
        "output_artifact_hash",
        "findings_hash",
    },
    "opportunity_source": {
        "title_zh",
        "excerpt_zh",
        "event_date",
        "fetch_date",
        "local_locator",
    },
    "opportunity_claim_evidence": {"source_excerpt_zh"},
    "opportunity_data_point": {"source_excerpt_zh"},
    "opportunity_quality_gate_result": {
        "run_id",
        "gate_name",
        "gate_verdict",
        "findings_json",
        "artifact_ref_json",
        "gate_version",
        "result_hash",
    },
}


REVIEW_LOG_FIELD_DEFAULTS = (
    ("review_stage", "TEXT NOT NULL DEFAULT 'unspecified'"),
    ("reviewer_id", "TEXT"),
    ("review_kind", "TEXT NOT NULL DEFAULT 'legacy'"),
    ("input_artifact_hash", "TEXT"),
    ("output_artifact_hash", "TEXT"),
    ("findings_hash", "TEXT"),
)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> bool:
    """Add a compatibility column and report whether this call changed schema.

    The return value matters for idempotency: data backfills that belong to a
    one-time schema migration must not be replayed every time a new run pack is
    loaded.  Replaying them used to rewrite nullable version fields on historic
    browser-audit manifests even though those runs were outside the load scope.
    """
    if column not in _table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        return True
    return False


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _backfill_default_intake_contracts(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT r.id, r.question, r.research_question, r.evidence_policy
        FROM opportunity_run r
        LEFT JOIN opportunity_intake_contract c ON c.run_id=r.id
        WHERE c.id IS NULL
        ORDER BY r.id
        """
    ).fetchall()
    for row in rows:
        research_question = row["research_question"] or row["question"]
        contract = {
            "run_id": row["id"],
            "research_question": research_question,
            "available_materials_choice": "A",
            "intake_material_type": "none",
            "evidence_policy": row["evidence_policy"] or "balanced",
            "field_origin": {"research_question": "legacy_migrated"},
            "default_accepted": {"available_materials_choice": True, "evidence_policy": True},
            "migration_note": "由 V1.4 兼容迁移从旧 run.question 生成。",
            "intake_contract_version": INTAKE_CONTRACT_VERSION,
            "evidence_policy_version": EVIDENCE_POLICY_VERSION,
            "early_signal_rule_version": EARLY_SIGNAL_RULE_VERSION,
        }
        contract_hash = hash_json(contract)
        conn.execute(
            """
            INSERT INTO opportunity_intake_contract(
              run_id, research_question, available_materials_choice, intake_material_type,
              evidence_policy, time_window_json, research_scope_json,
              special_constraints_json, field_origin_json, default_accepted_json,
              parsed_intake_json, validation_issue_json, intake_contract_version,
              evidence_policy_version, early_signal_rule_version, intake_contract_hash
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                row["id"],
                research_question,
                "A",
                "none",
                row["evidence_policy"] or "balanced",
                "{}",
                "{}",
                "{}",
                _json({"research_question": "legacy_migrated"}),
                _json({"available_materials_choice": True, "evidence_policy": True}),
                _json(contract),
                "[]",
                INTAKE_CONTRACT_VERSION,
                EVIDENCE_POLICY_VERSION,
                EARLY_SIGNAL_RULE_VERSION,
                contract_hash,
            ),
        )
        conn.execute(
            """
            INSERT INTO opportunity_run_manifest(
              run_id, manifest_type, manifest_json, manifest_hash,
              intake_contract_version, evidence_policy_version, early_signal_rule_version
            ) VALUES(?,?,?,?,?,?,?)
            """,
            (
                row["id"],
                "intake_contract",
                _json(contract),
                contract_hash,
                INTAKE_CONTRACT_VERSION,
                EVIDENCE_POLICY_VERSION,
                EARLY_SIGNAL_RULE_VERSION,
            ),
        )


def _rebuild_audit_issue_constraint_if_needed(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='opportunity_audit_issue'"
    ).fetchone()
    if not row or "policy_gate_violation" in (row["sql"] or ""):
        return
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS opportunity_audit_issue_v14_new (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id INTEGER NOT NULL,
          entity_id INTEGER,
          affected_uri TEXT NOT NULL,
          audit_issue_type TEXT NOT NULL CHECK (audit_issue_type IN ('source_missing','source_rejected','source_conflict','official_vs_media_conflict','calculation_error','unit_conversion_error','period_conflict','geo_scope_conflict','capacity_definition_conflict','supplier_count_definition_conflict','duplicate_event_score','stale_data','low_coverage','low_confidence','ai_inference_only','unsupported_claim','theme_mapping_only','forecast_as_fact','cross_db_reference_stale','replay_not_reproducible','policy_gate_violation','weak_signal_core_leak','insufficient_independent_confirmation')),
          audit_severity TEXT NOT NULL CHECK (audit_severity IN ('p0','p1','p2','p3')),
          audit_issue_status TEXT NOT NULL DEFAULT 'open' CHECK (audit_issue_status IN ('open','in_review','resolved','waived','reopened')),
          issue_title TEXT NOT NULL,
          issue_detail TEXT,
          evidence_ref_uri TEXT,
          evidence_ref_uri_list_json TEXT,
          reviewer TEXT,
          waiver_reason TEXT,
          resolved_at TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
          FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE SET NULL
        )
        """
    )
    cols = [
        "id", "run_id", "entity_id", "affected_uri", "audit_issue_type",
        "audit_severity", "audit_issue_status", "issue_title", "issue_detail",
        "evidence_ref_uri", "evidence_ref_uri_list_json", "reviewer",
        "waiver_reason", "resolved_at", "created_at", "updated_at",
    ]
    col_sql = ", ".join(cols)
    conn.execute(f"INSERT INTO opportunity_audit_issue_v14_new({col_sql}) SELECT {col_sql} FROM opportunity_audit_issue")
    conn.execute("DROP TABLE opportunity_audit_issue")
    conn.execute("ALTER TABLE opportunity_audit_issue_v14_new RENAME TO opportunity_audit_issue")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_opp_audit_run_severity "
        "ON opportunity_audit_issue(run_id, audit_severity, audit_issue_status)"
    )
    conn.execute("PRAGMA foreign_keys=ON")


def _rebuild_candidate_priority_constraint_if_needed(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='opportunity_candidate_entity'"
    ).fetchone()
    if not row or "research_only_literature_review_complete" in (row["sql"] or ""):
        return
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS opportunity_candidate_entity_v15_new (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          run_id INTEGER NOT NULL,
          candidate_stage TEXT NOT NULL CHECK (candidate_stage IN ('discovered','long_list','candidate','shortlist','scoring_ready','research_only','rejected','duplicate','out_of_scope','merged_to_entity')),
          name TEXT NOT NULL,
          entity_type_hint TEXT,
          entity_id INTEGER,
          parent_candidate_id INTEGER,
          preliminary_research_priority_label TEXT CHECK (preliminary_research_priority_label IS NULL OR preliminary_research_priority_label IN ('high_priority_for_scoring','medium_priority_for_followup','low_priority_watch','research_only_insufficient_data','research_only_literature_review_complete','reject_or_out_of_scope')),
          source_count INTEGER NOT NULL DEFAULT 0,
          independent_source_count INTEGER NOT NULL DEFAULT 0,
          reason TEXT,
          evidence_ref_uri TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          FOREIGN KEY(run_id) REFERENCES opportunity_run(id) ON DELETE CASCADE,
          FOREIGN KEY(entity_id) REFERENCES opportunity_entity(id) ON DELETE SET NULL,
          FOREIGN KEY(parent_candidate_id) REFERENCES opportunity_candidate_entity(id) ON DELETE SET NULL
        )
        """
    )
    cols = [
        "id", "run_id", "candidate_stage", "name", "entity_type_hint",
        "entity_id", "parent_candidate_id", "preliminary_research_priority_label",
        "source_count", "independent_source_count", "reason", "evidence_ref_uri",
        "created_at", "updated_at",
    ]
    col_sql = ", ".join(cols)
    old_research_only_label = "research_only_" + "lit_review_complete"
    select_sql = ", ".join(
        "CASE preliminary_research_priority_label "
        f"WHEN '{old_research_only_label}' THEN 'research_only_literature_review_complete' "
        "ELSE preliminary_research_priority_label END AS preliminary_research_priority_label"
        if col == "preliminary_research_priority_label"
        else col
        for col in cols
    )
    conn.execute(
        f"INSERT INTO opportunity_candidate_entity_v15_new({col_sql}) "
        f"SELECT {select_sql} FROM opportunity_candidate_entity"
    )
    conn.execute("DROP TABLE opportunity_candidate_entity")
    conn.execute("ALTER TABLE opportunity_candidate_entity_v15_new RENAME TO opportunity_candidate_entity")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_opp_candidate_run_stage "
        "ON opportunity_candidate_entity(run_id, candidate_stage)"
    )
    conn.execute("PRAGMA foreign_keys=ON")


def apply_compatible_migrations(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "opportunity_run", "research_question", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(conn, "opportunity_run", "display_title", "TEXT")
    _add_column_if_missing(conn, "opportunity_run", "evidence_policy", "TEXT NOT NULL DEFAULT 'balanced'")
    conn.execute(
        """
        UPDATE opportunity_run
        SET research_question=question
        WHERE research_question IS NULL OR research_question=''
        """
    )
    if "opportunity_intake_contract" in table_names(conn):
        _add_column_if_missing(conn, "opportunity_intake_contract", "materials_delivery_note", "TEXT")
    conn.execute(
        """
        UPDATE opportunity_run
        SET evidence_policy='balanced'
        WHERE evidence_policy IS NULL OR evidence_policy=''
        """
    )
    manifest_columns_added: set[str] = set()
    for column in (
        "intake_contract_version",
        "evidence_policy_version",
        "early_signal_rule_version",
        "workflow_contract_version",
        "pack_schema_version",
    ):
        if _add_column_if_missing(conn, "opportunity_run_manifest", column, "TEXT"):
            manifest_columns_added.add(column)
    if manifest_columns_added & {
        "intake_contract_version",
        "evidence_policy_version",
        "early_signal_rule_version",
    }:
        conn.execute(
            """
            UPDATE opportunity_run_manifest
            SET intake_contract_version=COALESCE(intake_contract_version, ?),
                evidence_policy_version=COALESCE(evidence_policy_version, ?),
                early_signal_rule_version=COALESCE(early_signal_rule_version, ?)
            """,
            (INTAKE_CONTRACT_VERSION, EVIDENCE_POLICY_VERSION, EARLY_SIGNAL_RULE_VERSION),
        )
    if manifest_columns_added & {"workflow_contract_version", "pack_schema_version"}:
        conn.execute(
            """
            UPDATE opportunity_run_manifest
            SET workflow_contract_version=COALESCE(workflow_contract_version, ?),
                pack_schema_version=COALESCE(pack_schema_version, ?)
            """,
            (RESEARCH_WORKFLOW_CONTRACT_VERSION, "opportunity_lens.run_pack.legacy"),
        )
    for table, fields in POLICY_FIELD_DEFAULTS.items():
        if table in table_names(conn):
            for column, definition in fields:
                _add_column_if_missing(conn, table, column, definition)
    for table, fields in SEARCH_CHANNEL_FIELD_DEFAULTS.items():
        if table in table_names(conn):
            for column, definition in fields:
                _add_column_if_missing(conn, table, column, definition)
    if "opportunity_source" in table_names(conn):
        conn.execute("UPDATE opportunity_source SET source_channel='report' WHERE source_channel='legacy_unspecified' AND local_path IS NOT NULL AND trim(local_path)<>''")
        conn.execute("UPDATE opportunity_source SET source_channel='web' WHERE source_channel='legacy_unspecified' AND url IS NOT NULL AND trim(url)<>''")
    if "opportunity_entity_investment_target" in table_names(conn):
        for column, definition in TARGET_RESEARCH_FIELD_DEFAULTS:
            _add_column_if_missing(conn, "opportunity_entity_investment_target", column, definition)
    if "opportunity_source" in table_names(conn):
        for column, definition in SOURCE_TRANSLATION_FIELD_DEFAULTS:
            _add_column_if_missing(conn, "opportunity_source", column, definition)
        for column, definition in SOURCE_DATE_FIELD_DEFAULTS:
            _add_column_if_missing(conn, "opportunity_source", column, definition)
    if "opportunity_target_data_point" in table_names(conn):
        for column, definition in TARGET_DATA_POINT_TRANSLATION_FIELD_DEFAULTS:
            _add_column_if_missing(conn, "opportunity_target_data_point", column, definition)
    for table in EXCERPT_TRANSLATION_TABLES:
        if table in table_names(conn):
            _add_column_if_missing(conn, table, "source_excerpt_zh", "TEXT")
    if "opportunity_agent_review_log" in table_names(conn):
        for column, definition in REVIEW_LOG_FIELD_DEFAULTS:
            _add_column_if_missing(conn, "opportunity_agent_review_log", column, definition)
    _rebuild_candidate_priority_constraint_if_needed(conn)
    _rebuild_audit_issue_constraint_if_needed(conn)
    _backfill_default_intake_contracts(conn)


def apply_pre_schema_column_migrations(conn: sqlite3.Connection) -> None:
    """旧库执行 schema.sql 之前先补索引依赖列。"""
    existing = set(table_names(conn))
    if "opportunity_run" in existing:
        _add_column_if_missing(conn, "opportunity_run", "research_question", "TEXT NOT NULL DEFAULT ''")
        _add_column_if_missing(conn, "opportunity_run", "display_title", "TEXT")
        _add_column_if_missing(conn, "opportunity_run", "evidence_policy", "TEXT NOT NULL DEFAULT 'balanced'")
    if "opportunity_run_manifest" in existing:
        for column in (
            "intake_contract_version",
            "evidence_policy_version",
            "early_signal_rule_version",
            "workflow_contract_version",
            "pack_schema_version",
        ):
            _add_column_if_missing(conn, "opportunity_run_manifest", column, "TEXT")
    if "opportunity_intake_contract" in existing:
        _add_column_if_missing(conn, "opportunity_intake_contract", "materials_delivery_note", "TEXT")
    for table, fields in POLICY_FIELD_DEFAULTS.items():
        if table in existing:
            for column, definition in fields:
                _add_column_if_missing(conn, table, column, definition)
    for table, fields in SEARCH_CHANNEL_FIELD_DEFAULTS.items():
        if table in existing:
            for column, definition in fields:
                _add_column_if_missing(conn, table, column, definition)
    if "opportunity_entity_investment_target" in existing:
        for column, definition in TARGET_RESEARCH_FIELD_DEFAULTS:
            _add_column_if_missing(conn, "opportunity_entity_investment_target", column, definition)
    if "opportunity_source" in existing:
        for column, definition in SOURCE_TRANSLATION_FIELD_DEFAULTS:
            _add_column_if_missing(conn, "opportunity_source", column, definition)
        for column, definition in SOURCE_DATE_FIELD_DEFAULTS:
            _add_column_if_missing(conn, "opportunity_source", column, definition)
    if "opportunity_target_data_point" in existing:
        for column, definition in TARGET_DATA_POINT_TRANSLATION_FIELD_DEFAULTS:
            _add_column_if_missing(conn, "opportunity_target_data_point", column, definition)
    for table in EXCERPT_TRANSLATION_TABLES:
        if table in existing:
            _add_column_if_missing(conn, table, "source_excerpt_zh", "TEXT")
    if "opportunity_agent_review_log" in existing:
        for column, definition in REVIEW_LOG_FIELD_DEFAULTS:
            _add_column_if_missing(conn, "opportunity_agent_review_log", column, definition)


def init_db(db_path: str | Path = DB_PATH, reset: bool = False) -> Path:
    path = Path(db_path)
    if reset and path.exists():
        if path.name != "opportunity_lens.db" and "opportunity_lens" not in str(path):
            raise RuntimeError(f"拒绝重置非本模块 DB：{path}")
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        apply_pre_schema_column_migrations(conn)
        execute_schema(conn)
        apply_compatible_migrations(conn)
        for key, value in VERSION_BUNDLE.items():
            conn.execute(
                "INSERT INTO opportunity_schema_meta(key, value, updated_at) "
                "VALUES(?,?,datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=datetime('now')",
                (key, value),
            )
        conn.commit()
        verify_schema(conn)
    finally:
        conn.close()
    return path


def verify_schema(conn: sqlite3.Connection) -> None:
    existing = set(table_names(conn))
    missing = sorted(REQUIRED_TABLES - existing)
    if missing:
        raise RuntimeError(f"缺少机会透镜数据表：{missing}")
    missing_columns: dict[str, list[str]] = {}
    for table, expected in REQUIRED_COLUMNS.items():
        cols = _table_columns(conn, table)
        absent = sorted(expected - cols)
        if absent:
            missing_columns[table] = absent
    for table, fields in POLICY_FIELD_DEFAULTS.items():
        if table in existing:
            cols = _table_columns(conn, table)
            absent = sorted(column for column, _definition in fields if column not in cols)
            if absent:
                missing_columns[table] = absent
    if missing_columns:
        raise RuntimeError(f"机会透镜关键字段缺失：{missing_columns}")
    row = conn.execute(
        "SELECT value FROM opportunity_schema_meta WHERE key='schema_version'"
    ).fetchone()
    if not row or row["value"] != SCHEMA_VERSION:
        raise RuntimeError("schema_version 元数据缺失或无效")
    fk_errors = list(conn.execute("PRAGMA foreign_key_check"))
    if fk_errors:
        raise RuntimeError(f"外键检查失败：{fk_errors[:3]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    path = init_db(args.db, reset=args.reset)
    print(f"机会透镜 DB 已就绪：{path}")


if __name__ == "__main__":
    main()
