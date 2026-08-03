#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 research 015 identity redirect 同步到 sentiment 公司链。

默认只验证。显式 ``--apply`` 才写库；写默认 live sentiment.db 还必须加
``--allow-live``。迁移会无损归并 raw、K 线和别名，重算受影响 legacy/V2 聚合，
并把 provider 边界残留的 ``.SS`` 统一回 research canonical ``.SH``。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
DEFAULT_SENTIMENT = ROOT / "data" / "sentiment.db"
DEFAULT_RESEARCH = ROOT / "data" / "research.db"
sys.path.insert(0, str(HERE))

import common
import migrate_retail_windows_v2 as identity_v2
import retail_windows_v2


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


def _columns(con: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in con.execute(f'PRAGMA table_info("{table}")')}


def load_research_identity(research: sqlite3.Connection):
    if not _table_exists(research, "company_identity_redirect"):
        raise RuntimeError("research 015 identity redirect 尚未部署")
    redirects = []
    for row in research.execute(
        """SELECT r.old_company_id,r.canonical_company_id,c.name canonical_name
           FROM company_identity_redirect r
           JOIN company c ON c.id=r.canonical_company_id
           ORDER BY r.old_company_id"""
    ):
        redirects.append(
            identity_v2.IdentityRedirect(
                int(row["old_company_id"]), int(row["canonical_company_id"]),
                str(row["canonical_name"]),
            )
        )
    research_companies = identity_v2._research_company_map(research)
    return tuple(redirects), research_companies


def merge_stock_kline(
    con: sqlite3.Connection,
    redirects: tuple[identity_v2.IdentityRedirect, ...],
    research_companies: dict[int, sqlite3.Row],
) -> dict[str, int]:
    if not _table_exists(con, "stock_kline"):
        return {"moved": 0, "deduplicated": 0}
    moved = deduplicated = 0
    payload_columns = (
        "o", "h", "l", "c", "vol", "amount", "source_url", "as_of", "fetched_at", "source"
    )
    for redirect in redirects:
        ticker = str(research_companies[redirect.canonical_company_id]["ticker"] or "").upper()
        for old in con.execute(
            "SELECT * FROM stock_kline WHERE company_id=? ORDER BY id",
            (redirect.old_company_id,),
        ).fetchall():
            target = con.execute(
                "SELECT * FROM stock_kline WHERE company_id=? AND freq IS ? AND ts IS ?",
                (redirect.canonical_company_id, old["freq"], old["ts"]),
            ).fetchone()
            if target is None:
                con.execute(
                    "UPDATE stock_kline SET company_id=?,ticker=? WHERE id=?",
                    (redirect.canonical_company_id, ticker, old["id"]),
                )
                moved += 1
                continue
            old_fetch = str(old["fetched_at"] or "")
            target_fetch = str(target["fetched_at"] or "")
            if old_fetch > target_fetch:
                assignments = ",".join(f'"{column}"=?' for column in payload_columns)
                con.execute(
                    f"UPDATE stock_kline SET ticker=?,{assignments} WHERE id=?",
                    (ticker, *(old[column] for column in payload_columns), target["id"]),
                )
            else:
                con.execute(
                    "UPDATE stock_kline SET ticker=? WHERE id=?", (ticker, target["id"])
                )
            con.execute("DELETE FROM stock_kline WHERE id=?", (old["id"],))
            deduplicated += 1
    return {"moved": moved, "deduplicated": deduplicated}


def merge_aliases(
    con: sqlite3.Connection,
    research: sqlite3.Connection,
    redirects: tuple[identity_v2.IdentityRedirect, ...],
    research_companies: dict[int, sqlite3.Row],
) -> dict[str, int]:
    if not _table_exists(con, "company_alias"):
        return {"deleted_old": 0, "upserted": 0}
    deleted = upserted = 0
    for redirect in redirects:
        ticker = str(research_companies[redirect.canonical_company_id]["ticker"] or "").upper()
        rows = con.execute(
            "SELECT alias,alias_type FROM company_alias WHERE company_id=?",
            (redirect.old_company_id,),
        ).fetchall()
        for row in rows:
            con.execute(
                """INSERT INTO company_alias(company_id,ticker,alias,alias_type)
                   VALUES(?,?,?,?) ON CONFLICT(company_id,alias) DO UPDATE SET
                     ticker=excluded.ticker,alias_type=COALESCE(company_alias.alias_type,excluded.alias_type)""",
                (redirect.canonical_company_id, ticker, row["alias"], row["alias_type"]),
            )
            upserted += 1
        cur = con.execute(
            "DELETE FROM company_alias WHERE company_id=?", (redirect.old_company_id,)
        )
        deleted += max(cur.rowcount, 0)
    if _table_exists(research, "company_identity_alias"):
        for row in research.execute(
            """SELECT a.canonical_company_id,a.alias,a.alias_type,c.ticker
               FROM company_identity_alias a JOIN company c ON c.id=a.canonical_company_id"""
        ):
            ticker = str(row["ticker"] or "").upper()
            if not ticker:
                continue
            con.execute(
                """INSERT INTO company_alias(company_id,ticker,alias,alias_type)
                   VALUES(?,?,?,?) ON CONFLICT(company_id,alias) DO UPDATE SET
                     ticker=excluded.ticker,alias_type=excluded.alias_type""",
                (row["canonical_company_id"], ticker, row["alias"], row["alias_type"]),
            )
            upserted += 1
    return {"deleted_old": deleted, "upserted": upserted}


