from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sqlite3
import subprocess
import tokenize
from io import StringIO
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "honghu.sqlite_dependency_inventory.v1"
SQLITE_RULES: dict[str, re.Pattern[str]] = {
    "sqlite3_connect": re.compile(r"\bsqlite3\s*\.\s*connect\s*\("),
    "attach": re.compile(r"\bATTACH\s+(?:DATABASE\s+)?", re.IGNORECASE),
    "pragma": re.compile(r"\bPRAGMA\b", re.IGNORECASE),
    "begin_immediate": re.compile(r"\bBEGIN\s+IMMEDIATE\b", re.IGNORECASE),
    "sqlite_conflict_dml": re.compile(
        r"\b(?:INSERT\s+OR\s+(?:IGNORE|REPLACE)|ON\s+CONFLICT|REPLACE\s+INTO)\b",
        re.IGNORECASE,
    ),
}
DATABASE_NAMES = ("research.db", "financial.db", "opportunity_lens.db", "sentiment.db")
DML_TARGET = re.compile(
    r"\b(?:INSERT(?:\s+OR\s+\w+)?\s+INTO|REPLACE\s+INTO|UPDATE|DELETE\s+FROM)\s+"
    r"(?P<table>(?:[\"`\[]?[A-Za-z_][\w]*[\"`\]]?\.)?[\"`\[]?[A-Za-z_][\w]*[\"`\]]?)",
    re.IGNORECASE,
)
DDL = re.compile(r"\b(?:CREATE|ALTER|DROP)\s+(?:TABLE|INDEX|VIEW|TRIGGER)\b", re.IGNORECASE)
SELECT = re.compile(r"\bSELECT\b", re.IGNORECASE)
ROUTE = re.compile(r"@app\.route\(\s*[rRuU]?[\"'](?P<route>[^\"']+)")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_files(root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z"], cwd=root, stderr=subprocess.DEVNULL
    )
    return [root / item.decode("utf-8") for item in output.split(b"\0") if item]


