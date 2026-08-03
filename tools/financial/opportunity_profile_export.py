from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .accounting_sanity import annual_roe_sanity_reasons
from .constants import DB_PATH, FACT_TYPES, ROOT, SOURCE_CHANNELS
from .db import connect, transaction, verify_database
from .repository import (
    ALLOWED_BENCHMARK_TYPES,
    create_model_run,
    finalize_reviewed_model,
    freeze_independent_model,
    record_external_reconciliation,
    record_model_inputs,
    record_model_outputs,
    record_source_snapshot,
    upsert_observation,
    upsert_security,
)


EXPORT_SCHEMA_VERSION = "company_financial_profile_export.v1"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _required_text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} 不能为空")
    return text


def _resolve_artifact_path(raw: str, *, export_path: Path) -> Path:
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate.resolve()
    project_candidate = (ROOT / candidate).resolve()
    if project_candidate.is_file():
        return project_candidate
    return (export_path.parent / candidate).resolve()


def validate_export(payload: Mapping[str, Any], *, export_path: Path) -> dict[str, Any]:
    if payload.get("export_schema_version") != EXPORT_SCHEMA_VERSION:
        raise ValueError(
            f"不支持的 export_schema_version: {payload.get('export_schema_version')!r}"
        )
    research_run_ref = _required_text(payload.get("research_run_ref"), "research_run_ref")
    _required_text(payload.get("as_of_date"), "as_of_date")
    artifacts = list(payload.get("source_artifacts") or [])
    companies = list(payload.get("companies") or [])
    if not artifacts:
        raise ValueError("source_artifacts 不能为空")
    if not companies:
        raise ValueError("companies 不能为空")

    artifact_results: list[dict[str, Any]] = []
    for index, artifact in enumerate(artifacts):
        path = _resolve_artifact_path(
            _required_text(artifact.get("path"), f"source_artifacts[{index}].path"),
            export_path=export_path,
        )
        expected = _required_text(
            artifact.get("sha256"), f"source_artifacts[{index}].sha256"
        )
        if not path.is_file():
            raise FileNotFoundError(f"模型来源文件不存在: {path}")
        actual = _sha256_file(path)
        if actual != expected:
            raise ValueError(f"模型来源哈希不一致: {path} expected={expected} actual={actual}")
        artifact_results.append({"path": str(path), "sha256": actual})

    run_keys: set[str] = set()
    company_ids: set[int] = set()
    for company_index, company in enumerate(companies):
        research_company_id = int(company["research_company_id"])
        if research_company_id in company_ids:
            raise ValueError(f"research_company_id 重复: {research_company_id}")
        company_ids.add(research_company_id)
        security = dict(company.get("security") or {})
        _required_text(security.get("canonical_name"), "security.canonical_name")
        _required_text(security.get("ticker"), "security.ticker")
        snapshots = list(company.get("source_snapshots") or [])
        snapshot_keys = {
            _required_text(item.get("key"), "source_snapshot.key") for item in snapshots
        }
        if len(snapshot_keys) != len(snapshots):
            raise ValueError(f"公司 {research_company_id} 的 source_snapshot.key 重复")

        for snapshot in snapshots:
            source_channel = _required_text(
                snapshot.get("source_channel"), "source_snapshot.source_channel"
            )
            if source_channel not in SOURCE_CHANNELS:
                raise ValueError(f"非法 source_channel: {source_channel}")
            _required_text(snapshot.get("provider"), "source_snapshot.provider")
            _required_text(snapshot.get("source_ref"), "source_snapshot.source_ref")
            _required_text(snapshot.get("title"), "source_snapshot.title")

        local_model_keys: set[str] = set()
        for model in list(company.get("model_runs") or []):
            run_key = _required_text(model.get("run_key"), "model_run.run_key")
            if run_key in run_keys:
                raise ValueError(f"run_key 重复: {run_key}")
            run_keys.add(run_key)
            local_model_keys.add(run_key)
            if model.get("finalization") not in {"independent", "reviewed"}:
                raise ValueError(f"模型 {run_key} 的 finalization 非法")
            if not model.get("inputs") or not model.get("outputs"):
                raise ValueError(f"模型 {run_key} 必须同时提供 inputs 和 outputs")
            if model.get("finalization") == "reviewed" and model.get("reconciliations"):
                raise ValueError(
                    f"模型 {run_key} 是 reviewed 诊断/参考模型，不能登记要求"
                    "独立冻结顺序的外部对账；应把市场数据作为输入或单独建立"
                    "市场隐含诊断模型"
                )
        observations = list(company.get("observations") or [])
        for observation in observations:
            metric_name = _required_text(
                observation.get("metric_name"), "observation.metric_name"
            )
            _required_text(observation.get("unit"), "observation.unit")
            provider = _required_text(
                observation.get("provider"), "observation.provider"
            )
            fact_type = _required_text(
                observation.get("fact_type"), "observation.fact_type"
            )
            if fact_type not in FACT_TYPES:
                raise ValueError(f"非法 fact_type: {fact_type}")
            value_num = observation.get("value_num")
            value_text = str(observation.get("value_text") or "").strip()
            if (
                value_num is None
                and not value_text
                and observation.get("quality_status") != "not_applicable"
            ):
                raise ValueError(
                    f"观察值 {metric_name} 的数值和文本不能同时为空"
                )
            if (
                provider == "internal_model"
                and value_num is not None
                and not str(observation.get("formula") or "").strip()
            ):
                raise ValueError("内部模型观察值必须保存公式")
            snapshot_key = observation.get("source_snapshot_key")
            model_key = observation.get("model_run_key")
            if snapshot_key and snapshot_key not in snapshot_keys:
                raise ValueError(f"观察值引用了不存在的 source_snapshot_key: {snapshot_key}")
            if model_key and model_key not in local_model_keys:
                raise ValueError(f"观察值引用了不存在的 model_run_key: {model_key}")
        invalid_roe_years = annual_roe_sanity_reasons(observations)
        for observation in observations:
            try:
                year = int(observation.get("fiscal_year"))
            except (TypeError, ValueError):
                continue
            if (
                observation.get("metric_name") == "roe"
                and year in invalid_roe_years
                and observation.get("quality_status")
                not in {"not_applicable", "superseded"}
            ):
                raise ValueError(
                    f"公司 {research_company_id} 的 {year} 年ROE分母不具经济意义，"
                    f"必须标记 not_applicable：{invalid_roe_years[year]}"
                )
        for model in list(company.get("model_runs") or []):
            for reconciliation in list(model.get("reconciliations") or []):
                if reconciliation.get("benchmark_type") not in ALLOWED_BENCHMARK_TYPES:
                    raise ValueError(
                        f"非法 benchmark_type: {reconciliation.get('benchmark_type')}"
                    )
                _required_text(
                    reconciliation.get("benchmark_source_ref"),
                    "reconciliation.benchmark_source_ref",
                )

    return {
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "research_run_ref": research_run_ref,
        "artifact_count": len(artifact_results),
        "company_count": len(companies),
        "model_run_count": len(run_keys),
        "artifacts": artifact_results,
    }


