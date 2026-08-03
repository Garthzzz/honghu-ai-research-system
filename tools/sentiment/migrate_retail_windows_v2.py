#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""散户情绪市场窗口 V2 的安全迁移与公司身份归并。

默认只审计，不写库。只有传入 ``--apply`` 才会修改目标数据库；目标是 live
``data/sentiment.db`` 时还必须额外传入 ``--allow-live``。这样临时库测试和正式
运维使用同一份迁移代码，同时避免误触 live 数据。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

import common
import retail_windows_v2
import senti3


@dataclass(frozen=True)
class IdentityRedirect:
    old_company_id: int
    canonical_company_id: int
    canonical_name: str


@dataclass(frozen=True)
class VerifiedSentiCompany:
    company_id: int
    name: str
    ticker: str


IDENTITY_REDIRECTS = (
    IdentityRedirect(900001, 557, "东山精密"),
    IdentityRedirect(900003, 555, "胜宏科技"),
    IdentityRedirect(900004, 392, "中芯国际"),
    IdentityRedirect(900015, 448, "盛合晶微"),
    IdentityRedirect(900017, 556, "鹏鼎控股"),
    IdentityRedirect(900018, 535, "菲利华"),
    IdentityRedirect(900019, 388, "协创数据"),
    IdentityRedirect(900024, 532, "立昂微"),
    IdentityRedirect(900025, 583, "生益电子"),
    IdentityRedirect(900031, 520, "中船特气"),
)

# 2026-07-15 Tushare stock_basic：31/31 按中文名精确唯一匹配，且 list_status=L。
# 这是身份校验输入，不是猜测；迁移只写 sentiment.db，不反向写 research.db。
VERIFIED_SENTI_COMPANIES = (
    VerifiedSentiCompany(900001, "东山精密", "002384.SZ"),
    VerifiedSentiCompany(900002, "京东方A", "000725.SZ"),
    VerifiedSentiCompany(900003, "胜宏科技", "300476.SZ"),
    VerifiedSentiCompany(900004, "中芯国际", "688981.SH"),
    VerifiedSentiCompany(900005, "信维通信", "300136.SZ"),
    VerifiedSentiCompany(900006, "三环集团", "300408.SZ"),
    VerifiedSentiCompany(900007, "蓝思科技", "300433.SZ"),
    VerifiedSentiCompany(900008, "风华高科", "000636.SZ"),
    VerifiedSentiCompany(900009, "云南锗业", "002428.SZ"),
    VerifiedSentiCompany(900010, "华虹宏力", "688347.SH"),
    VerifiedSentiCompany(900011, "大族激光", "002008.SZ"),
    VerifiedSentiCompany(900012, "兴森科技", "002436.SZ"),
    VerifiedSentiCompany(900013, "国瓷材料", "300285.SZ"),
    VerifiedSentiCompany(900014, "中国巨石", "600176.SH"),
    VerifiedSentiCompany(900015, "盛合晶微", "688820.SH"),
    VerifiedSentiCompany(900016, "剑桥科技", "603083.SH"),
    VerifiedSentiCompany(900017, "鹏鼎控股", "002938.SZ"),
    VerifiedSentiCompany(900018, "菲利华", "300395.SZ"),
    VerifiedSentiCompany(900019, "协创数据", "300857.SZ"),
    VerifiedSentiCompany(900020, "利通电子", "603629.SH"),
    VerifiedSentiCompany(900021, "东材科技", "601208.SH"),
    VerifiedSentiCompany(900022, "三安光电", "600703.SH"),
    VerifiedSentiCompany(900023, "德福科技", "301511.SZ"),
    VerifiedSentiCompany(900024, "立昂微", "605358.SH"),
    VerifiedSentiCompany(900025, "生益电子", "688183.SH"),
    VerifiedSentiCompany(900026, "长芯博创", "300548.SZ"),
    VerifiedSentiCompany(900027, "铜冠铜箔", "301217.SZ"),
    VerifiedSentiCompany(900028, "江海股份", "002484.SZ"),
    VerifiedSentiCompany(900029, "通鼎互联", "002491.SZ"),
    VerifiedSentiCompany(900030, "亿纬锂能", "300014.SZ"),
    VerifiedSentiCompany(900031, "中船特气", "688146.SH"),
)