def _upsert_redirects(
    con: sqlite3.Connection,
    redirects: tuple[identity_v2.IdentityRedirect, ...],
) -> int:
    now = common.now_iso()
    count = 0
    reason = "research provider-verified duplicate company identity"
    for item in redirects:
        existing = con.execute(
            """SELECT canonical_company_id,canonical_name,reason
               FROM company_id_redirect WHERE old_company_id=?""",
            (item.old_company_id,),
        ).fetchone()
        if existing and int(existing["canonical_company_id"]) != item.canonical_company_id:
            raise RuntimeError(f"sentiment redirect 冲突: {item.old_company_id}")
        if existing and (
            str(existing["canonical_name"]) == item.canonical_name
            and str(existing["reason"]) == reason
        ):
            continue
        con.execute(
            """INSERT INTO company_id_redirect(
                 old_company_id,canonical_company_id,canonical_name,reason,verified_at)
               VALUES(?,?,?,?,?) ON CONFLICT(old_company_id) DO UPDATE SET
                 canonical_company_id=excluded.canonical_company_id,
                 canonical_name=excluded.canonical_name,
                 reason=excluded.reason,verified_at=excluded.verified_at""",
            (
                item.old_company_id, item.canonical_company_id, item.canonical_name,
                reason, now,
            ),
        )
        count += 1
    return count


def apply(con: sqlite3.Connection, research: sqlite3.Connection) -> dict:
    retail_windows_v2.ensure_schema(con)
    redirects, research_companies = load_research_identity(research)
    inserted_redirects = _upsert_redirects(con, redirects)
    old_ids = tuple(item.old_company_id for item in redirects)
    canonical_ids = tuple(item.canonical_company_id for item in redirects)
    placeholders = ",".join("?" for _ in old_ids)
    legacy_needed = any(
        _table_exists(con, table)
        and con.execute(
            f'SELECT 1 FROM "{table}" WHERE company_id IN ({placeholders}) LIMIT 1', old_ids
        ).fetchone()
        for table in identity_v2.LEGACY_DERIVED_TABLES
    )
    affected_windows: set[str] = set()
    if _table_exists(con, "senti_retail_window"):
        affected_windows.update(
            str(row[0]) for row in con.execute(
                f'''SELECT DISTINCT window_id FROM senti_retail_window
                    WHERE company_id IN ({placeholders})''', old_ids
            )
        )

    raw = identity_v2.merge_raw_identities(
        con, research_companies, redirects=redirects, verified_companies=()
    )
    kline = merge_stock_kline(con, redirects, research_companies)
    aliases = merge_aliases(con, research, redirects, research_companies)

    # 受影响 legacy 聚合必须从已归并 raw 重算，不能简单相加造成重复帖子。
    raw_changed = int(raw["moved"]) + int(raw["deduplicated"]) > 0
    legacy = (
        identity_v2.rebuild_legacy_aggregates(con, redirects)
        if raw_changed or legacy_needed else {"rebuilt": 0, "deleted": 0}
    )
    # 只重算确实受身份归并影响的窗口，二次执行保持 no-op。
    if raw_changed and _table_exists(con, "senti_raw_window"):
        ids = tuple(sorted(set(canonical_ids)))
        ph = ",".join("?" for _ in ids)
        affected_windows.update(
            str(row[0]) for row in con.execute(
                f'''SELECT DISTINCT rw.window_id
                    FROM senti_raw_window rw JOIN senti_raw r ON r.id=rw.raw_id
                    WHERE r.company_id IN ({ph})''', ids
            )
        )
    v2_companies = 0
    if _table_exists(con, "retail_window_ledger"):
        for window_id in sorted(affected_windows):
            v2_companies += retail_windows_v2.aggregate_window(con, window_id)

    # provider 请求符号不能泄漏为 canonical ticker；同时修复 ASMPT 五位港股代码。
    canonical_tickers = identity_v2.sync_canonical_research_tickers(con, research_companies)
    toshiba_kline_deleted = 0
    if _table_exists(con, "stock_kline"):
        con.execute(
            """UPDATE stock_kline SET ticker='00522.HK'
               WHERE company_id=53 AND COALESCE(UPPER(TRIM(ticker)),'')<>'00522.HK'"""
        )
        # 6588.T 属于 Toshiba Tec，不是 research id122 的非上市 HDD 子公司。
        unexpected = int(con.execute(
            """SELECT COUNT(*) FROM stock_kline WHERE company_id=122
               AND COALESCE(UPPER(TRIM(ticker)),'')<>'6588.T'"""
        ).fetchone()[0])
        if unexpected:
            raise RuntimeError(f"东芝 company_id=122 出现非 6588.T K线，拒绝无条件删除: {unexpected}")
        cur = con.execute(
            "DELETE FROM stock_kline WHERE company_id=122 AND UPPER(TRIM(ticker))='6588.T'"
        )
        toshiba_kline_deleted = max(cur.rowcount, 0)
    if _table_exists(con, "event_item") and {"entity_type", "entity_id"}.issubset(_columns(con, "event_item")):
        for item in redirects:
            con.execute(
                "UPDATE event_item SET entity_id=? WHERE entity_type='company' AND entity_id=?",
                (item.canonical_company_id, item.old_company_id),
            )
    return {
        "redirects": inserted_redirects,
        "raw": raw,
        "kline": kline,
        "aliases": aliases,
        "legacy": legacy,
        "v2_companies_rebuilt": v2_companies,
        "canonical_tickers": canonical_tickers,
        "toshiba_kline_deleted": toshiba_kline_deleted,
    }