def _existing_model(conn: Any, run_key: str) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT id,security_id,research_run_ref,skill_name,model_name,model_role
             FROM financial_model_run WHERE run_key=?""",
        (run_key,),
    ).fetchone()
    return dict(row) if row else None


def import_export(
    payload: Mapping[str, Any],
    *,
    export_path: Path,
    db_path: str | Path = DB_PATH,
) -> dict[str, Any]:
    validation = validate_export(payload, export_path=export_path)
    conn = connect(db_path)
    summary = {
        **validation,
        "database": str(Path(db_path).resolve()),
        "source_snapshots": 0,
        "models_inserted": 0,
        "models_reused": 0,
        "models_superseded": 0,
        "observations_inserted": 0,
        "observations_revised": 0,
        "observations_unchanged": 0,
        "reconciliations_recorded": 0,
    }
    try:
        with transaction(conn):
            for company in payload["companies"]:
                security_spec = dict(company["security"])
                security_id = upsert_security(
                    conn,
                    research_company_id=int(company["research_company_id"]),
                    canonical_name=security_spec["canonical_name"],
                    ticker=security_spec.get("ticker"),
                    market=security_spec.get("market"),
                    listing_status=security_spec.get("listing_status"),
                    reporting_currency=security_spec.get("reporting_currency"),
                    name_en=security_spec.get("name_en"),
                    identity_status=security_spec.get("identity_status", "verified"),
                )
                snapshot_ids: dict[str, int] = {}
                for snapshot in company.get("source_snapshots") or []:
                    snapshot_ids[str(snapshot["key"])] = record_source_snapshot(
                        conn,
                        provider=snapshot["provider"],
                        source_channel=snapshot["source_channel"],
                        source_ref=snapshot["source_ref"],
                        title=snapshot["title"],
                        publisher=snapshot.get("publisher"),
                        as_of_date=snapshot.get("as_of_date"),
                        fetched_at=snapshot.get("fetched_at"),
                        content_hash=snapshot.get("content_hash"),
                        raw_snapshot_path=snapshot.get("raw_snapshot_path"),
                        metadata=snapshot.get("metadata"),
                    )
                    summary["source_snapshots"] += 1

                model_ids: dict[str, int] = {}
                for model in company.get("model_runs") or []:
                    run_key = str(model["run_key"])
                    existing = _existing_model(conn, run_key)
                    if existing is not None:
                        expected_identity = (
                            security_id,
                            str(payload["research_run_ref"]),
                            str(model["skill_name"]),
                            str(model["model_name"]),
                            str(model["model_role"]),
                        )
                        actual_identity = (
                            int(existing["security_id"]),
                            str(existing["research_run_ref"]),
                            str(existing["skill_name"]),
                            str(existing["model_name"]),
                            str(existing["model_role"]),
                        )
                        if actual_identity != expected_identity:
                            raise ValueError(
                                f"run_key 已被不同模型占用: {run_key} "
                                f"expected={expected_identity!r} actual={actual_identity!r}"
                            )
                        model_ids[run_key] = int(existing["id"])
                        summary["models_reused"] += 1
                        continue
                    model_id = create_model_run(
                        conn,
                        run_key=run_key,
                        security_id=security_id,
                        research_run_ref=payload["research_run_ref"],
                        skill_name=model["skill_name"],
                        model_name=model["model_name"],
                        model_role=model["model_role"],
                        forecast_start=model.get("forecast_start"),
                        forecast_end=model.get("forecast_end"),
                        valuation_date=model.get("valuation_date"),
                        assumptions=model.get("assumptions"),
                        limitations=model.get("limitations"),
                    )
                    record_model_inputs(conn, model_id, model["inputs"])
                    record_model_outputs(conn, model_id, model["outputs"])
                    if model["finalization"] == "independent":
                        freeze_independent_model(conn, model_id)
                    else:
                        finalize_reviewed_model(conn, model_id)
                    for superseded_key in model.get("supersedes_run_keys") or []:
                        changed = conn.execute(
                            """UPDATE financial_model_run
                                  SET status='superseded',updated_at=datetime('now')
                                WHERE run_key=? AND security_id=? AND id<>?
                                  AND status<>'superseded'""",
                            (str(superseded_key), security_id, model_id),
                        ).rowcount
                        summary["models_superseded"] += int(changed or 0)
                        if changed:
                            conn.execute(
                                """UPDATE financial_observation
                                      SET quality_status='superseded',
                                          updated_at=datetime('now')
                                    WHERE model_run_id IN (
                                      SELECT id FROM financial_model_run
                                       WHERE run_key=? AND security_id=? AND id<>?
                                    )""",
                                (str(superseded_key), security_id, model_id),
                            )
                    for reconciliation in model.get("reconciliations") or []:
                        record_external_reconciliation(
                            conn,
                            model_id,
                            benchmark_type=reconciliation["benchmark_type"],
                            benchmark_source_ref=reconciliation["benchmark_source_ref"],
                            metric_name=reconciliation["metric_name"],
                            period=reconciliation["period"],
                            independent_value=reconciliation.get("independent_value"),
                            benchmark_value=reconciliation.get("benchmark_value"),
                            unit=reconciliation["unit"],
                            decomposition=reconciliation.get("decomposition"),
                            conclusion=reconciliation["conclusion"],
                        )
                        summary["reconciliations_recorded"] += 1
                    model_ids[run_key] = model_id
                    summary["models_inserted"] += 1

                for observation in company.get("observations") or []:
                    row = dict(observation)
                    snapshot_key = row.pop("source_snapshot_key", None)
                    model_key = row.pop("model_run_key", None)
                    row["security_id"] = security_id
                    if snapshot_key:
                        row["source_snapshot_id"] = snapshot_ids[str(snapshot_key)]
                    if model_key:
                        row["model_run_id"] = model_ids[str(model_key)]
                    _, status = upsert_observation(
                        conn,
                        return_status=True,
                        revision_reason=f"{payload['research_run_ref']}:profile_export_refresh",
                        **row,
                    )
                    summary[f"observations_{status}"] += 1
        verify_database(db_path)
        return summary
    finally:
        conn.close()


def load_export(path: str | Path) -> tuple[Path, dict[str, Any]]:
    export_path = Path(path).resolve()
    payload = json.loads(export_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("公司财务画像导出必须是 JSON object")
    return export_path, payload


def main() -> None:
    parser = argparse.ArgumentParser(description="校验或导入 Opportunity Lens 公司财务画像")
    parser.add_argument("export_json")
    parser.add_argument("--db", default=str(DB_PATH))
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    export_path, payload = load_export(args.export_json)
    if args.validate_only:
        result = validate_export(payload, export_path=export_path)
    else:
        result = import_export(payload, export_path=export_path, db_path=args.db)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
