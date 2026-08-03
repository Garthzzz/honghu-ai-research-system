from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping

from .constants import FACT_TYPES, MODEL_SKILLS, SOURCE_CHANNELS


ALLOWED_BENCHMARK_TYPES = {
    "consensus",
    "guidance",
    "market_implied",
    "peer",
    "historical",
    "sell_side_report",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _table(name: str, schema: str | None = None) -> str:
    """Return a safely-qualified table name for ATTACH-based atomic writes."""
    if not schema:
        return name
    if not str(schema).replace("_", "").isalnum():
        raise ValueError(f"非法 SQLite schema: {schema!r}")
    return f'"{schema}".{name}'


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _iso_date(value: Any, *, required: bool = False) -> str | None:
    raw = str(value or "").strip()[:10]
    if not raw:
        if required:
            raise ValueError("日期不能为空")
        return None
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError as exc:
        raise ValueError(f"非法 ISO 日期: {value!r}") from exc


def upsert_security(
    conn: sqlite3.Connection,
    *,
    research_company_id: int | None,
    canonical_name: str,
    ticker: str | None = None,
    market: str | None = None,
    listing_status: str | None = None,
    reporting_currency: str | None = None,
    name_en: str | None = None,
    identity_status: str = "verified",
    schema: str | None = None,
) -> int:
    name = str(canonical_name or "").strip()
    if not name:
        raise ValueError("canonical_name 不能为空")
    existing = None
    if research_company_id is not None:
        existing = conn.execute(
            f"""SELECT s.id FROM {_table('financial_security_company_link', schema)} l
                  JOIN {_table('financial_security', schema)} s ON s.id=l.security_id
                 WHERE l.research_company_id=?""",
            (int(research_company_id),),
        ).fetchone()
    if existing is None and research_company_id is not None:
        existing = conn.execute(
            f"SELECT id FROM {_table('financial_security', schema)} WHERE research_company_id=?",
            (int(research_company_id),),
        ).fetchone()
    if existing is None and ticker:
        existing = conn.execute(
            f"SELECT id FROM {_table('financial_security', schema)} WHERE market IS ? AND upper(ticker)=upper(?)",
            (market, str(ticker).strip()),
        ).fetchone()
    if existing:
        security_id = int(existing[0])
        conn.execute(
            f"""UPDATE {_table('financial_security', schema)} SET research_company_id=COALESCE(research_company_id,?),
                   canonical_name=CASE WHEN research_company_id IS NULL OR research_company_id=? THEN ? ELSE canonical_name END,
                   name_en=COALESCE(name_en,?),ticker=COALESCE(ticker,?),
                   market=COALESCE(?,market),listing_status=COALESCE(?,listing_status),
                   reporting_currency=COALESCE(?,reporting_currency),identity_status=?,updated_at=datetime('now')
               WHERE id=?""",
            (research_company_id, research_company_id, name, name_en, ticker, market, listing_status,
             reporting_currency, identity_status, security_id),
        )
        if research_company_id is not None:
            conn.execute(
                f"""INSERT INTO {_table('financial_security_company_link', schema)}(
                       research_company_id,security_id,link_role) VALUES(?,?,'canonical_or_alias')
                     ON CONFLICT(research_company_id) DO UPDATE SET
                       security_id=excluded.security_id,updated_at=datetime('now')""",
                (int(research_company_id), security_id),
            )
        return security_id
    security_id = int(conn.execute(
        f"""INSERT INTO {_table('financial_security', schema)}(
             research_company_id,canonical_name,name_en,ticker,market,listing_status,
             reporting_currency,identity_status)
           VALUES(?,?,?,?,?,?,?,?)""",
        (research_company_id, name, name_en, ticker, market, listing_status,
         reporting_currency, identity_status),
    ).lastrowid)
    if research_company_id is not None:
        conn.execute(
            f"""INSERT INTO {_table('financial_security_company_link', schema)}(
                   research_company_id,security_id,link_role) VALUES(?,?,'canonical')""",
            (int(research_company_id), security_id),
        )
    return security_id


def record_source_snapshot(
    conn: sqlite3.Connection,
    *,
    provider: str,
    source_channel: str,
    source_ref: str,
    title: str,
    publisher: str | None = None,
    as_of_date: str | None = None,
    fetched_at: str | None = None,
    content_hash: str | None = None,
    raw_snapshot_path: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    schema: str | None = None,
) -> int:
    if source_channel not in SOURCE_CHANNELS:
        raise ValueError(f"非法 source_channel: {source_channel}")
    if not str(provider or "").strip() or not str(source_ref or "").strip() or not str(title or "").strip():
        raise ValueError("provider/source_ref/title 不能为空")
    normalized_as_of = _iso_date(as_of_date)
    payload = _canonical_json(dict(metadata or {}))
    row = conn.execute(
        f"""SELECT id FROM {_table('financial_source_snapshot', schema)}
           WHERE provider=? AND source_ref=? AND as_of_date IS ? AND content_hash IS ?""",
        (provider, source_ref, normalized_as_of, content_hash),
    ).fetchone()
    if row:
        return int(row[0])
    return int(conn.execute(
        f"""INSERT INTO {_table('financial_source_snapshot', schema)}(
             provider,source_channel,source_ref,title,publisher,as_of_date,fetched_at,
             content_hash,raw_snapshot_path,metadata_json)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (provider, source_channel, source_ref, title, publisher, normalized_as_of,
         fetched_at, content_hash, raw_snapshot_path, payload),
    ).lastrowid)


def observation_key(payload: Mapping[str, Any]) -> str:
    identity = {
        key: payload.get(key)
        for key in (
            "security_id", "metric_name", "period_start", "period_end", "fiscal_year",
            "fiscal_period", "fact_type", "as_of_date", "provider", "raw_feature_name",
            "scenario_name", "model_run_id",
        )
    }
    return _hash(identity)


def upsert_observation(
    conn: sqlite3.Connection,
    *,
    schema: str | None = None,
    return_status: bool = False,
    revision_reason: str = "provider_revision_same_observation_identity",
    **raw: Any,
) -> int | tuple[int, str]:
    fact_type = str(raw.get("fact_type") or "")
    if fact_type not in FACT_TYPES:
        raise ValueError(f"非法 fact_type: {fact_type}")
    metric = str(raw.get("metric_name") or "").strip()
    unit = str(raw.get("unit") or "").strip()
    provider = str(raw.get("provider") or "").strip()
    if not metric or not unit or not provider:
        raise ValueError("metric_name/unit/provider 不能为空")
    value_num = _finite(raw.get("value_num"))
    value_text = str(raw.get("value_text") or "").strip() or None
    if value_num is None and value_text is None and raw.get("quality_status") != "not_applicable":
        raise ValueError("数值和文本不能同时为空")
    formula = str(raw.get("formula") or "").strip() or None
    input_refs = list(raw.get("input_refs") or [])
    if provider == "internal_model" and value_num is not None and not formula:
        raise ValueError("内部模型观察值必须保存公式")
    payload = {
        **raw,
        "metric_name": metric,
        "value_num": value_num,
        "value_text": value_text,
        "unit": unit,
        "period_start": _iso_date(raw.get("period_start")),
        "period_end": _iso_date(raw.get("period_end")),
        "as_of_date": _iso_date(raw.get("as_of_date"), required=True),
        "announcement_date": _iso_date(raw.get("announcement_date")),
        "provider": provider,
        "formula": formula,
        "input_refs_json": _canonical_json(input_refs),
        "scenario_name": str(raw.get("scenario_name") or "reported"),
        "frequency": str(raw.get("frequency") or "snapshot"),
        "quality_status": str(raw.get("quality_status") or "usable"),
    }
    payload["observation_key"] = observation_key(payload)
    columns = (
        "observation_key", "security_id", "metric_name", "value_num", "value_text", "unit",
        "currency", "period_start", "period_end", "fiscal_year", "fiscal_period", "frequency",
        "fact_type", "as_of_date", "announcement_date", "provider", "raw_feature_name",
        "source_snapshot_id", "formula", "input_refs_json", "quality_status", "scenario_name",
        "model_run_id", "legacy_ref",
    )
    values = tuple(payload.get(column) for column in columns)
    existing = conn.execute(
        f"""SELECT id,value_num,value_text,unit,currency,source_snapshot_id,formula,
                   input_refs_json,quality_status
              FROM {_table('financial_observation', schema)} WHERE observation_key=?""",
        (payload["observation_key"],),
    ).fetchone()
    tracked_columns = (
        "value_num", "value_text", "unit", "currency", "source_snapshot_id",
        "formula", "input_refs_json", "quality_status",
    )
    replacement = {column: payload.get(column) for column in tracked_columns}
    status = "inserted"
    if existing is not None:
        previous = {column: existing[column] for column in tracked_columns}
        if previous == replacement:
            status = "unchanged"
        else:
            status = "revised"
            conn.execute(
                f"""INSERT INTO {_table('financial_observation_revision', schema)}(
                       observation_id,previous_payload_json,replacement_payload_json,revision_reason)
                     VALUES(?,?,?,?)""",
                (int(existing["id"]), _canonical_json(previous), _canonical_json(replacement), revision_reason),
            )
    conn.execute(
        f"""INSERT INTO {_table('financial_observation', schema)}({','.join(columns)})
            VALUES({','.join('?' for _ in columns)})
            ON CONFLICT(observation_key) DO UPDATE SET
              value_num=excluded.value_num,value_text=excluded.value_text,unit=excluded.unit,
              currency=excluded.currency,source_snapshot_id=excluded.source_snapshot_id,
              formula=excluded.formula,input_refs_json=excluded.input_refs_json,
              quality_status=excluded.quality_status,updated_at=datetime('now')""",
        values,
    )
    row = conn.execute(
        f"SELECT id FROM {_table('financial_observation', schema)} WHERE observation_key=?",
        (payload["observation_key"],),
    ).fetchone()
    observation_id = int(row[0])
    return (observation_id, status) if return_status else observation_id


def create_model_run(
    conn: sqlite3.Connection,
    *,
    run_key: str,
    skill_name: str,
    model_name: str,
    model_role: str,
    security_id: int | None = None,
    research_run_ref: str | None = None,
    forecast_start: str | None = None,
    forecast_end: str | None = None,
    valuation_date: str | None = None,
    assumptions: Mapping[str, Any] | None = None,
    limitations: str | None = None,
) -> int:
    if skill_name not in MODEL_SKILLS:
        raise ValueError(f"非法 skill_name: {skill_name}")
    return int(conn.execute(
        """INSERT INTO financial_model_run(
             run_key,security_id,research_run_ref,skill_name,model_name,model_role,
             forecast_start,forecast_end,valuation_date,assumptions_json,limitations)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (run_key, security_id, research_run_ref, skill_name, model_name, model_role,
         forecast_start, forecast_end, valuation_date, _canonical_json(dict(assumptions or {})), limitations),
    ).lastrowid)


def record_model_inputs(conn: sqlite3.Connection, model_run_id: int, rows: Iterable[Mapping[str, Any]]) -> None:
    for row in rows:
        if not str(row.get("source_ref") or "").strip():
            raise ValueError("每个模型输入必须有 source_ref")
        conn.execute(
            """INSERT INTO financial_model_input(
                 model_run_id,input_name,value_num,value_text,range_low,range_high,unit,
                 period_or_as_of_date,source_ref,input_type,formula_or_method,
                 sensitivity_note,limitation_note)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (model_run_id, row["input_name"], _finite(row.get("value_num")), row.get("value_text"),
             _finite(row.get("range_low")), _finite(row.get("range_high")), row["unit"],
             row["period_or_as_of_date"], row["source_ref"], row["input_type"],
             row.get("formula_or_method"), row.get("sensitivity_note"), row.get("limitation_note")),
        )


def record_model_outputs(conn: sqlite3.Connection, model_run_id: int, rows: Iterable[Mapping[str, Any]]) -> None:
    for row in rows:
        conn.execute(
            """INSERT INTO financial_model_output(
                 model_run_id,output_name,value_num,value_text,range_low,range_high,unit,
                 period_or_as_of_date,formula,substitution,dependency_group,conclusion)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (model_run_id, row["output_name"], _finite(row.get("value_num")), row.get("value_text"),
             _finite(row.get("range_low")), _finite(row.get("range_high")), row["unit"],
             row["period_or_as_of_date"], row["formula"], row["substitution"],
             row.get("dependency_group"), row.get("conclusion")),
        )


def freeze_independent_model(conn: sqlite3.Connection, model_run_id: int) -> tuple[str, str]:
    inputs = [dict(row) for row in conn.execute(
        "SELECT * FROM financial_model_input WHERE model_run_id=? ORDER BY id", (model_run_id,)
    )]
    outputs = [dict(row) for row in conn.execute(
        "SELECT * FROM financial_model_output WHERE model_run_id=? ORDER BY id", (model_run_id,)
    )]
    if not inputs or not outputs:
        raise ValueError("冻结前必须同时存在模型输入和输出")
    input_hash, output_hash = _hash(inputs), _hash(outputs)
    conn.execute(
        """UPDATE financial_model_run SET status='frozen_independent',
             independent_before_consensus=1,input_hash=?,output_hash=?,frozen_at=?,updated_at=datetime('now')
           WHERE id=?""",
        (input_hash, output_hash, datetime.now(timezone.utc).isoformat(timespec="seconds"), model_run_id),
    )
    return input_hash, output_hash


def finalize_reviewed_model(conn: sqlite3.Connection, model_run_id: int) -> tuple[str, str]:
    """Freeze the ledger hash for a diagnostic model that legitimately uses market data.

    Reverse valuation and current-PB diagnostics are not independent forecasts, so
    marking them ``frozen_independent`` would misstate the research sequence.  They
    still need immutable input/output hashes before the viewer can present them as
    reviewed diagnostics.
    """
    model = conn.execute(
        "SELECT model_role,status FROM financial_model_run WHERE id=?",
        (int(model_run_id),),
    ).fetchone()
    if model is None:
        raise ValueError(f"模型运行不存在: {model_run_id}")
    if str(model["model_role"]) not in {"diagnostic", "reference"}:
        raise ValueError("只有诊断或参考模型可以跳过独立预测冻结")
    inputs = [dict(row) for row in conn.execute(
        "SELECT * FROM financial_model_input WHERE model_run_id=? ORDER BY id", (model_run_id,)
    )]
    outputs = [dict(row) for row in conn.execute(
        "SELECT * FROM financial_model_output WHERE model_run_id=? ORDER BY id", (model_run_id,)
    )]
    if not inputs or not outputs:
        raise ValueError("复核前必须同时存在模型输入和输出")
    input_hash, output_hash = _hash(inputs), _hash(outputs)
    conn.execute(
        """UPDATE financial_model_run SET status='reviewed',
             independent_before_consensus=0,input_hash=?,output_hash=?,
             frozen_at=?,updated_at=datetime('now')
           WHERE id=?""",
        (input_hash, output_hash, datetime.now(timezone.utc).isoformat(timespec="seconds"), model_run_id),
    )
    return input_hash, output_hash


def record_external_reconciliation(
    conn: sqlite3.Connection,
    model_run_id: int,
    *,
    benchmark_type: str,
    benchmark_source_ref: str,
    metric_name: str,
    period: str,
    independent_value: float | None,
    benchmark_value: float | None,
    unit: str,
    decomposition: Mapping[str, Any] | None = None,
    conclusion: str,
) -> int:
    """Record an external benchmark only after the independent model is frozen."""
    model = conn.execute(
        """SELECT status,independent_before_consensus,input_hash,output_hash
             FROM financial_model_run WHERE id=?""",
        (int(model_run_id),),
    ).fetchone()
    if model is None:
        raise ValueError(f"模型运行不存在: {model_run_id}")
    if (
        str(model["status"]) not in {"frozen_independent", "reconciled"}
        or int(model["independent_before_consensus"] or 0) != 1
        or not model["input_hash"]
        or not model["output_hash"]
    ):
        raise ValueError("外部对账前必须先冻结独立模型及其输入、输出")
    if benchmark_type not in ALLOWED_BENCHMARK_TYPES:
        raise ValueError(f"非法 benchmark_type: {benchmark_type}")
    source_ref = str(benchmark_source_ref or "").strip()
    metric = str(metric_name or "").strip()
    normalized_period = str(period or "").strip()
    normalized_unit = str(unit or "").strip()
    normalized_conclusion = str(conclusion or "").strip()
    if not all((source_ref, metric, normalized_period, normalized_unit, normalized_conclusion)):
        raise ValueError("对账来源、指标、期间、单位和结论均不能为空")
    independent = _finite(independent_value)
    benchmark = _finite(benchmark_value)
    difference = None if independent is None or benchmark is None else independent - benchmark
    difference_pct = None
    if difference is not None and benchmark not in {None, 0.0}:
        difference_pct = difference / abs(benchmark)
    conn.execute(
        """INSERT INTO financial_reconciliation(
             model_run_id,benchmark_type,benchmark_source_ref,metric_name,period,
             independent_value,benchmark_value,unit,difference_value,difference_pct,
             decomposition_json,conclusion)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(model_run_id,benchmark_type,benchmark_source_ref,metric_name,period)
           DO UPDATE SET independent_value=excluded.independent_value,
             benchmark_value=excluded.benchmark_value,unit=excluded.unit,
             difference_value=excluded.difference_value,difference_pct=excluded.difference_pct,
             decomposition_json=excluded.decomposition_json,conclusion=excluded.conclusion,
             reconciled_at=datetime('now')""",
        (
            int(model_run_id), benchmark_type, source_ref, metric, normalized_period,
            independent, benchmark, normalized_unit, difference, difference_pct,
            _canonical_json(dict(decomposition or {})), normalized_conclusion,
        ),
    )
    conn.execute(
        """UPDATE financial_model_run SET status='reconciled',updated_at=datetime('now')
             WHERE id=?""",
        (int(model_run_id),),
    )
    row = conn.execute(
        """SELECT id FROM financial_reconciliation
             WHERE model_run_id=? AND benchmark_type=? AND benchmark_source_ref=?
               AND metric_name=? AND period=?""",
        (int(model_run_id), benchmark_type, source_ref, metric, normalized_period),
    ).fetchone()
    return int(row[0])


def latest_observations(
    conn: sqlite3.Connection,
    *,
    research_company_id: int,
    fact_types: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    params: list[Any] = [int(research_company_id)]
    clause = ""
    if fact_types:
        selected = list(dict.fromkeys(fact_types))
        clause = f" AND o.fact_type IN ({','.join('?' for _ in selected)})"
        params.extend(selected)
    rows = conn.execute(
        f"""SELECT o.*,s.canonical_name,s.ticker,s.market,ss.title AS source_title,
                   ss.publisher AS source_publisher,ss.source_channel
              FROM financial_observation o
              JOIN financial_security s ON s.id=o.security_id
              LEFT JOIN financial_security_company_link l ON l.security_id=s.id
              LEFT JOIN financial_source_snapshot ss ON ss.id=o.source_snapshot_id
             WHERE (l.research_company_id=? OR s.research_company_id=?) {clause}
             ORDER BY o.metric_name,o.period_end,o.as_of_date,o.id""",
        [params[0], *params],
    )
    return [dict(row) for row in rows]
