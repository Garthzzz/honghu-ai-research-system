#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""情绪/事件系统公共件:独立库连接、闭集校验、去重账本、门C 守卫、溯源时间戳。

C1 隔离:写连接 main=data/sentiment.db;research.db 一律 ro ATTACH/连接,绝不写。
门C 守卫:assert_senti_only() 在每个入库脚本起手调用,main 非 sentiment.db 立即抛。
"""
from __future__ import annotations
import sqlite3, hashlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).resolve().parent.parent.parent
SENTI_DB = ROOT / "data" / "sentiment.db"
RESEARCH_DB = ROOT / "data" / "research.db"
SECRETS = ROOT / "tools" / "dynamic" / "secrets"
TZ = timezone(timedelta(hours=8))


def now_iso() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def today() -> str:
    return datetime.now(TZ).date().isoformat()


def get_senti_db() -> sqlite3.Connection:
    con = sqlite3.connect(str(SENTI_DB), timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=30000")     # 并发 tick/抓取写库时等锁 30s,不立即失败(WAL 下多写者)
    return con


def attach_research_ro(con: sqlite3.Connection):
    """在 sentiment.db 连接上 ATTACH research.db 只读(viewer JOIN 用)。"""
    uri = f"file:{RESEARCH_DB.as_posix()}?mode=ro"
    con.execute(f"ATTACH DATABASE '{uri}' AS research")


def research_ro_conn() -> sqlite3.Connection:
    """独立只读连接读 research.db(闭集校验 / 取 dp)。"""
    uri = f"file:{RESEARCH_DB.as_posix()}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    return con


def load_closed_set():
    """闭集:research.db 现有 company.id / industry.id。"""
    rc = research_ro_conn()
    comps = {r[0] for r in rc.execute("SELECT id FROM company")}
    inds = {r[0] for r in rc.execute("SELECT id FROM industry")}
    rc.close()
    return comps, inds


def seen_key(kind, source, native_id) -> str:
    return hashlib.sha1(f"{kind}|{source}|{native_id}".encode("utf-8")).hexdigest()


def mark_seen(con, kind, source, native_id) -> bool:
    """去重账本:首见返回 True(应处理),已见返回 False(跳过)。"""
    k = seen_key(kind, source, native_id)
    cur = con.execute("INSERT OR IGNORE INTO senti_seen(seen_key,kind,first_seen_at) VALUES(?,?,?)",
                      (k, kind, now_iso()))
    return cur.rowcount == 1


def assert_senti_only(con: sqlite3.Connection):
    """门C 守卫:main 必须是 sentiment.db;任何 attach 的 research 必须 ro。"""
    for r in con.execute("PRAGMA database_list"):
        name, file = r[1], (r[2] or "")
        if name == "main" and not file.replace("\\", "/").endswith("data/sentiment.db"):
            raise RuntimeError(f"门C 违规:写连接 main 非 sentiment.db → {file}")


def assert_in_closed_set(comps, inds, entity_type, entity_id):
    if entity_type == "company" and entity_id not in comps:
        raise ValueError(f"闭集校验失败:company_id={entity_id} 不在 research.db")
    if entity_type == "industry" and entity_id not in inds:
        raise ValueError(f"闭集校验失败:industry_id={entity_id} 不在 research.db")