def verify(con: sqlite3.Connection, research: sqlite3.Connection) -> dict:
    redirects, research_companies = load_research_identity(research)
    old_ids = tuple(item.old_company_id for item in redirects)
    placeholders = ",".join("?" for _ in old_ids)
    remaining = {}
    for table, in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall():
        if table == "company_id_redirect" or "company_id" not in _columns(con, table):
            continue
        count = con.execute(
            f'SELECT COUNT(*) FROM "{table}" WHERE company_id IN ({placeholders})', old_ids
        ).fetchone()[0]
        if count:
            remaining[table] = int(count)
    if remaining:
        raise RuntimeError(f"旧 company_id 仍有残留: {remaining}")
    for item in redirects:
        row = con.execute(
            "SELECT canonical_company_id FROM company_id_redirect WHERE old_company_id=?",
            (item.old_company_id,),
        ).fetchone()
        if row is None or int(row["canonical_company_id"]) != item.canonical_company_id:
            raise RuntimeError(f"sentiment redirect 缺失: {item.old_company_id}")
    bad_tickers = {}
    for table, in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall():
        columns = _columns(con, table)
        if not {"company_id", "ticker"}.issubset(columns):
            continue
        count = 0
        for company_id, row in research_companies.items():
            ticker = str(row["ticker"] or "").strip().upper()
            if not ticker:
                continue
            count += con.execute(
                f'''SELECT COUNT(*) FROM "{table}" WHERE company_id=?
                    AND COALESCE(UPPER(TRIM(ticker)),'')<>?''',
                (company_id, ticker),
            ).fetchone()[0]
        if count:
            bad_tickers[table] = int(count)
    if bad_tickers:
        raise RuntimeError(f"canonical ticker 残留不一致: {bad_tickers}")
    if _table_exists(con, "stock_kline"):
        if con.execute("SELECT COUNT(*) FROM stock_kline WHERE company_id=122").fetchone()[0]:
            raise RuntimeError("东芝错误 6588.T K 线仍存在")
    bad_names = con.execute(
        "SELECT COUNT(*) FROM senti_company WHERE name LIKE '#%' OR name=ticker OR TRIM(name)=''"
    ).fetchone()[0]
    if bad_names:
        raise RuntimeError(f"senti_company 名称仍异常: {bad_names}")
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    if integrity != "ok" or fk:
        raise RuntimeError(f"SQLite 检查失败: integrity={integrity} fk={len(fk)}")
    return {
        "redirects": len(redirects),
        "old_rows": 0,
        "bad_tickers": 0,
        "bad_names": 0,
        "integrity": integrity,
        "foreign_keys": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sentiment-db", type=Path, default=DEFAULT_SENTIMENT)
    parser.add_argument("--research-db", type=Path, default=DEFAULT_RESEARCH)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--allow-live", action="store_true")
    args = parser.parse_args(argv)
    sentiment_path = args.sentiment_db.resolve()
    research_path = args.research_db.resolve()
    if args.apply and sentiment_path == DEFAULT_SENTIMENT.resolve() and not args.allow_live:
        parser.error("写默认 live sentiment.db 必须显式 --allow-live")
    con = connect(sentiment_path, writable=args.apply)
    research = connect(research_path, writable=False)
    try:
        if args.apply:
            con.execute("BEGIN IMMEDIATE")
            result = apply(con, research)
            audit = verify(con, research)
            con.commit()
            print(json.dumps({"ok": True, "result": result, "audit": audit}, ensure_ascii=False))
        else:
            audit = verify(con, research)
            print(json.dumps({"ok": True, "audit": audit}, ensure_ascii=False))
        return 0
    except Exception:
        if args.apply:
            con.rollback()
        raise
    finally:
        research.close()
        con.close()


if __name__ == "__main__":
    raise SystemExit(main())
