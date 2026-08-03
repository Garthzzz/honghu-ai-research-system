#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
event_store — event 表读写公共层(可复用,被 earnings_fetcher / conference_loader /
POST /api/event / scheduler 共用,不写一次性入口)。

提供:
  upsert_conference(con, **f)  — 按 UNIQUE(title, scheduled_date) 幂等(INSERT OR IGNORE)
  upsert_earnings(con, company_id, company_name, quarter, date, ...) — 按 (company_id, quarter) UPSERT
  insert_manual(con, **f)      — POST /api/event 用,校验后插入
全部:
  - related_company_ids / related_industry_ids 内 id 入库前 SELECT 验证存在(反 slop)
  - event_type ∈ vocab §18,importance ∈ 1/2/3,status ∈ 枚举(db CHECK 兜底)
"""
from __future__ import annotations
import sqlite3, json
from datetime import datetime

EVENT_TYPES = {'财报', '大会', '产品发布', '监管', '并购', '融资', '论文', '业内传言'}


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _valid_ids(con, table, ids):
    """过滤出 db 中真实存在的 id(反 slop:不写不存在的关联)。返回 (valid, invalid)。"""
    if not ids:
        return [], []
    valid = []
    for i in ids:
        try:
            if con.execute(f"SELECT 1 FROM {table} WHERE id=?", (int(i),)).fetchone():
                valid.append(int(i))
        except Exception:
            pass
    invalid = [i for i in ids if int(i) not in valid] if ids else []
    return valid, invalid


def upsert_conference(con, *, title, scheduled_date, importance, related_industry_ids=None,
                      related_company_ids=None, official_url=None, description=None, source_id=None):
    inds, _ = _valid_ids(con, "industry", related_industry_ids or [])
    cos, _ = _valid_ids(con, "company", related_company_ids or [])
    cur = con.execute(
        """INSERT OR IGNORE INTO event(title, event_type, importance, scheduled_date, status,
             related_company_ids, related_industry_ids, description, official_url, data_source, source_id)
           VALUES(?, '大会', ?, ?, 'upcoming', ?, ?, ?, ?, 'hardcoded_conf', ?)""",
        (title, importance, scheduled_date, json.dumps(cos), json.dumps(inds),
         description, official_url, source_id))
    return ("inserted" if cur.rowcount else "exists")


def upsert_earnings(con, *, company_id, company_name, quarter, scheduled_date, importance,
                    description, source_id=None, status='upcoming'):
    """按 (company_id, quarter) UPSERT:同公司同季度已存在 → UPDATE 日期/描述,否则 INSERT。"""
    cos, _ = _valid_ids(con, "company", [company_id])
    if not cos:
        return "invalid_company"
    title = f"{company_name} {quarter} 财报"
    ex = con.execute(
        """SELECT id FROM event WHERE event_type='财报'
             AND related_company_ids LIKE ? AND title LIKE ?""",
        (f'%{company_id}%', f'%{quarter}%')).fetchone()
    if ex:
        con.execute("""UPDATE event SET title=?, scheduled_date=?, importance=?, description=?,
                       status=?, updated_at=? WHERE id=?""",
                    (title, scheduled_date, importance, description, status, _now(), ex[0]))
        return "updated"
    con.execute(
        """INSERT INTO event(title, event_type, importance, scheduled_date, status,
             related_company_ids, related_industry_ids, description, data_source, source_id)
           VALUES(?, '财报', ?, ?, ?, ?, '[]', ?, 'yfinance_earnings', ?)""",
        (title, importance, scheduled_date, status, json.dumps(cos), description, source_id))
    return "inserted"


def insert_manual(con, *, title, event_type, scheduled_date, importance,
                  related_company_ids=None, related_industry_ids=None,
                  description=None, official_url=None):
    """POST /api/event。返回 (ok, msg, event_id|None)。"""
    if event_type not in EVENT_TYPES:
        return False, f"event_type 非法(须 ∈ {sorted(EVENT_TYPES)})", None
    if importance not in (1, 2, 3):
        return False, "importance 须 ∈ 1/2/3", None
    if not title or not scheduled_date:
        return False, "title / scheduled_date 必填", None
    cos, bad_c = _valid_ids(con, "company", related_company_ids or [])
    inds, bad_i = _valid_ids(con, "industry", related_industry_ids or [])
    if bad_c or bad_i:
        return False, f"关联 id 不存在 company={bad_c} industry={bad_i}", None
    cur = con.execute(
        """INSERT INTO event(title, event_type, importance, scheduled_date, status,
             related_company_ids, related_industry_ids, description, official_url, data_source)
           VALUES(?,?,?,?, 'upcoming', ?,?,?,?, 'manual')""",
        (title, event_type, importance, scheduled_date, json.dumps(cos), json.dumps(inds),
         description, official_url))
    con.commit()
    return True, "ok", cur.lastrowid
