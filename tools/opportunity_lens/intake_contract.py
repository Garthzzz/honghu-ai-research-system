from __future__ import annotations

import json
import sqlite3
from typing import Any

from .constants import (
    EARLY_SIGNAL_RULE_VERSION,
    EVIDENCE_POLICY_VERSION,
    INTAKE_CONTRACT_VERSION,
    RESEARCH_WORKFLOW_CONTRACT_VERSION,
    RUN_PACK_SCHEMA_VERSION,
)
from .score_trace import hash_json
from .validators import validate_enum

MATERIAL_CHOICE_TO_TYPE = {
    "A": "none",
    "B": "papers_folder",
    "C": "research_db_reference",
}


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def normalize_available_materials_choice(value: str | None) -> str:
    if value is None or str(value).strip() == "":
        return "A"
    normalized = str(value).strip().upper()
    if normalized not in MATERIAL_CHOICE_TO_TYPE:
        raise ValueError("available_materials_choice 必须是 A、B、C 之一")
    return normalized


def material_type_from_choice(choice: str) -> str:
    normalized = normalize_available_materials_choice(choice)
    return validate_enum("intake_material_type", MATERIAL_CHOICE_TO_TYPE[normalized])


def normalize_evidence_policy(value: str | None) -> str:
    return validate_enum("evidence_policy", value or "balanced")


def default_intake_for_question(research_question: str, evidence_policy: str = "balanced") -> dict[str, Any]:
    return {
        "research_question": research_question,
        "available_materials_choice": "A",
        "intake_material_type": "none",
        "evidence_policy": evidence_policy,
        "time_window": {},
        "research_scope": {},
        "special_constraints": {},
        "field_origin": {
            "research_question": "user_provided",
            "available_materials_choice": "default_accepted",
            "evidence_policy": "default_accepted" if evidence_policy == "balanced" else "user_provided",
        },
        "default_accepted": {
            "available_materials_choice": True,
            "evidence_policy": evidence_policy == "balanced",
        },
        "validation_issues": [],
    }


def canonical_contract_payload(payload: dict[str, Any]) -> dict[str, Any]:
    choice = normalize_available_materials_choice(payload.get("available_materials_choice"))
    expected_material_type = material_type_from_choice(choice)
    material_type = payload.get("intake_material_type") or expected_material_type
    material_type = validate_enum("intake_material_type", material_type)
    if material_type != expected_material_type:
        raise ValueError(
            f"intake_material_type={material_type!r} 与 available_materials_choice={choice!r} 不一致；"
            f"应为 {expected_material_type!r}"
        )
    policy = normalize_evidence_policy(payload.get("evidence_policy"))
    research_question = str(payload.get("research_question") or "").strip()
    if not research_question:
        raise ValueError("research_question 不能为空")
    contract = {
        "research_question": research_question,
        "available_materials_choice": choice,
        "intake_material_type": material_type,
        "papers_or_report_folder": payload.get("papers_or_report_folder"),
        "materials_delivery_note": payload.get("materials_delivery_note"),
        "reference_industry_in_research_db": payload.get("reference_industry_in_research_db"),
        "evidence_policy": policy,
        "time_window": dict(payload.get("time_window") or {}),
        "research_scope": dict(payload.get("research_scope") or {}),
        "special_constraints": dict(payload.get("special_constraints") or {}),
        "field_origin": dict(payload.get("field_origin") or {}),
        "default_accepted": dict(payload.get("default_accepted") or {}),
        "validation_issues": list(payload.get("validation_issues") or []),
        "intake_contract_version": INTAKE_CONTRACT_VERSION,
        "evidence_policy_version": EVIDENCE_POLICY_VERSION,
        "early_signal_rule_version": EARLY_SIGNAL_RULE_VERSION,
    }
    if choice == "B" and not (contract["papers_or_report_folder"] or contract["materials_delivery_note"]):
        contract["validation_issues"].append("选择 B 时应提供共享资料路径或资料包交付说明")
    if choice == "C" and not contract["reference_industry_in_research_db"]:
        contract["validation_issues"].append("选择 C 时应提供 reference_industry_in_research_db")
    return contract