A_SHARE_TICKER = re.compile(r"^\d{6}\.(?:SZ|SH|SS|BJ)$", re.IGNORECASE)

LEGACY_DERIVED_TABLES = (
    "senti_retail_bucket",
    "senti_retail_daily",
    "senti_news_bucket",
    "senti_news_daily",
    "heat_volume_bucket",
    "heat_volume_daily",
)

OTHER_COMPANY_TABLES = (
    "senti_discussion_daily",
    "senti_indicator_daily",
    "senti_post",
    "senti_discussion_hourly",
    "senti_indicator_hourly",
    "senti_kline_hourly",
    "stock_kline",
    "senti_label_corpus",
    "recruit_source",
    "recruit_job",
    "recruit_change_log",
)


def _norm_name(value: str | None) -> str:
    return "".join(str(value or "").split()).casefold()


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f'PRAGMA table_info("{table}")')}


def _research_company_map(research: sqlite3.Connection) -> dict[int, sqlite3.Row]:
    return {
        int(row["id"]): row
        for row in research.execute(
            "SELECT id,name,ticker FROM company ORDER BY id"
        )
    }


def _verified_by_id(
    verified_companies: Iterable[VerifiedSentiCompany] = VERIFIED_SENTI_COMPANIES,
) -> dict[int, VerifiedSentiCompany]:
    return {item.company_id: item for item in verified_companies}


def _redirect_ticker(
    redirect: IdentityRedirect,
    research_companies: dict[int, sqlite3.Row],
    verified_companies: Iterable[VerifiedSentiCompany] = VERIFIED_SENTI_COMPANIES,
) -> str:
    verified = _verified_by_id(verified_companies).get(redirect.old_company_id)
    research_ticker = str(
        research_companies[redirect.canonical_company_id]["ticker"] or ""
    ).strip().upper()
    expected = verified.ticker if verified else research_ticker
    if not expected:
        raise ValueError(f"redirect 无已验证 ticker: {redirect.old_company_id}")
    if research_ticker and research_ticker != expected:
        raise ValueError(
            f"canonical ticker 与 Tushare 身份核验冲突: {redirect.canonical_company_id} "
            f"{research_ticker!r} != {expected!r}"
        )
    return expected


def validate_verified_senti_companies(
    senti: sqlite3.Connection,
    redirects: Iterable[IdentityRedirect] = IDENTITY_REDIRECTS,
    verified_companies: Iterable[VerifiedSentiCompany] = VERIFIED_SENTI_COMPANIES,
) -> None:
    if not _table_exists(senti, "senti_company"):
        raise RuntimeError("senti_company 不存在，无法验证 31 家 Tushare 身份")
    redirected_ids = {item.old_company_id for item in redirects}
    for item in verified_companies:
        row = senti.execute(
            "SELECT name,ticker FROM senti_company WHERE id=?", (item.company_id,)
        ).fetchone()
        if row is None:
            # 幂等重跑时 10 个 duplicate 已转成 redirect 并删除本地身份。
            redirect_exists = _table_exists(senti, "company_id_redirect") and senti.execute(
                "SELECT 1 FROM company_id_redirect WHERE old_company_id=?", (item.company_id,)
            ).fetchone()
            if item.company_id in redirected_ids and redirect_exists:
                continue
            raise ValueError(f"经 Tushare 核验的 senti_company 缺失: {item.company_id}")
        if _norm_name(row["name"]) != _norm_name(item.name):
            raise ValueError(
                f"Tushare 身份名称不匹配: {item.company_id} {row['name']!r} != {item.name!r}"
            )
        current = str(row["ticker"] or "").strip().upper()
        # 空值和历史 ticker=name 是已知待修复状态；其他冲突不能静默覆盖。
        if current and _norm_name(current) != _norm_name(row["name"]) and current != item.ticker:
            raise ValueError(
                f"已有 ticker 与 Tushare 核验冲突: {item.company_id} {current!r} != {item.ticker!r}"
            )


