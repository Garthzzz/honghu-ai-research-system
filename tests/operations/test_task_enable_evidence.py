from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tools.operations.task_enable_evidence import (
    TaskEnableEvidenceError,
    _normalized_text_sha256,
    verify_local_disabled_evidence,
    verify_valuation_setup_evidence,
)
from tools.operations.task_manifest import load_task_manifest


ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "config/operations/production_tasks.json"
COLLECTOR = ROOT / "tools/operations/Collect-LocalDisabledTaskEvidence.ps1"
NOW = datetime(2026, 8, 17, 1, 0, tzinfo=timezone.utc)


def _payload() -> dict[str, object]:
    manifest = load_task_manifest(MANIFEST_PATH)
    tasks = [
        {
            "task_id": task_id,
            "present": True,
            "enabled": False,
            "state": "Disabled",
            "principal": definition.legacy_principal,
            "definition_sha256": definition.legacy_definition_sha256,
            "expected_definition_sha256": definition.legacy_definition_sha256,
            "definition_matches_manifest": True,
        }
        for task_id, definition in manifest.tasks.items()
    ]
    return {
        "schema_version": "honghu.local_task_disabled_evidence.v2",
        "checked_at": (NOW - timedelta(seconds=30)).isoformat(),
        "source_host": manifest.legacy_runner_host,
        "source_host_identity_sha256": manifest.legacy_runner_host_identity_sha256,
        "machine_guid_recorded": False,
        "manifest_sha256": manifest.sha256,
        "collector_sha256": _normalized_text_sha256(COLLECTOR),
        "tasks": tasks,
        "all_present": True,
        "all_disabled": True,
        "all_definitions_match": True,
        "legacy_runner_process_count": 0,
        "legacy_runner_processes": [],
        "secrets_recorded": False,
    }


def _verify(tmp_path: Path, payload: dict[str, object]) -> dict[str, object]:
    path = tmp_path / "local-disabled.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return verify_local_disabled_evidence(
        load_task_manifest(MANIFEST_PATH), path, collector_path=COLLECTOR, now=NOW
    )


def test_complete_fresh_local_disabled_evidence_passes(tmp_path: Path) -> None:
    result = _verify(tmp_path, _payload())
    assert result["verified"] is True
    assert result["task_count"] == 10
    assert result["legacy_runner_process_count"] == 0


def test_powershell_seven_digit_checked_at_passes(tmp_path: Path) -> None:
    payload = _payload()
    payload["checked_at"] = "2026-08-17T00:59:30.1234567+00:00"
    assert _verify(tmp_path, payload)["verified"] is True


def test_collector_identity_is_stable_across_lf_and_crlf(tmp_path: Path) -> None:
    lf = tmp_path / "lf.ps1"
    crlf = tmp_path / "crlf.ps1"
    lf.write_bytes(b"one\ntwo\n")
    crlf.write_bytes(b"one\r\ntwo\r\n")
    assert _normalized_text_sha256(lf) == _normalized_text_sha256(crlf)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda data: data.update(schema_version="honghu.local_task_disabled_evidence.v1"),
        lambda data: data.update(checked_at=(NOW - timedelta(hours=2)).isoformat()),
        lambda data: data.update(source_host="FORGED"),
        lambda data: data.update(source_host_identity_sha256="0" * 64),
        lambda data: data.update(manifest_sha256="0" * 64),
        lambda data: data.update(collector_sha256="0" * 64),
        lambda data: data["tasks"].pop(),
        lambda data: data["tasks"][0].update(enabled=True),
        lambda data: data["tasks"][0].update(definition_sha256="0" * 64),
        lambda data: data.update(legacy_runner_process_count=1),
        lambda data: data.update(legacy_runner_processes=[{"pid": 123}]),
        lambda data: data.pop("all_definitions_match"),
    ],
)
def test_old_forged_or_incomplete_evidence_fails_closed(
    tmp_path: Path, mutator
) -> None:
    payload = copy.deepcopy(_payload())
    mutator(payload)
    with pytest.raises(TaskEnableEvidenceError):
        _verify(tmp_path, payload)


def _valuation_setup_payload() -> dict[str, object]:
    contracts = [
        ("紫金矿业", "601899.SH", "上海", "铜资源", "15379", "CNY"),
        ("洛阳钼业", "603993.SH", "上海", "铜资源", "4787", "CNY"),
        ("五矿资源", "1208.HK", "香港", "铜资源", "1085", "HKD"),
        ("藏格矿业", "000408.SZ", "深圳", "铜资源", "1197", "CNY"),
        ("锡业股份", "000960.SZ", "深圳", "锡", "538", "CNY"),
        ("华锡有色", "600301.SH", "上海", "锡", "294", "CNY"),
        ("兴业银锡", "000426.SZ", "深圳", "锡", "958", "CNY"),
    ]
    return {
        "schema_version": "honghu.valuation_tracker.production_setup_evidence.v1",
        "status": "pass",
        "contract_verified": True,
        "migration_id": "0021_valuation_tracker",
        "migration_sha256": "1" * 64,
        "workbook_sha256": "453ded4b67ad53848ffd90ab27ddcad21ba3262d623e3946de613c414091e3e0",
        "workbook_seed_sha256": "09907358d4e3ee9751e7196fcd9f27574553b434915bce38af3d7c4175f19e41",
        "identity_seed_sha256": "a0f27b5ffd30bda0eddaeb2f39ef6a0e49e98ad9a618f49f378003e4d874fa8f",
        "members": [
            {
                "company_id": 100 + order,
                "security_id": 200 + order,
                "researcher_version_id": 300 + order,
                "display_order": order,
                "name": values[0],
                "ticker": values[1],
                "market": values[2],
                "board": values[3],
                "ceiling_value": values[4],
                "currency": values[5],
            }
            for order, values in enumerate(contracts, start=1)
        ],
    }


def test_exact_valuation_setup_evidence_is_required_and_verified(tmp_path: Path) -> None:
    path = tmp_path / "setup.json"
    path.write_text(json.dumps(_valuation_setup_payload(), ensure_ascii=False), encoding="utf-8")
    assert verify_valuation_setup_evidence(path)["member_count"] == 7


@pytest.mark.parametrize(
    "mutator",
    [
        lambda data: data.update(contract_verified=False),
        lambda data: data.update(workbook_seed_sha256="0" * 64),
        lambda data: data["members"][0].update(ticker="601889.SH"),
        lambda data: data["members"][1].update(display_order=1),
        lambda data: data["members"][2].update(currency="CNY"),
        lambda data: data["members"].pop(),
    ],
)
def test_valuation_setup_evidence_drift_fails_closed(tmp_path: Path, mutator) -> None:
    payload = _valuation_setup_payload()
    mutator(payload)
    path = tmp_path / "setup.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(TaskEnableEvidenceError):
        verify_valuation_setup_evidence(path)
