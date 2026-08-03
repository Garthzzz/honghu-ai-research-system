#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""用 Tushare ``stock_basic`` 精确补全 research.company 的 A 股 ticker。

安全边界：

* ``--fetch-only`` 只读 research.db、联网生成 manifest，不写数据库；
* ``--apply-manifest`` 不联网，只填充当前仍为空的 ticker；
* 仅接受公司名与 Tushare ``name``/``fullname`` 的精确唯一匹配，不做模糊匹配；
* 不覆盖任何已有 ticker；歧义、无匹配和非 A 股对象均保留原状；
* 写默认 live research.db 必须显式 ``--confirm-live``。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .tushare_provider import call_tushare, ts_code_from_ticker


ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_DB = ROOT / "data" / "research.db"
SCHEMA_VERSION = "company_ticker_identity.v1"
CATALOG_FIELDS = (
    "ts_code,symbol,name,fullname,exchange,market,list_status,list_date,delist_date"
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _connect(path: Path, *, writable: bool = False) -> sqlite3.Connection:
    if writable:
        conn = sqlite3.connect(str(path))
    else:
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _universe(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        {
            "company_id": int(row["id"]),
            "name": str(row["name"] or "").strip(),
            "ticker": str(row["ticker"] or "").strip().upper(),
            "listing_status": str(row["listing_status"] or "").strip(),
            "market": str(row["market"] or "").strip(),
        }
        for row in conn.execute(
            "SELECT id,name,ticker,listing_status,market FROM company ORDER BY id"
        )
    ]


def _sha(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def universe_sha256(rows: Iterable[Mapping[str, Any]]) -> str:
    return _sha(
        [
            {
                "company_id": int(row["company_id"]),
                "name": str(row.get("name") or ""),
                "ticker": str(row.get("ticker") or ""),
                "listing_status": str(row.get("listing_status") or ""),
                "market": str(row.get("market") or ""),
            }
            for row in rows
        ]
    )


def fetch_stock_catalog() -> list[dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for status in ("L", "P", "D"):
        for raw in call_tushare(
            "stock_basic",
            {"exchange": "", "list_status": status},
            CATALOG_FIELDS,
            timeout=60,
        ):
            code = str(raw.get("ts_code") or "").strip().upper()
            if not code:
                continue
            rows[code] = {
                "ts_code": code,
                "name": str(raw.get("name") or "").strip(),
                "fullname": str(raw.get("fullname") or "").strip(),
                "exchange": str(raw.get("exchange") or "").strip(),
                "board": str(raw.get("market") or "").strip(),
                "list_status": str(raw.get("list_status") or status).strip().upper(),
                "list_date": str(raw.get("list_date") or "").strip() or None,
                "delist_date": str(raw.get("delist_date") or "").strip() or None,
            }
    return sorted(rows.values(), key=lambda row: row["ts_code"])


def _catalog_index(catalog: Iterable[Mapping[str, Any]]) -> tuple[dict[str, list[dict]], dict[str, dict]]:
    by_name: dict[str, list[dict]] = defaultdict(list)
    by_code: dict[str, dict] = {}
    for raw in catalog:
        row = dict(raw)
        code = str(row.get("ts_code") or "").strip().upper()
        if not code:
            continue
        by_code[code] = row
        for name in {str(row.get("name") or "").strip(), str(row.get("fullname") or "").strip()}:
            if name:
                by_name[name].append(row)
    return dict(by_name), by_code


def _dedupe_matches(matches: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for _, row in sorted(
        {str(row.get("ts_code") or ""): row for row in matches if row.get("ts_code")}.items()
    )]


def _summary(entries: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(entries)
    counts = Counter(str(row.get("status") or "unknown") for row in rows)
    validation = Counter(
        str(row.get("existing_validation") or "") for row in rows if row.get("existing_validation")
    )
    return {
        "total_companies": len(rows),
        "status_counts": dict(sorted(counts.items())),
        "existing_validation_counts": dict(sorted(validation.items())),
        "proposed_updates": counts.get("exact_unique_match", 0),
    }


def _compute_run_id(manifest: Mapping[str, Any]) -> str:
    payload = dict(manifest)
    payload.pop("run_id", None)
    return _sha(payload)[:20]


def build_manifest(
    db_path: Path,
    catalog: Iterable[Mapping[str, Any]],
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    catalog_rows = [dict(row) for row in catalog]
    by_name, by_code = _catalog_index(catalog_rows)
    conn = _connect(db_path)
    try:
        universe = _universe(conn)
    finally:
        conn.close()

    entries: list[dict[str, Any]] = []
    for company in universe:
        entry = dict(company)
        ticker = entry["ticker"]
        name = entry["name"]
        if ticker:
            entry["status"] = "existing_ticker"
            ts_code = ts_code_from_ticker(ticker)
            if ts_code:
                provider = by_code.get(ts_code)
                if provider is None:
                    entry["existing_validation"] = "a_share_code_not_in_catalog"
                elif name in {provider.get("name"), provider.get("fullname")}:
                    entry["existing_validation"] = "a_share_exact_name"
                    entry["provider_record"] = provider
                else:
                    entry["existing_validation"] = "a_share_name_alias_or_mismatch"
                    entry["provider_record"] = provider
            else:
                entry["existing_validation"] = "non_a_share_not_checked"
            entries.append(entry)
            continue

        matches = _dedupe_matches(by_name.get(name, []))
        if len(matches) == 1:
            provider = matches[0]
            entry.update(
                {
                    "status": "exact_unique_match",
                    "proposed_ticker": provider["ts_code"],
                    "proposed_listing_status": (
                        "a_share" if provider.get("list_status") in {"L", "P"} else "delisted"
                    ),
                    "proposed_market": "A股",
                    "provider_record": provider,
                }
            )
        elif len(matches) > 1:
            entry.update({"status": "ambiguous_exact_name", "provider_matches": matches})
        else:
            entry["status"] = "unmatched"
        entries.append(entry)

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "mode": "fetch",
        "generated_at": generated_at or _utc_now(),
        "provider": "Tushare stock_basic",
        "database_name": db_path.name,
        "catalog_count": len(catalog_rows),
        "catalog_sha256": _sha(catalog_rows),
        "universe_sha256": universe_sha256(universe),
        "companies": entries,
    }
    manifest["summary"] = _summary(entries)
    manifest["run_id"] = _compute_run_id(manifest)
    return manifest


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("mode") != "fetch":
        raise ValueError("ticker manifest schema/mode 不匹配")
    try:
        generated = datetime.fromisoformat(str(manifest.get("generated_at") or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("generated_at 非 ISO datetime") from exc
    if generated.tzinfo is None:
        raise ValueError("generated_at 必须带时区")
    companies = manifest.get("companies")
    if not isinstance(companies, list) or not companies:
        raise ValueError("manifest 未覆盖 company 全集")
    ids = [int(row.get("company_id")) for row in companies if isinstance(row, Mapping)]
    if len(ids) != len(companies) or len(ids) != len(set(ids)):
        raise ValueError("company_id 缺失或重复")
    if universe_sha256(companies) != manifest.get("universe_sha256"):
        raise ValueError("manifest company 全集哈希校验失败")
    if int(manifest.get("catalog_count") or 0) <= 0 or len(str(manifest.get("catalog_sha256") or "")) != 64:
        raise ValueError("manifest 缺少有效 Tushare catalog 摘要")
    if manifest.get("run_id") != _compute_run_id(manifest):
        raise ValueError("manifest run_id 校验失败")
    if manifest.get("summary") != _summary(companies):
        raise ValueError("manifest summary 与明细不一致")
    if int((manifest.get("summary") or {}).get("total_companies") or -1) != len(companies):
        raise ValueError("manifest company 全集计数不一致")

    for entry in companies:
        status = entry.get("status")
        if status == "exact_unique_match":
            if entry.get("ticker"):
                raise ValueError(f"company_id={entry['company_id']} 已有 ticker 却请求覆盖")
            provider = entry.get("provider_record") or {}
            if entry.get("name") not in {provider.get("name"), provider.get("fullname")}:
                raise ValueError(f"company_id={entry['company_id']} 非精确名称匹配")
            if entry.get("proposed_ticker") != provider.get("ts_code"):
                raise ValueError(f"company_id={entry['company_id']} ticker 与 provider 不一致")
            if provider.get("list_status") not in {"L", "P", "D"}:
                raise ValueError(f"company_id={entry['company_id']} list_status 非法")
        elif status not in {"existing_ticker", "ambiguous_exact_name", "unmatched"}:
            raise ValueError(f"company_id={entry['company_id']} status 非法：{status}")


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{manifest['run_id']}.tmp")
    try:
        temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp.replace(path)
    finally:
        if temp.exists():
            temp.unlink()


def load_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("ticker manifest 顶层必须是 object")
    return payload


def apply_manifest(db_path: Path, manifest: Mapping[str, Any], *, confirm_live: bool = False) -> dict[str, Any]:
    validate_manifest(manifest)
    db_path = db_path.resolve()
    if db_path == DEFAULT_DB.resolve() and not confirm_live:
        raise PermissionError("应用 live research.db 必须显式 confirm_live=True")
    conn = _connect(db_path, writable=True)
    try:
        current = _universe(conn)
        if universe_sha256(current) != manifest.get("universe_sha256"):
            raise RuntimeError("company 全集已变化，拒绝应用过期 ticker manifest")
        conn.execute("BEGIN IMMEDIATE")
        updated = 0
        for entry in manifest["companies"]:
            if entry.get("status") != "exact_unique_match":
                continue
            cursor = conn.execute(
                """UPDATE company
                   SET ticker=?, listing_status=?, market=COALESCE(NULLIF(TRIM(market),''),?)
                   WHERE id=? AND (ticker IS NULL OR TRIM(ticker)='') AND name=?""",
                (
                    entry["proposed_ticker"],
                    entry["proposed_listing_status"],
                    entry["proposed_market"],
                    int(entry["company_id"]),
                    entry["name"],
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"company_id={entry['company_id']} ticker 更新前置条件失效")
            updated += 1
        violations = list(conn.execute("PRAGMA foreign_key_check"))
        if violations:
            raise RuntimeError(f"foreign_key_check 失败：{len(violations)} 条")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"integrity_check 失败：{integrity}")
        conn.commit()
        return {"run_id": manifest["run_id"], "updated": updated, "summary": manifest["summary"]}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fetch-only", action="store_true")
    mode.add_argument("--apply-manifest", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--confirm-live", action="store_true")
    args = parser.parse_args(argv)
    db_path = args.db.resolve()
    if not db_path.exists():
        parser.error(f"数据库不存在：{db_path}")
    if args.fetch_only:
        output = (args.manifest or (ROOT / "cache" / f"company_tickers_{datetime.now():%Y%m%d_%H%M%S}.json")).resolve()
        manifest = build_manifest(db_path, fetch_stock_catalog())
        write_manifest(output, manifest)
        print(json.dumps({**manifest["summary"], "manifest": str(output), "run_id": manifest["run_id"]}, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    manifest = load_manifest(args.apply_manifest.resolve())
    result = apply_manifest(db_path, manifest, confirm_live=args.confirm_live)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
