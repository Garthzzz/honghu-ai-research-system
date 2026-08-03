#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""合并经 provider/交易所核验的重复公司身份并修正三项市场身份。

默认只验证；显式 ``--apply`` 才写库，写默认 live research.db 还必须传
``--confirm-live``。旧公司 ID 写入 redirect 表，旧中英文名写入 alias 表；研究
数据点、公司画像、行业关系和 JSON 公司引用均迁到 canonical ID 后才删除重复行。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = ROOT / "data" / "research.db"
VERIFIED_AT = "2026-07-15T14:00:00+08:00"

LISTING_STATUS_TARGETS = {
    421: "us",
    466: "tse",
    539: "other_listed",
    543: "tse",
    589: "other_listed",
    593: "tse",
}

# 同一快照的数值、日期、币种和来源必须成组裁决，禁止逐字段拼接。
SNAPSHOT_GROUPS = (
    (
        "valuation",
        "valuation_as_of",
        (
            "pe_ttm", "pe_forward", "pb", "ps_ttm", "ev_ebitda",
            "dividend_yield", "peg", "market_cap_value", "market_cap_unit",
            "valuation_as_of", "valuation_source_id",
        ),
    ),
    (
        "market_cap_translation",
        "market_cap_cny_as_of",
        ("market_cap_cny", "market_cap_usd", "market_cap_cny_as_of"),
    ),
    (
        "financial_metrics",
        "financial_metrics_as_of",
        (
            "roe", "roa", "eps_ttm", "bps_mrq", "per_share_currency",
            "financial_metrics_as_of", "financial_metrics_source_id",
        ),
    ),
    (
        "forecast",
        "forecast_as_of_date",
        (
            "forecast_eps_year1", "forecast_eps_year2",
            "forecast_revenue_year1", "forecast_revenue_year2",
            "forecast_revenue_unit", "forecast_as_of_date", "forecast_source_id",
        ),
    ),
)


@dataclass(frozen=True)
class IdentityMerge:
    old_id: int
    old_name: str
    canonical_id: int
    canonical_name_before: str
    canonical_name_after: str
    ticker: str


MERGES = (
    IdentityMerge(19, "Cisco", 174, "思科", "思科", "CSCO"),
    IdentityMerge(22, "NVIDIA", 150, "英伟达", "英伟达", "NVDA"),
    IdentityMerge(23, "Broadcom", 173, "博通", "博通", "AVGO"),
    IdentityMerge(24, "Microsoft", 197, "微软", "微软", "MSFT"),
    IdentityMerge(25, "Amazon", 196, "亚马逊", "亚马逊", "AMZN"),
    IdentityMerge(217, "华通Compeq", 589, "华通电脑", "华通电脑", "2313.TW"),
    IdentityMerge(331, "沐曦股份", 335, "沐曦", "沐曦股份", "688802.SH"),
    IdentityMerge(575, "Applied Materials", 421, "应用材料", "应用材料", "AMAT"),
    IdentityMerge(564, "Ibiden", 466, "揖斐电", "揖斐电", "4062.T"),
    IdentityMerge(565, "Meiko Electronics", 593, "名幸电子", "名幸电子", "6787.T"),
    IdentityMerge(516, "世创(Siltronic)", 539, "世创Siltronic", "世创（Siltronic）", "WAF.DE"),
    IdentityMerge(508, "胜高(SUMCO)", 543, "胜高SUMCO", "胜高（SUMCO）", "3436.T"),
)


def connect(path: Path, *, writable: bool) -> sqlite3.Connection:
    if writable:
        con = sqlite3.connect(str(path))
    else:
        con = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        con.execute("PRAGMA query_only=ON")
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def ensure_schema(con: sqlite3.Connection) -> None:
    script = """
        CREATE TABLE IF NOT EXISTS company_identity_redirect(
          old_company_id INTEGER PRIMARY KEY,
          canonical_company_id INTEGER NOT NULL REFERENCES company(id),
          old_name TEXT NOT NULL,
          canonical_name TEXT NOT NULL,
          ticker TEXT,
          reason TEXT NOT NULL,
          verified_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_company_identity_redirect_canonical
          ON company_identity_redirect(canonical_company_id);
        CREATE TABLE IF NOT EXISTS company_identity_alias(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          canonical_company_id INTEGER NOT NULL REFERENCES company(id) ON DELETE CASCADE,
          alias TEXT NOT NULL,
          alias_type TEXT NOT NULL,
          source TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
          UNIQUE(canonical_company_id,alias)
        );
        CREATE INDEX IF NOT EXISTS idx_company_identity_alias_text
          ON company_identity_alias(alias);
        """
    # sqlite3.executescript() 会在 Python 驱动层隐式 COMMIT，不能用于迁移事务。
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            sql = statement.strip()
            if sql:
                con.execute(sql)
            statement = ""
    if statement.strip():
        raise RuntimeError("015 schema SQL 不完整")