def _git_head(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def _domain(path: str) -> str:
    if path.startswith("tools/financial/"):
        return "financial"
    if path.startswith("tools/opportunity_lens/") or path.startswith("opportunity_lens/"):
        return "opportunity"
    if path.startswith("tools/sentiment/"):
        return "sentiment"
    if path.startswith("tools/dynamic/"):
        return "dynamic"
    if path.startswith("tools/viewer/"):
        return "viewer"
    if path.startswith("tools/pipeline/") or path.startswith("tools/research_core/"):
        return "research"
    if path.startswith("tools/migrations/") or path.startswith("tools/migrate/"):
        return "legacy_migration"
    if path.startswith("tools/maintenance/"):
        return "operations"
    if path.startswith("tools/release/"):
        return "release"
    if path.startswith("tests/"):
        return "test"
    return "other"


def _lifecycle(path: str) -> str:
    if path.startswith("tests/"):
        return "test_only"
    if path.startswith(("tools/migrations/", "tools/migrate/")):
        return "legacy_migration"
    if path.startswith("tools/maintenance/apply_run"):
        return "one_shot_maintenance"
    return "active_or_callable"


def _default_unit(domain: str) -> str:
    return {
        "financial": "financial_data",
        "opportunity": "opportunity_lens",
        "sentiment": "sentiment_analytics",
        "dynamic": "dynamic_intelligence",
        "viewer": "viewer_access_boundary",
        "research": "research_publication",
        "operations": "operations_governance",
        "release": "release_governance",
        "legacy_migration": "legacy_migration_archive",
        "test": "test_fixture_only",
    }.get(domain, "manual_classification_required")


def _function_ranges(tree: ast.AST) -> list[tuple[int, int, str]]:
    ranges: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            ranges.append((node.lineno, getattr(node, "end_lineno", node.lineno), node.name))
    return sorted(ranges, key=lambda item: (item[1] - item[0], item[0]))


def _function_for_line(ranges: Iterable[tuple[int, int, str]], line: int) -> str:
    for start, end, name in ranges:
        if start <= line <= end:
            return name
    return "<module>"


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _column_number(text: str, offset: int) -> int:
    last_newline = text.rfind("\n", 0, offset)
    return offset if last_newline < 0 else offset - last_newline - 1


def _normalise_table(value: str) -> str:
    return value.replace('"', "").replace("`", "").replace("[", "").replace("]", "")


def _without_comments(text: str) -> str:
    """Remove Python comments while preserving line positions for SQL evidence."""

    lines = text.splitlines(keepends=True)
    try:
        for token in tokenize.generate_tokens(StringIO(text).readline):
            if token.type != tokenize.COMMENT:
                continue
            line_index = token.start[0] - 1
            start, end = token.start[1], token.end[1]
            lines[line_index] = lines[line_index][:start] + (" " * (end - start)) + lines[line_index][end:]
    except (tokenize.TokenError, IndentationError):
        return text
    return "".join(lines)


def _without_docstrings(text: str, tree: ast.AST) -> str:
    lines = text.splitlines(keepends=True)
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not body or not isinstance(body, list):
            continue
        first = body[0]
        if not (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            continue
        start = first.lineno - 1
        end = getattr(first, "end_lineno", first.lineno) - 1
        for index in range(start, end + 1):
            newline = "\n" if lines[index].endswith("\n") else ""
            lines[index] = (" " * (len(lines[index]) - len(newline))) + newline
    return "".join(lines)


def _surface_types(relative: str, text: str) -> list[str]:
    surfaces: set[str] = set()
    if relative.startswith("tools/viewer/"):
        surfaces.add("viewer_route")
    if relative.startswith(("tools/dynamic/", "tools/sentiment/")):
        surfaces.add("scheduled_or_continuous_task")
    if any(token in relative for token in ("publisher", "publication", "ingest", "db_writer", "loader")):
        surfaces.add("publisher_or_ingest")
    if "if __name__" in text and "__main__" in text:
        surfaces.add("cli")
    if not surfaces:
        surfaces.add("library_or_script")
    return sorted(surfaces)


def scan_file(root: Path, path: Path) -> dict[str, Any] | None:
    relative = path.relative_to(root).as_posix()
    if path.suffix.lower() != ".py":
        return None
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8-sig")
    scan_text = _without_comments(text)
    hits: list[dict[str, Any]] = []
    try:
        tree = ast.parse(text, filename=relative)
        ranges = _function_ranges(tree)
        scan_text = _without_docstrings(scan_text, tree)
    except SyntaxError:
        ranges = []
    for rule, pattern in SQLITE_RULES.items():
        for match in pattern.finditer(scan_text):
            line = _line_number(scan_text, match.start())
            column = _column_number(scan_text, match.start())
            function = _function_for_line(ranges, line)
            hits.append(
                {
                    "rule": rule,
                    "line": line,
                    "column": column,
                    "operation": function,
                    "operation_id": f"{relative}:{function}:{rule}:{line}:{column}",
                }
            )
    referenced_databases = sorted(name for name in DATABASE_NAMES if name in scan_text)
    dml_hits: list[dict[str, Any]] = []
    for match in DML_TARGET.finditer(scan_text):
        line = _line_number(scan_text, match.start())
        column = _column_number(scan_text, match.start())
        operation = _function_for_line(ranges, line)
        dml_hits.append(
            {
                "rule": "dml",
                "line": line,
                "column": column,
                "operation": operation,
                "target": _normalise_table(match.group("table")),
                "operation_id": f"{relative}:{operation}:dml:{line}:{column}",
            }
        )
    dml_targets = sorted({hit["target"] for hit in dml_hits})
    has_ddl = bool(DDL.search(scan_text))
    has_select = bool(SELECT.search(scan_text))
    if not hits and not referenced_databases and not dml_targets:
        return None
    access = "write" if dml_targets or has_ddl else "read" if has_select or hits else "unknown"
    domain = _domain(relative)
    writer_hits = dml_hits + [
        hit for hit in hits if hit["rule"] in {"begin_immediate", "sqlite_conflict_dml"}
    ]
    transaction_functions = sorted({hit["operation"] for hit in writer_hits})
    return {
        "path": relative,
        "source_sha256": _sha256(raw),
        "domain": domain,
        "lifecycle": _lifecycle(relative),
        "access": access,
        "sqlite_semantics": sorted({hit["rule"] for hit in hits}),
        "database_references": referenced_databases,
        "attach_present": any(hit["rule"] == "attach" for hit in hits),
        "dml_targets": dml_targets,
        "ddl_present": has_ddl,
        "writer_operations": sorted(writer_hits, key=lambda item: (item["line"], item["rule"])),
        "transaction_boundaries": [f"{relative}:{name}" for name in transaction_functions],
        "surface_types": _surface_types(relative, text),
        "routes": sorted({match.group("route") for match in ROUTE.finditer(scan_text)}),
        "candidate_cutover_unit": _default_unit(domain),
        "authoritative_backend": "sqlite_transition",
        "migration_state": "S0",
        "review_status": "manual_review_required" if access == "write" else "machine_classified",
    }


def build_inventory(root: Path) -> dict[str, Any]:
    records = [record for path in _git_files(root) if (record := scan_file(root, path))]
    records.sort(key=lambda row: row["path"])
    operation_ids = [op["operation_id"] for row in records for op in row["writer_operations"]]
    duplicates = sorted(key for key, count in Counter(operation_ids).items() if count > 1)
    summary = {
        "file_count": len(records),
        "production_file_count": sum(row["lifecycle"] != "test_only" for row in records),
        "write_file_count": sum(row["access"] == "write" for row in records),
        "writer_operation_count": len(operation_ids),
        "attach_file_count": sum(bool(row["attach_present"]) for row in records),
        "manual_review_file_count": sum(row["review_status"] == "manual_review_required" for row in records),
        "counts_by_domain": dict(sorted(Counter(row["domain"] for row in records).items())),
        "counts_by_rule": dict(
            sorted(Counter(rule for row in records for rule in row["sqlite_semantics"]).items())
        ),
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "source_commit": _git_head(root),
        "definition": {
            "writer": "domain mutation path/write endpoint/writer operation/transaction contract",
            "not_equivalent_to": "whole process, Viewer application, or scheduled-task process",
            "scope": "tracked Python sources and tests; live database contents are not embedded",
            "classification_limit": "static evidence; write paths remain manual-review items until code and transaction semantics are audited",
        },
        "summary": summary,
        "validation": {
            "duplicate_operation_ids": duplicates,
            "all_writers_have_candidate_owner": all(
                row["candidate_cutover_unit"] for row in records if row["access"] == "write"
            ),
        },
        "files": records,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["inventory_sha256"] = _sha256(canonical.encode("utf-8"))
    return payload


def audit_live_schema(data_root: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"schema_version": "honghu.sqlite_live_schema_audit.v1", "databases": {}}
    for name in DATABASE_NAMES:
        path = (data_root / name).resolve()
        connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
        try:
            connection.execute("PRAGMA query_only=ON")
            tables = []
            for table_name, sql in connection.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ):
                tables.append(
                    {
                        "name": table_name,
                        "columns": [row[1] for row in connection.execute(f'PRAGMA table_info("{table_name}")')],
                        "row_count": int(connection.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]),
                        "schema_sha256": _sha256(str(sql or "").encode("utf-8")),
                    }
                )
            result["databases"][name] = {
                "user_version": int(connection.execute("PRAGMA user_version").fetchone()[0]),
                "tables": tables,
            }
        finally:
            connection.close()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live-data-root", type=Path)
    args = parser.parse_args(argv)
    payload = audit_live_schema(args.live_data_root) if args.live_data_root else build_inventory(args.root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "sha256": _sha256(args.output.read_bytes())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