def apply_verified_senti_tickers(
    con: sqlite3.Connection,
    redirects: Iterable[IdentityRedirect] = IDENTITY_REDIRECTS,
    verified_companies: Iterable[VerifiedSentiCompany] = VERIFIED_SENTI_COMPANIES,
) -> dict[str, int]:
    """修复 31 家 ticker，并把所有既有 company_id+ticker 兼容行同步为真代码。"""
    verified_companies = tuple(verified_companies)
    validate_verified_senti_companies(con, redirects, verified_companies)
    updated = 0
    for item in verified_companies:
        cur = con.execute(
            "UPDATE senti_company SET ticker=? WHERE id=?", (item.ticker, item.company_id)
        )
        updated += max(cur.rowcount, 0)
    tables = [
        row[0]
        for row in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    ]
    synced_rows = 0
    for table in tables:
        if table in {"senti_company", "company_alias"}:
            continue
        columns = _columns(con, table)
        if not {"company_id", "ticker"}.issubset(columns):
            continue
        for item in verified_companies:
            cur = con.execute(
                f'UPDATE "{table}" SET ticker=? WHERE company_id=?',
                (item.ticker, item.company_id),
            )
            synced_rows += max(cur.rowcount, 0)
    old_ids = tuple(item.company_id for item in verified_companies)
    aliases_deleted = _delete_company_rows(con, "company_alias", old_ids)
    return {
        "companies_updated": updated,
        "rows_ticker_synced": synced_rows,
        "polluted_aliases_deleted": aliases_deleted,
    }


def sync_canonical_research_tickers(
    con: sqlite3.Connection,
    research_companies: dict[int, sqlite3.Row],
) -> dict[str, int]:
    """把 sentiment 公司链中的 provider/历史 ticker 统一回 research canonical。

    Yahoo 对上交所使用 ``.SS``，但该后缀只能存在于 provider 请求边界；数据库
    关联键统一保存 ``.SH``。这里按 live research company 身份同步所有同时含
    ``company_id`` 与 ``ticker`` 的表，并单独处理 ``senti_company.id``。不带
    company_id 的 Funda 拓扑镜像不在本迁移的边界内。
    """
    canonical = {
        int(company_id): str(row["ticker"] or "").strip().upper()
        for company_id, row in research_companies.items()
        if str(row["ticker"] or "").strip()
    }
    table_counts: dict[str, int] = {}
    tables = [
        str(row[0])
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
    ]
    for table in tables:
        columns = _columns(con, table)
        id_column = "id" if table == "senti_company" else "company_id"
        if id_column not in columns or "ticker" not in columns:
            continue
        changed = 0
        for company_id, ticker in canonical.items():
            cur = con.execute(
                f'''UPDATE "{table}" SET ticker=?
                    WHERE "{id_column}"=?
                      AND COALESCE(UPPER(TRIM(ticker)),'')<>?''',
                (ticker, company_id, ticker),
            )
            changed += max(cur.rowcount, 0)
        if changed:
            table_counts[table] = changed
    return table_counts


def validate_redirects(
    senti: sqlite3.Connection,
    research: sqlite3.Connection,
    redirects: Iterable[IdentityRedirect] = IDENTITY_REDIRECTS,
    verified_companies: Iterable[VerifiedSentiCompany] = VERIFIED_SENTI_COMPANIES,
) -> dict[int, sqlite3.Row]:
    """验证两端身份，拒绝仅凭相同中文名进行静默归并。"""
    research_companies = _research_company_map(research)
    verified_companies = tuple(verified_companies)
    validate_verified_senti_companies(senti, redirects, verified_companies)
    for redirect in redirects:
        canonical = research_companies.get(redirect.canonical_company_id)
        if canonical is None:
            raise ValueError(f"research company 不存在: {redirect.canonical_company_id}")
        if _norm_name(canonical["name"]) != _norm_name(redirect.canonical_name):
            raise ValueError(
                f"canonical 名称不匹配: {redirect.canonical_company_id} "
                f"{canonical['name']!r} != {redirect.canonical_name!r}"
            )
        _redirect_ticker(redirect, research_companies, verified_companies)
        if _table_exists(senti, "senti_company"):
            old = senti.execute(
                "SELECT name FROM senti_company WHERE id=?", (redirect.old_company_id,)
            ).fetchone()
            # 幂等重跑时旧 senti_company 已删除；首次迁移存在时必须精确核名。
            if old and _norm_name(old["name"]) != _norm_name(redirect.canonical_name):
                raise ValueError(
                    f"旧身份名称不匹配: {redirect.old_company_id} "
                    f"{old['name']!r} != {redirect.canonical_name!r}"
                )

        if _table_exists(senti, "company_id_redirect"):
            existing = senti.execute(
                "SELECT canonical_company_id,canonical_name FROM company_id_redirect "
                "WHERE old_company_id=?",
                (redirect.old_company_id,),
            ).fetchone()
            if existing and (
                int(existing["canonical_company_id"]) != redirect.canonical_company_id
                or _norm_name(existing["canonical_name"]) != _norm_name(redirect.canonical_name)
            ):
                raise ValueError(f"已有 redirect 冲突: {redirect.old_company_id}")
    return research_companies