def _company(con: sqlite3.Connection, company_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM company WHERE id=?", (company_id,)).fetchone()


def _validate_merge(con: sqlite3.Connection, item: IdentityMerge) -> tuple[sqlite3.Row | None, sqlite3.Row]:
    old = _company(con, item.old_id)
    canonical = _company(con, item.canonical_id)
    if canonical is None:
        raise RuntimeError(f"canonical company 不存在: {item.canonical_id}")
    allowed_canonical_names = {item.canonical_name_before, item.canonical_name_after}
    if canonical["name"] not in allowed_canonical_names:
        raise RuntimeError(
            f"canonical 名称冲突: {item.canonical_id} {canonical['name']!r}"
        )
    if str(canonical["ticker"] or "").upper() != item.ticker:
        raise RuntimeError(
            f"canonical ticker 冲突: {item.canonical_id} {canonical['ticker']!r}"
        )
    if old is None:
        redirect = con.execute(
            "SELECT * FROM company_identity_redirect WHERE old_company_id=?", (item.old_id,)
        ).fetchone() if _table_exists(con, "company_identity_redirect") else None
        if redirect is None or int(redirect["canonical_company_id"]) != item.canonical_id:
            raise RuntimeError(f"旧 company 缺失且无合法 redirect: {item.old_id}")
        return None, canonical
    if old["name"] != item.old_name:
        raise RuntimeError(f"旧公司名称冲突: {item.old_id} {old['name']!r}")
    old_ticker = str(old["ticker"] or "").upper()
    if old_ticker and old_ticker != item.ticker:
        raise RuntimeError(f"旧公司 ticker 冲突: {item.old_id} {old_ticker!r}")
    return old, canonical


def _is_empty(value: object) -> bool:
    return value in (None, "")


def _merge_text(canonical: object, old: object, *, old_id: int, label: str) -> str | None:
    current = str(canonical or "").strip()
    legacy = str(old or "").strip()
    if not legacy:
        return current or None
    if not current:
        return legacy
    if legacy == current or legacy in current:
        return current
    return f"{current}；补充（合并自旧 company_id={old_id} 的{label}）：{legacy}"


def _merge_sources(canonical: object, old: object) -> str | None:
    values: list[str] = []
    for raw in (canonical, old):
        for value in str(raw or "").split(";"):
            value = value.strip()
            if value and value not in values:
                values.append(value)
    return "; ".join(values) or None


def _snapshot_updates(
    old: sqlite3.Row,
    canonical: sqlite3.Row,
    *,
    group_name: str,
    date_field: str,
    fields: tuple[str, ...],
    resolutions: list[dict],
) -> dict[str, object]:
    differing = [
        field for field in fields
        if not _is_empty(old[field]) and not _is_empty(canonical[field])
        and old[field] != canonical[field]
    ]
    updates: dict[str, object] = {}
    if not differing:
        for field in fields:
            if _is_empty(canonical[field]) and not _is_empty(old[field]):
                updates[field] = old[field]
        return updates

    old_date = str(old[date_field] or "").strip()
    canonical_date = str(canonical[date_field] or "").strip()
    if not old_date or not canonical_date:
        raise RuntimeError(
            f"company {old['id']}->{canonical['id']} 的 {group_name} 快照冲突缺少可裁决日期: "
            f"{differing}"
        )
    if old_date == canonical_date:
        raise RuntimeError(
            f"company {old['id']}->{canonical['id']} 的 {group_name} 同日快照值冲突: "
            f"{differing}"
        )
    choose_old = old_date > canonical_date
    if choose_old:
        # 成组复制，包括 NULL；避免新日期与旧快照残值拼接。
        updates.update({field: old[field] for field in fields})
    resolutions.append({
        "scope": "company",
        "old_company_id": int(old["id"]),
        "canonical_company_id": int(canonical["id"]),
        "group": group_name,
        "conflicting_fields": differing,
        "old_as_of": old_date,
        "canonical_as_of": canonical_date,
        "resolution": "old_newer_snapshot" if choose_old else "canonical_newer_snapshot",
    })
    return updates


def _fill_company_fields(
    con: sqlite3.Connection, old: sqlite3.Row, canonical: sqlite3.Row
) -> dict:
    excluded = {"id", "name", "ticker", "created_at"}
    grouped_fields = {field for _, _, fields in SNAPSHOT_GROUPS for field in fields}
    updates: dict[str, object] = {}
    resolutions: list[dict] = []

    for group_name, date_field, fields in SNAPSHOT_GROUPS:
        updates.update(
            _snapshot_updates(
                old, canonical, group_name=group_name, date_field=date_field,
                fields=fields, resolutions=resolutions,
            )
        )

    merged_note = _merge_text(canonical["note"], old["note"], old_id=int(old["id"]), label="note")
    if merged_note != canonical["note"]:
        updates["note"] = merged_note
        resolutions.append({
            "scope": "company", "old_company_id": int(old["id"]),
            "canonical_company_id": int(canonical["id"]), "field": "note",
            "resolution": "deduplicated_text_merge",
        })
    merged_intro = _merge_text(
        canonical["brief_intro"], old["brief_intro"],
        old_id=int(old["id"]), label="brief_intro",
    )
    if merged_intro != canonical["brief_intro"]:
        updates["brief_intro"] = merged_intro
        updates["brief_intro_src"] = _merge_sources(
            canonical["brief_intro_src"], old["brief_intro_src"]
        )
        resolutions.append({
            "scope": "company", "old_company_id": int(old["id"]),
            "canonical_company_id": int(canonical["id"]), "field": "brief_intro",
            "resolution": "provenance_preserving_text_merge",
        })
    elif _is_empty(canonical["brief_intro_src"]) and not _is_empty(old["brief_intro_src"]):
        updates["brief_intro_src"] = old["brief_intro_src"]

    handled = grouped_fields | {"note", "brief_intro", "brief_intro_src", "listing_status"}
    for key in old.keys():
        if key in excluded or key in handled:
            continue
        if _is_empty(canonical[key]) and not _is_empty(old[key]):
            updates[key] = old[key]
        elif not _is_empty(old[key]) and not _is_empty(canonical[key]) and old[key] != canonical[key]:
            raise RuntimeError(
                f"company {old['id']}->{canonical['id']} 未定义字段冲突策略: "
                f"{key}={old[key]!r}/{canonical[key]!r}"
            )

    target_status = LISTING_STATUS_TARGETS.get(int(canonical["id"]))
    if target_status:
        updates["listing_status"] = target_status
        if old["listing_status"] != canonical["listing_status"]:
            resolutions.append({
                "scope": "company", "old_company_id": int(old["id"]),
                "canonical_company_id": int(canonical["id"]), "field": "listing_status",
                "resolution": f"provider_verified:{target_status}",
            })
    elif _is_empty(canonical["listing_status"]) and not _is_empty(old["listing_status"]):
        updates["listing_status"] = old["listing_status"]
    elif (
        not _is_empty(old["listing_status"])
        and not _is_empty(canonical["listing_status"])
        and old["listing_status"] != canonical["listing_status"]
    ):
        raise RuntimeError(
            f"company {old['id']}->{canonical['id']} listing_status 冲突无核验策略"
        )

    if updates:
        assignments = ",".join(f'"{key}"=?' for key in updates)
        con.execute(
            f"UPDATE company SET {assignments} WHERE id=?",
            (*updates.values(), int(canonical["id"])),
        )
    return {"updated_fields": len(updates), "resolutions": resolutions}


def _merge_company_table(
    con: sqlite3.Connection,
    table: str,
    old_id: int,
    canonical_id: int,
    key_columns: Iterable[str],
) -> dict[str, int]:
    """按业务唯一键迁移；任何未定义的非空业务冲突都整事务失败。"""
    if not _table_exists(con, table):
        return {"moved": 0, "merged": 0}
    columns = [row[1] for row in con.execute(f'PRAGMA table_info("{table}")')]
    pk_columns = [row[1] for row in con.execute(f'PRAGMA table_info("{table}")') if row[5]]
    if "company_id" not in columns or len(pk_columns) != 1:
        raise RuntimeError(f"{table} schema 不符合身份迁移合同")
    pk = pk_columns[0]
    keys = tuple(key_columns)
    moved = merged = 0
    rows = con.execute(
        f'SELECT * FROM "{table}" WHERE company_id=? ORDER BY "{pk}"', (old_id,)
    ).fetchall()
    for row in rows:
        where = " AND ".join(["company_id=?", *(f'"{key}" IS ?' for key in keys)])
        existing = con.execute(
            f'SELECT * FROM "{table}" WHERE {where} LIMIT 1',
            (canonical_id, *(row[key] for key in keys)),
        ).fetchone()
        if existing is None:
            con.execute(
                f'UPDATE "{table}" SET company_id=? WHERE "{pk}"=?',
                (canonical_id, row[pk]),
            )
            moved += 1
            continue
        updates = {}
        for column in columns:
            if column in {pk, "company_id", *keys}:
                continue
            if existing[column] in (None, "") and row[column] not in (None, ""):
                updates[column] = row[column]
            elif (
                existing[column] not in (None, "")
                and row[column] not in (None, "")
                and existing[column] != row[column]
            ):
                if column in {"created_at", "last_updated", "last_verified_at"}:
                    updates[column] = max(str(existing[column]), str(row[column]))
                else:
                    raise RuntimeError(
                        f"{table} 唯一键冲突含未裁决字段: old={old_id} "
                        f"canonical={canonical_id} field={column} "
                        f"old_value={row[column]!r} canonical_value={existing[column]!r}"
                    )
        if updates:
            assignments = ",".join(f'"{key}"=?' for key in updates)
            con.execute(
                f'UPDATE "{table}" SET {assignments} WHERE "{pk}"=?',
                (*updates.values(), existing[pk]),
            )
        con.execute(f'DELETE FROM "{table}" WHERE "{pk}"=?', (row[pk],))
        merged += 1
    return {"moved": moved, "merged": merged}


def _rewrite_json_id_lists(con: sqlite3.Connection, mapping: dict[int, int]) -> int:
    changed = 0
    targets = (
        ("event", "related_company_ids"),
        ("hypothesis", "related_company_ids"),
        ("hypothesis_trade", "target_company_ids"),
        ("news_item", "ai_tags_company"),
        ("voice_post", "ai_tags_company"),
    )
    for table, column in targets:
        if not _table_exists(con, table):
            continue
        for row in con.execute(
            f'SELECT id,"{column}" value FROM "{table}" WHERE "{column}" IS NOT NULL'
        ).fetchall():
            try:
                values = json.loads(row["value"])
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(values, list):
                continue
            normalized = []
            touched = False
            for value in values:
                if isinstance(value, int) and value in mapping:
                    value = mapping[value]
                    touched = True
                if value not in normalized:
                    normalized.append(value)
            if touched or normalized != values:
                con.execute(
                    f'UPDATE "{table}" SET "{column}"=? WHERE id=?',
                    (json.dumps(normalized, ensure_ascii=False), row["id"]),
                )
                changed += 1
    return changed


def _upsert_alias(
    con: sqlite3.Connection, canonical_id: int, alias: str, alias_type: str
) -> None:
    alias = str(alias or "").strip()
    if not alias:
        return
    con.execute(
        """INSERT INTO company_identity_alias(canonical_company_id,alias,alias_type,source)
           VALUES(?,?,?,'015_provider_identity_audit')
           ON CONFLICT(canonical_company_id,alias) DO UPDATE SET
             alias_type=excluded.alias_type,source=excluded.source""",
        (canonical_id, alias, alias_type),
    )


def _row_counts(con: sqlite3.Connection, tables: Iterable[str]) -> dict[str, int]:
    return {
        table: int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        for table in tables if _table_exists(con, table)
    }


def apply(con: sqlite3.Connection) -> dict:
    transaction_was_open = con.in_transaction
    ensure_schema(con)
    if transaction_was_open and not con.in_transaction:
        raise RuntimeError("015 ensure_schema 破坏了外层事务")
    tracked_tables = (
        "company", "industry_data_point", "company_industry", "company_profile",
        "company_sub_market_share", "company_thesis", "data_point_peer_group",
        "theme_company", "source_entity", "analyst_note", "fetch_schedule",
    )
    before_counts = _row_counts(con, tracked_tables)
    result = {
        "merged_companies": 0,
        "filled_company_fields": 0,
        "conflict_resolutions": [],
        "tables": {},
        "json_refs": 0,
    }
    mapping = {item.old_id: item.canonical_id for item in MERGES}
    result["json_refs"] = _rewrite_json_id_lists(con, mapping)
    for item in MERGES:
        old, canonical = _validate_merge(con, item)
        if old is None:
            continue
        fill = _fill_company_fields(con, old, canonical)
        result["filled_company_fields"] += int(fill["updated_fields"])
        result["conflict_resolutions"].extend(fill["resolutions"])
        con.execute(
            "UPDATE industry_data_point SET company_id=? WHERE company_id=?",
            (item.canonical_id, item.old_id),
        )
        specs = (
            ("company_industry", ("industry_id", "role")),
            ("company_profile", ("industry_id", "period")),
            ("company_sub_market_share", ("industry_id", "sub_market", "geo")),
            ("company_thesis", ("industry_id",)),
            ("data_point_peer_group", ("industry_id", "metric", "as_of_date", "is_forecast")),
            ("theme_company", ("theme_id",)),
        )
        for table, keys in specs:
            stat = _merge_company_table(con, table, item.old_id, item.canonical_id, keys)
            if stat["moved"] or stat["merged"]:
                bucket = result["tables"].setdefault(table, {"moved": 0, "merged": 0})
                bucket["moved"] += stat["moved"]
                bucket["merged"] += stat["merged"]
        if _table_exists(con, "analyst_note"):
            con.execute(
                "UPDATE analyst_note SET entity_id=? WHERE entity_type='company' AND entity_id=?",
                (item.canonical_id, item.old_id),
            )
        if _table_exists(con, "source_entity"):
            con.execute(
                "UPDATE source_entity SET entity_id=? WHERE entity_type='company' AND entity_id=?",
                (str(item.canonical_id), str(item.old_id)),
            )
        if _table_exists(con, "fetch_schedule"):
            con.execute(
                "UPDATE fetch_schedule SET target_id=? WHERE target_type='company' AND target_id=?",
                (item.canonical_id, item.old_id),
            )
        _upsert_alias(con, item.canonical_id, item.old_name, "legacy_name")
        _upsert_alias(con, item.canonical_id, item.canonical_name_before, "name")
        _upsert_alias(con, item.canonical_id, item.canonical_name_after, "canonical_name")
        _upsert_alias(con, item.canonical_id, item.ticker, "ticker")
        con.execute(
            """INSERT INTO company_identity_redirect(
                 old_company_id,canonical_company_id,old_name,canonical_name,ticker,reason,verified_at)
               VALUES(?,?,?,?,?,'same listed legal entity; provider-verified duplicate',?)""",
            (
                item.old_id, item.canonical_id, item.old_name, item.canonical_name_after,
                item.ticker, VERIFIED_AT,
            ),
        )
        con.execute("DELETE FROM company WHERE id=?", (item.old_id,))
        if item.canonical_name_before != item.canonical_name_after:
            con.execute(
                "UPDATE company SET name=? WHERE id=? AND name=?",
                (item.canonical_name_after, item.canonical_id, item.canonical_name_before),
            )
        result["merged_companies"] += 1

    # 明确身份修正：ASMPT 为港股；第四范式已更名；东芝记录本意是非上市 HDD 子公司，
    # 绝不能继续绑定 Toshiba Tec 6588.T。
    asmpt = _company(con, 53)
    if not asmpt or asmpt["name"] != "ASMPT" or str(asmpt["ticker"] or "") not in {"0522.HK", "00522.HK"}:
        raise RuntimeError("ASMPT 身份前置条件冲突")
    con.execute(
        "UPDATE company SET ticker='00522.HK',market='港股',listing_status='hk' WHERE id=53"
    )
    _upsert_alias(con, 53, "0522.HK", "legacy_ticker")
    _upsert_alias(con, 53, "00522.HK", "ticker")

    phancy = _company(con, 114)
    if not phancy or phancy["name"] not in {"第四范式", "范式智能"} or phancy["ticker"] != "06682.HK":
        raise RuntimeError("范式智能身份前置条件冲突")
    con.execute("UPDATE company SET name='范式智能',market='港股',listing_status='hk' WHERE id=114")
    _upsert_alias(con, 114, "第四范式", "legacy_name")
    _upsert_alias(con, 114, "范式智能", "canonical_name")
    _upsert_alias(con, 114, "PHANCY", "english_short_name")

    toshiba = _company(con, 122)
    if not toshiba or toshiba["name"] not in {"东芝", "东芝电子器件及存储"}:
        raise RuntimeError("东芝身份前置条件冲突")
    if toshiba["ticker"] not in {None, "", "6588.T"}:
        raise RuntimeError(f"东芝旧 ticker 冲突: {toshiba['ticker']!r}")
    note = str(toshiba["note"] or "").strip()
    audit_note = "身份核验：本记录为非上市 Toshiba Electronic Devices & Storage；6588.T 属于 Toshiba Tec，已解除错误绑定。"
    if audit_note not in note:
        note = f"{note}；{audit_note}" if note else audit_note
    con.execute(
        """UPDATE company SET name='东芝电子器件及存储',ticker=NULL,market='其他',
                  listing_status='private_subsidiary',display_mode='qualitative_only',note=?,
                  pe_ttm=NULL,pe_forward=NULL,pb=NULL,market_cap_value=NULL,market_cap_unit=NULL,
                  valuation_as_of=NULL,roe=NULL,roa=NULL,ev_ebitda=NULL,ps_ttm=NULL,
                  dividend_yield=NULL,peg=NULL,valuation_source_id=NULL,market_cap_cny=NULL,
                  market_cap_usd=NULL,market_cap_cny_as_of=NULL,eps_ttm=NULL,bps_mrq=NULL,
                  per_share_currency=NULL,financial_metrics_as_of=NULL,financial_metrics_source_id=NULL
           WHERE id=122""",
        (note,),
    )
    _upsert_alias(con, 122, "东芝", "legacy_name")
    _upsert_alias(con, 122, "Toshiba Electronic Devices & Storage", "english_name")

    # 即使某个未来 schema 变化没有 FK，也不能静默留下旧 company_id。
    after_counts = _row_counts(con, tracked_tables)
    expected = dict(before_counts)
    expected["company"] = before_counts["company"] - result["merged_companies"]
    for table, stat in result["tables"].items():
        if table in expected:
            expected[table] -= int(stat["merged"])
    mismatches = {
        table: {"before": before_counts[table], "expected": expected[table], "after": after_counts[table]}
        for table in expected if after_counts.get(table) != expected[table]
    }
    if mismatches:
        raise RuntimeError(f"身份合并行数守恒失败: {mismatches}")
    result["row_counts"] = {"before": before_counts, "after": after_counts}
    return result


def verify(con: sqlite3.Connection) -> dict:
    ensure = _table_exists(con, "company_identity_redirect") and _table_exists(con, "company_identity_alias")
    if not ensure:
        raise RuntimeError("015 schema 尚未部署")
    for item in MERGES:
        old = _company(con, item.old_id)
        canonical = _company(con, item.canonical_id)
        redirect = con.execute(
            "SELECT * FROM company_identity_redirect WHERE old_company_id=?", (item.old_id,)
        ).fetchone()
        if old is not None or canonical is None or canonical["name"] != item.canonical_name_after:
            raise RuntimeError(f"公司合并未完成: {item.old_id}->{item.canonical_id}")
        if redirect is None or int(redirect["canonical_company_id"]) != item.canonical_id:
            raise RuntimeError(f"redirect 缺失: {item.old_id}")
    asmpt = _company(con, 53)
    phancy = _company(con, 114)
    toshiba = _company(con, 122)
    if (asmpt["ticker"], asmpt["market"], asmpt["listing_status"]) != ("00522.HK", "港股", "hk"):
        raise RuntimeError("ASMPT 修正未完成")
    if phancy["name"] != "范式智能" or phancy["ticker"] != "06682.HK":
        raise RuntimeError("范式智能修正未完成")
    if toshiba["name"] != "东芝电子器件及存储" or toshiba["ticker"] is not None or toshiba["listing_status"] != "private_subsidiary":
        raise RuntimeError("东芝错误 ticker 尚未解除")
    for company_id, target_status in LISTING_STATUS_TARGETS.items():
        row = _company(con, company_id)
        if row is None or row["listing_status"] != target_status:
            raise RuntimeError(
                f"上市状态规范化失败: company={company_id} "
                f"actual={None if row is None else row['listing_status']!r} expected={target_status!r}"
            )

    old_ids = tuple(item.old_id for item in MERGES)
    placeholders = ",".join("?" for _ in old_ids)
    remaining: dict[str, int] = {}
    for table, in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall():
        columns = {str(row[1]) for row in con.execute(f'PRAGMA table_info("{table}")')}
        if "company_id" not in columns:
            continue
        count = int(con.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE company_id IN ({placeholders})', old_ids
        ).fetchone()[0])
        if count:
            remaining[f"{table}.company_id"] = count
    for table, entity_type_column, entity_id_column, company_type in (
        ("analyst_note", "entity_type", "entity_id", "company"),
        ("source_entity", "entity_type", "entity_id", "company"),
        ("fetch_schedule", "target_type", "target_id", "company"),
    ):
        if not _table_exists(con, table):
            continue
        count = int(con.execute(
            f'''SELECT COUNT(*) FROM "{table}"
                WHERE "{entity_type_column}"=?
                  AND CAST("{entity_id_column}" AS TEXT) IN ({placeholders})''',
            (company_type, *(str(value) for value in old_ids)),
        ).fetchone()[0])
        if count:
            remaining[f"{table}.{entity_id_column}"] = count
    if remaining:
        raise RuntimeError(f"旧 company 引用仍有残留: {remaining}")

    mapping = {item.old_id: item.canonical_id for item in MERGES}
    for table, column in (
        ("event", "related_company_ids"),
        ("hypothesis", "related_company_ids"),
        ("hypothesis_trade", "target_company_ids"),
        ("news_item", "ai_tags_company"),
        ("voice_post", "ai_tags_company"),
    ):
        if not _table_exists(con, table):
            continue
        for row in con.execute(
            f'SELECT id,"{column}" value FROM "{table}" WHERE "{column}" IS NOT NULL'
        ):
            try:
                values = json.loads(row["value"])
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(values, list) and any(value in mapping for value in values):
                raise RuntimeError(f"JSON 旧 company 引用残留: {table}.{column} id={row['id']}")
    duplicates = con.execute(
        """SELECT ticker,COUNT(*) n FROM company
           WHERE ticker IS NOT NULL AND TRIM(ticker)<>''
           GROUP BY UPPER(TRIM(ticker)) HAVING COUNT(*)>1"""
    ).fetchall()
    if duplicates:
        raise RuntimeError(f"仍有重复 ticker: {[tuple(row) for row in duplicates]}")
    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    if fk:
        raise RuntimeError(f"foreign_key_check 失败: {len(fk)}")
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    if integrity != "ok":
        raise RuntimeError(f"integrity_check 失败: {integrity}")
    return {
        "companies": con.execute("SELECT COUNT(*) FROM company").fetchone()[0],
        "redirects": con.execute("SELECT COUNT(*) FROM company_identity_redirect").fetchone()[0],
        "aliases": con.execute("SELECT COUNT(*) FROM company_identity_alias").fetchone()[0],
        "duplicate_tickers": 0,
        "old_references": 0,
        "integrity": integrity,
        "foreign_keys": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-live", action="store_true")
    args = parser.parse_args(argv)
    path = args.db.resolve()
    if not path.exists():
        parser.error(f"数据库不存在: {path}")
    if args.apply and path == DEFAULT_DB.resolve() and not args.confirm_live:
        parser.error("写默认 live research.db 必须显式 --confirm-live")
    con = connect(path, writable=args.apply)
    try:
        if args.apply:
            con.execute("BEGIN IMMEDIATE")
            result = apply(con)
            audit = verify(con)
            con.commit()
            print(json.dumps({"ok": True, "result": result, "audit": audit}, ensure_ascii=False))
        else:
            audit = verify(con)
            print(json.dumps({"ok": True, "audit": audit}, ensure_ascii=False))
        return 0
    except Exception:
        if args.apply:
            con.rollback()
        raise
    finally:
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