def save_intake_contract(
    conn: sqlite3.Connection,
    run_id: int,
    payload: dict[str, Any],
    *,
    raw_payload: dict[str, Any] | None = None,
    raw_intake_text: str | None = None,
) -> int:
    contract = canonical_contract_payload(payload)
    contract_hash = hash_json(contract)
    row_id = int(
        conn.execute(
            """
            INSERT INTO opportunity_intake_contract(
              run_id, research_question, available_materials_choice, intake_material_type,
              papers_or_report_folder, reference_industry_in_research_db, evidence_policy,
              materials_delivery_note,
              time_window_json, research_scope_json, special_constraints_json,
              field_origin_json, default_accepted_json, parsed_intake_json,
              validation_issue_json, raw_intake_text, raw_payload_json,
              intake_contract_version, evidence_policy_version, early_signal_rule_version,
              intake_contract_hash
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id) DO UPDATE SET
              research_question=excluded.research_question,
              available_materials_choice=excluded.available_materials_choice,
              intake_material_type=excluded.intake_material_type,
              papers_or_report_folder=excluded.papers_or_report_folder,
              materials_delivery_note=excluded.materials_delivery_note,
              reference_industry_in_research_db=excluded.reference_industry_in_research_db,
              evidence_policy=excluded.evidence_policy,
              time_window_json=excluded.time_window_json,
              research_scope_json=excluded.research_scope_json,
              special_constraints_json=excluded.special_constraints_json,
              field_origin_json=excluded.field_origin_json,
              default_accepted_json=excluded.default_accepted_json,
              parsed_intake_json=excluded.parsed_intake_json,
              validation_issue_json=excluded.validation_issue_json,
              raw_intake_text=excluded.raw_intake_text,
              raw_payload_json=excluded.raw_payload_json,
              intake_contract_version=excluded.intake_contract_version,
              evidence_policy_version=excluded.evidence_policy_version,
              early_signal_rule_version=excluded.early_signal_rule_version,
              intake_contract_hash=excluded.intake_contract_hash,
              updated_at=datetime('now')
            """,
            (
                run_id,
                contract["research_question"],
                contract["available_materials_choice"],
                contract["intake_material_type"],
                contract["papers_or_report_folder"],
                contract["reference_industry_in_research_db"],
                contract["evidence_policy"],
                contract["materials_delivery_note"],
                _json(contract["time_window"]),
                _json(contract["research_scope"]),
                _json(contract["special_constraints"]),
                _json(contract["field_origin"]),
                _json(contract["default_accepted"]),
                _json(contract),
                _json(contract["validation_issues"]),
                raw_intake_text,
                _json(raw_payload or payload),
                INTAKE_CONTRACT_VERSION,
                EVIDENCE_POLICY_VERSION,
                EARLY_SIGNAL_RULE_VERSION,
                contract_hash,
            ),
        ).lastrowid
    )
    row = conn.execute("SELECT id FROM opportunity_intake_contract WHERE run_id=?", (run_id,)).fetchone()
    intake_id = int(row["id"] if row else row_id)
    conn.execute(
        """
        UPDATE opportunity_run
        SET question=?, research_question=?, evidence_policy=?, updated_at=datetime('now')
        WHERE id=?
        """,
        (contract["research_question"], contract["research_question"], contract["evidence_policy"], run_id),
    )
    conn.execute(
        """
        INSERT INTO opportunity_run_manifest(
          run_id, manifest_type, manifest_json, manifest_hash,
          intake_contract_version, evidence_policy_version, early_signal_rule_version,
          workflow_contract_version, pack_schema_version
        ) VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id,
            "intake_contract",
            _json(contract),
            contract_hash,
            INTAKE_CONTRACT_VERSION,
            EVIDENCE_POLICY_VERSION,
            EARLY_SIGNAL_RULE_VERSION,
            RESEARCH_WORKFLOW_CONTRACT_VERSION,
            RUN_PACK_SCHEMA_VERSION,
        ),
    )
    return intake_id


def require_valid_intake_contract(conn: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM opportunity_intake_contract WHERE run_id=?",
        (run_id,),
    ).fetchone()
    if not row:
        raise ValueError("进入 intake_validated 前必须先保存 intake contract")
    issues = json.loads(row["validation_issue_json"] or "[]")
    if issues:
        raise ValueError("intake contract 仍有未解决校验问题：" + "；".join(str(item) for item in issues))
    return {key: row[key] for key in row.keys()}