def audit_state(
    senti: sqlite3.Connection,
    research: sqlite3.Connection,
    redirects: Iterable[IdentityRedirect] = IDENTITY_REDIRECTS,
    verified_companies: Iterable[VerifiedSentiCompany] = VERIFIED_SENTI_COMPANIES,
) -> dict:
    validate_redirects(senti, research, redirects, verified_companies)
    old_ids = tuple(item.old_company_id for item in redirects)
    placeholders = ",".join("?" for _ in old_ids)
    counts = {}
    for table in ("senti_company", "company_alias", "senti_raw", *LEGACY_DERIVED_TABLES):
        if not _table_exists(senti, table):
            continue
        column = "id" if table == "senti_company" else "company_id"
        counts[table] = int(
            senti.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE "{column}" IN ({placeholders})',
                old_ids,
            ).fetchone()[0]
        )
    return {"redirects": len(old_ids), "old_rows": counts}


def _pick_min(*values):
    clean = [value for value in values if value not in (None, "")]
    return min(clean) if clean else None


def _pick_max(*values):
    clean = [value for value in values if value not in (None, "")]
    return max(clean) if clean else None


def _merge_raw_pair(
    con: sqlite3.Connection,
    target: sqlite3.Row,
    old: sqlite3.Row,
    canonical_ticker: str,
    columns: set[str],
) -> None:
    """把同一去重键的两行无损压到 canonical 行；冲突标签保留 canonical。"""
    updates: dict[str, object] = {"ticker": canonical_ticker}
    fill_if_empty = (
        "post_id", "title", "url", "author", "author_uid", "web_name", "domain",
        "channel", "sim_hash", "reason", "as_of", "attitude_src",
    )
    for column in fill_if_empty:
        if column in columns and target[column] in (None, "") and old[column] not in (None, ""):
            updates[column] = old[column]
    if "attitude" in columns and target["attitude"] is None and old["attitude"] is not None:
        updates["attitude"] = old["attitude"]
        if "attitude_src" in columns and old["attitude_src"]:
            updates["attitude_src"] = old["attitude_src"]

    for column in (
        "fans_count", "auth_type", "media_type", "hot_value", "read_count", "reply_count",
        "heat_value", "sampled", "backfilled",
    ):
        if column in columns:
            updates[column] = _pick_max(target[column], old[column])
    if "publish_time" in columns:
        updates["publish_time"] = _pick_min(target["publish_time"], old["publish_time"])
    if "fetched_at" in columns:
        updates["fetched_at"] = _pick_max(target["fetched_at"], old["fetched_at"])

    set_sql = ",".join(f'"{key}"=?' for key in updates)
    con.execute(
        f'UPDATE senti_raw SET {set_sql} WHERE id=?',
        (*updates.values(), int(target["id"])),
    )


def merge_raw_identities(
    con: sqlite3.Connection,
    research_companies: dict[int, sqlite3.Row],
    redirects: Iterable[IdentityRedirect] = IDENTITY_REDIRECTS,
    verified_companies: Iterable[VerifiedSentiCompany] = VERIFIED_SENTI_COMPANIES,
) -> dict[str, int]:
    if not _table_exists(con, "senti_raw"):
        return {"moved": 0, "deduplicated": 0, "remapped": 0}
    columns = _columns(con, "senti_raw")
    touched: set[int] = set()
    moved = deduplicated = 0
    has_mapping = _table_exists(con, "senti_raw_window")

    for redirect in redirects:
        ticker = _redirect_ticker(redirect, research_companies, verified_companies)
        old_rows = con.execute(
            "SELECT * FROM senti_raw WHERE company_id=? ORDER BY id",
            (redirect.old_company_id,),
        ).fetchall()
        for old in old_rows:
            target = con.execute(
                "SELECT * FROM senti_raw WHERE company_id=? AND source_layer=? AND dedup_key=?",
                (redirect.canonical_company_id, old["source_layer"], old["dedup_key"]),
            ).fetchone()
            if target is None:
                con.execute(
                    "UPDATE senti_raw SET company_id=?,ticker=? WHERE id=?",
                    (redirect.canonical_company_id, ticker, old["id"]),
                )
                touched.add(int(old["id"]))
                moved += 1
                continue

            if has_mapping:
                con.execute(
                    "DELETE FROM senti_raw_window WHERE raw_id IN (?,?)",
                    (old["id"], target["id"]),
                )
            _merge_raw_pair(con, target, old, ticker, columns)
            con.execute("DELETE FROM senti_raw WHERE id=?", (old["id"],))
            touched.add(int(target["id"]))
            deduplicated += 1

    remap_stat = retail_windows_v2.map_retail_raw_rows(con, raw_ids=sorted(touched)) if touched else {"mapped": 0}
    return {"moved": moved, "deduplicated": deduplicated, "remapped": int(remap_stat["mapped"])}


def _move_other_company_rows(
    con: sqlite3.Connection,
    redirects: Iterable[IdentityRedirect],
) -> int:
    """迁移当前为空的兼容表；若未来出现唯一键冲突则整事务失败，不静默丢行。"""
    moved = 0
    for table in OTHER_COMPANY_TABLES:
        if not _table_exists(con, table) or "company_id" not in _columns(con, table):
            continue
        for redirect in redirects:
            try:
                cur = con.execute(
                    f'UPDATE "{table}" SET company_id=? WHERE company_id=?',
                    (redirect.canonical_company_id, redirect.old_company_id),
                )
            except sqlite3.IntegrityError as exc:
                raise RuntimeError(
                    f"{table} 身份迁移发生唯一键冲突，已回滚；需先编写该表专用归并规则"
                ) from exc
            moved += max(cur.rowcount, 0)
    return moved


def _delete_company_rows(
    con: sqlite3.Connection,
    table: str,
    company_ids: Iterable[int],
) -> int:
    ids = tuple(int(value) for value in company_ids)
    if not ids or not _table_exists(con, table):
        return 0
    cur = con.execute(
        f'DELETE FROM "{table}" WHERE company_id IN ({",".join("?" for _ in ids)})',
        ids,
    )
    return max(cur.rowcount, 0)


def rebuild_legacy_aggregates(
    con: sqlite3.Connection,
    redirects: Iterable[IdentityRedirect] = IDENTITY_REDIRECTS,
) -> dict[str, int]:
    present = {table for table in LEGACY_DERIVED_TABLES if _table_exists(con, table)}
    if not present:
        return {"rebuilt": 0, "deleted": 0}
    if present != set(LEGACY_DERIVED_TABLES):
        missing = sorted(set(LEGACY_DERIVED_TABLES) - present)
        raise RuntimeError(f"legacy 聚合表不完整，拒绝半迁移: {missing}")

    # 先删受影响身份的旧派生行，再从 canonical raw 在同一事务内重算。
    affected = {
        value
        for redirect in redirects
        for value in (redirect.old_company_id, redirect.canonical_company_id)
    }
    deleted = sum(_delete_company_rows(con, table, affected) for table in LEGACY_DERIVED_TABLES)

    import senti_aggregate_3layer

    layer_cfg = senti3.load_layer_config()
    weights = (layer_cfg.get("retail", {}) or {}).get("weights", senti3.DEFAULT_RETAIL_WEIGHTS)
    significance_min = int(
        (layer_cfg.get("retail", {}) or {}).get("significance_min", senti3.SIGNIFICANCE_MIN)
    )
    coverage_low = float(senti3.load_sampling_config()["coverage_low"])
    now = common.now_iso()
    nr = senti_aggregate_3layer.agg_retail(
        con, now, weights, significance_min, coverage_low, commit=False
    )
    nn = senti_aggregate_3layer.agg_news(
        con, now, significance_min, coverage_low, commit=False
    )
    nh = senti_aggregate_3layer.agg_heat(con, now, commit=False)
    senti_aggregate_3layer.rollup_daily(
        con, now, significance_min, coverage_low, weights, commit=False
    )
    return {"rebuilt": nr + nn + nh, "deleted": deleted}


def _alias_values(name: str, ticker: str) -> list[tuple[str, str]]:
    ticker = ticker.strip().upper()
    values = [(name.strip(), "name")]
    if ticker:
        values.append((ticker, "ticker"))
        code = ticker.split(".", 1)[0]
        if code:
            values.append((code, "code"))
    seen = set()
    unique = []
    for item in values:
        if item[0] and item[0] not in seen:
            seen.add(item[0])
            unique.append(item)
    return unique


def sync_research_aliases(
    con: sqlite3.Connection,
    research_companies: dict[int, sqlite3.Row],
    redirects: Iterable[IdentityRedirect] = IDENTITY_REDIRECTS,
    verified_companies: Iterable[VerifiedSentiCompany] = VERIFIED_SENTI_COMPANIES,
) -> dict[str, int]:
    if not _table_exists(con, "company_alias"):
        raise RuntimeError("company_alias 不存在，须先执行三层情绪基础迁移")
    old_ids = tuple(item.old_company_id for item in redirects)
    deleted = _delete_company_rows(con, "company_alias", old_ids)
    overrides = {
        item.canonical_company_id: _redirect_ticker(item, research_companies, verified_companies)
        for item in redirects
    }
    upserted = 0
    for company_id, company in research_companies.items():
        ticker = overrides.get(company_id) or str(company["ticker"] or "").strip().upper()
        name = str(company["name"] or "").strip()
        if not ticker or not name or not A_SHARE_TICKER.fullmatch(ticker):
            continue
        for alias, alias_type in _alias_values(name, ticker):
            con.execute(
                """INSERT INTO company_alias(company_id,ticker,alias,alias_type)
                   VALUES(?,?,?,?)
                   ON CONFLICT(company_id,alias) DO UPDATE SET
                     ticker=excluded.ticker,alias_type=excluded.alias_type""",
                (company_id, ticker, alias, alias_type),
            )
            upserted += 1
    return {"deleted_old": deleted, "upserted": upserted}


def sync_remaining_senti_aliases(
    con: sqlite3.Connection,
    verified_companies: Iterable[VerifiedSentiCompany] = VERIFIED_SENTI_COMPANIES,
) -> int:
    count = 0
    for item in verified_companies:
        row = con.execute(
            "SELECT name,ticker FROM senti_company WHERE id=?", (item.company_id,)
        ).fetchone()
        if row is None:
            continue
        ticker = str(row["ticker"] or "").strip().upper()
        if not ticker or _norm_name(ticker) == _norm_name(row["name"]):
            raise RuntimeError(f"senti_company ticker 未正确同步: {item.company_id}")
        for alias, alias_type in _alias_values(str(row["name"]), ticker):
            con.execute(
                """INSERT INTO company_alias(company_id,ticker,alias,alias_type)
                   VALUES(?,?,?,?)
                   ON CONFLICT(company_id,alias) DO UPDATE SET
                     ticker=excluded.ticker,alias_type=excluded.alias_type""",
                (item.company_id, ticker, alias, alias_type),
            )
            count += 1
    return count


def apply_migration(
    senti: sqlite3.Connection,
    research: sqlite3.Connection,
    *,
    redirects: Iterable[IdentityRedirect] = IDENTITY_REDIRECTS,
    verified_companies: Iterable[VerifiedSentiCompany] = VERIFIED_SENTI_COMPANIES,
    rebuild_legacy: bool = True,
) -> dict:
    redirects = tuple(redirects)
    verified_companies = tuple(verified_companies)
    retail_windows_v2.ensure_schema(senti)
    research_companies = validate_redirects(senti, research, redirects, verified_companies)
    verified_tickers = apply_verified_senti_tickers(senti, redirects, verified_companies)
    now = common.now_iso()
    for redirect in redirects:
        senti.execute(
            """INSERT INTO company_id_redirect(
                 old_company_id,canonical_company_id,canonical_name,reason,verified_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(old_company_id) DO UPDATE SET
                 canonical_company_id=excluded.canonical_company_id,
                 canonical_name=excluded.canonical_name,
                 reason=excluded.reason,
                 verified_at=excluded.verified_at""",
            (
                redirect.old_company_id,
                redirect.canonical_company_id,
                redirect.canonical_name,
                "sentiment-local duplicate of canonical research company",
                now,
            ),
        )

    raw = merge_raw_identities(senti, research_companies, redirects, verified_companies)
    other_moved = _move_other_company_rows(senti, redirects)
    legacy = rebuild_legacy_aggregates(senti, redirects) if rebuild_legacy else {"rebuilt": 0, "deleted": 0}
    aliases = sync_research_aliases(
        senti, research_companies, redirects, verified_companies
    )
    canonical_tickers = sync_canonical_research_tickers(senti, research_companies)
    deleted_companies = 0
    if _table_exists(senti, "senti_company"):
        old_ids = tuple(item.old_company_id for item in redirects)
        cur = senti.execute(
            f'DELETE FROM senti_company WHERE id IN ({",".join("?" for _ in old_ids)})',
            old_ids,
        )
        deleted_companies = max(cur.rowcount, 0)
    aliases["senti_verified_upserted"] = sync_remaining_senti_aliases(
        senti, verified_companies
    )
    for item in verified_companies:
        row = senti.execute(
            "SELECT name,ticker FROM senti_company WHERE id=?", (item.company_id,)
        ).fetchone()
        if row and (
            not str(row["ticker"] or "").strip()
            or _norm_name(row["ticker"]) == _norm_name(row["name"])
        ):
            raise RuntimeError(f"迁移后仍有空/伪 ticker: {item.company_id}")

    remaining = {}
    old_ids = tuple(item.old_company_id for item in redirects)
    placeholders = ",".join("?" for _ in old_ids)
    for table in ("company_alias", "senti_raw", *LEGACY_DERIVED_TABLES, *OTHER_COMPANY_TABLES):
        if not _table_exists(senti, table) or "company_id" not in _columns(senti, table):
            continue
        count = int(
            senti.execute(
                f'SELECT COUNT(*) FROM "{table}" WHERE company_id IN ({placeholders})', old_ids
            ).fetchone()[0]
        )
        if count:
            remaining[table] = count
    if remaining:
        raise RuntimeError(f"归并后仍有旧 company_id: {remaining}")

    return {
        "redirects": len(redirects),
        "verified_tickers": verified_tickers,
        "raw": raw,
        "other_rows_moved": other_moved,
        "legacy": legacy,
        "aliases": aliases,
        "canonical_tickers": canonical_tickers,
        "deleted_senti_company": deleted_companies,
    }


def _connect(path: Path, *, read_only: bool) -> sqlite3.Connection:
    if read_only:
        con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    else:
        con = sqlite3.connect(str(path), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=30000")
    return con


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=common.SENTI_DB)
    parser.add_argument("--research-db", type=Path, default=common.RESEARCH_DB)
    parser.add_argument("--apply", action="store_true", help="执行迁移；默认只读审计")
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="允许 --apply 写 data/sentiment.db；必须由运维人员显式给出",
    )
    parser.add_argument(
        "--no-rebuild-legacy",
        action="store_true",
        help="仅限不含 legacy 聚合表的测试库；正式库不得使用",
    )
    args = parser.parse_args(argv)
    db_path = args.db.resolve()
    research_path = args.research_db.resolve()
    live_path = common.SENTI_DB.resolve()
    if args.apply and db_path == live_path and not args.allow_live:
        parser.error("写 live sentiment.db 必须同时传 --apply --allow-live")
    if args.no_rebuild_legacy and db_path == live_path:
        parser.error("live sentiment.db 禁止跳过 legacy 聚合重算")

    senti = _connect(db_path, read_only=not args.apply)
    research = _connect(research_path, read_only=True)
    try:
        if not args.apply:
            print(json.dumps({"mode": "dry-run", **audit_state(senti, research)}, ensure_ascii=False, indent=2))
            return 0

        senti.execute("BEGIN IMMEDIATE")
        try:
            result = apply_migration(
                senti,
                research,
                rebuild_legacy=not args.no_rebuild_legacy,
            )
            fk_errors = senti.execute("PRAGMA foreign_key_check").fetchall()
            if fk_errors:
                raise RuntimeError(f"foreign_key_check 失败: {len(fk_errors)}")
            senti.commit()
        except Exception:
            senti.rollback()
            raise
        print(json.dumps({"mode": "applied", **result, "foreign_key_errors": 0}, ensure_ascii=False, indent=2))
        return 0
    finally:
        research.close()
        senti.close()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
