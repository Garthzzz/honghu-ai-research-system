from __future__ import annotations

"""Audit or migrate overlong paper filenames and all live path references."""

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from tools.pipeline.paper_paths import (
    MAX_FILENAME_CHARS,
    MAX_PROJECT_RELATIVE_PATH_CHARS,
    filesystem_path,
    paper_path_violations,
    proposed_paper_path,
)


ROOT = Path(__file__).resolve().parents[2]
BEIJING = ZoneInfo("Asia/Shanghai")
SCHEMA_VERSION = "industry_demo.paper_path_migration.v2"
DATABASES = (
    "data/research.db",
    "data/sentiment.db",
    "data/opportunity_lens.db",
    "data/financial.db",
)
TEXT_SUFFIXES = {
    ".bat",
    ".css",
    ".csv",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sql",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
TEXT_ROOTS = ("config", "docs", "opportunity_lens", "templates", "tools", "cache")
SKIP_TEXT_PREFIXES = (
    "archive/",
    "backup/",
    "broadcast_packages/",
    "cache/broadcast_validation/",
    "cache/context/",
    "cache/paper_path_migration/",
    "cache/project_cleanup_",
    "cache/research_content/",
    "cache/tar_safe_test_",
    "cache/tarv",
    "cache/v15",
    "cache/zip_safe_test_",
    "tools/dynamic/secrets/",
    "tools/viewer/static/vendor/",
)
DB_COLUMN_TOKENS = ("path", "uri", "json", "manifest", "file", "ref")


@dataclass(frozen=True)
class Rename:
    old: str
    new: str
    size: int
    sha256: str
    action: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with filesystem_path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _mapping(root: Path) -> list[Rename]:
    rows: list[Rename] = []
    targets: set[str] = set()
    for source in paper_path_violations(root / "papers", project_root=root):
        target = proposed_paper_path(source, project_root=root)
        old = source.relative_to(root).as_posix()
        new = target.relative_to(root).as_posix()
        source_hash = _sha256(source)
        action = "rename"
        if new in targets:
            raise FileExistsError(f"多个待迁移研报指向同一目标路径：{new}")
        if target.exists() and target != source:
            target_hash = _sha256(target)
            if target_hash != source_hash:
                raise FileExistsError(
                    "研报改名目标已存在且内容不同，拒绝覆盖："
                    f"{new}；旧文件 sha256={source_hash}；"
                    f"目标文件 sha256={target_hash}"
                )
            # Incremental deployments can leave a legacy long-name file beside
            # the already-migrated safe-name copy. Keep the safe path, remove
            # only the byte-identical legacy copy, and rewrite live references.
            action = "deduplicate"
        targets.add(new)
        rows.append(
            Rename(
                old,
                new,
                filesystem_path(source).stat().st_size,
                source_hash,
                action,
            )
        )
    return rows


def _replacement_pairs(root: Path, rows: Iterable[Rename]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for row in rows:
        old_path = root / Path(row.old)
        new_path = root / Path(row.new)
        variants = (
            (str(old_path), str(new_path)),
            (old_path.as_posix(), new_path.as_posix()),
            (row.old.replace("/", "\\"), row.new.replace("/", "\\")),
            (row.old, row.new),
            (Path(row.old).name, Path(row.new).name),
        )
        pairs.extend(variants)
    # Replace longer values first so a basename cannot consume part of a full path.
    unique = dict(pairs)
    return sorted(unique.items(), key=lambda item: len(item[0]), reverse=True)


def _replace(text: str, pairs: list[tuple[str, str]]) -> str:
    updated = text
    for old, new in pairs:
        updated = updated.replace(old, new)
    return updated


def _candidate_text_files(root: Path) -> Iterable[Path]:
    for top in TEXT_ROOTS:
        base = root / top
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
                continue
            relative = path.relative_to(root).as_posix()
            if any(relative.startswith(prefix) for prefix in SKIP_TEXT_PREFIXES):
                continue
            if path.stat().st_size <= 30_000_000:
                yield path
    for path in root.iterdir():
        if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES:
            yield path


def _text_changes(
    root: Path,
    pairs: list[tuple[str, str]],
) -> dict[Path, tuple[bytes, bytes]]:
    changes: dict[Path, tuple[bytes, bytes]] = {}
    for path in _candidate_text_files(root):
        raw = path.read_bytes()
        try:
            original = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        updated = _replace(original, pairs)
        if updated != original:
            changes[path] = (raw, updated.encode("utf-8"))
    return changes


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _database_candidates(
    conn: sqlite3.Connection,
) -> Iterable[tuple[str, str, int, str]]:
    tables = [
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    for table in tables:
        columns = [
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({_quoted(table)})")
            if "TEXT" in str(row[2]).upper()
            and any(token in str(row[1]).lower() for token in DB_COLUMN_TOKENS)
        ]
        for column in columns:
            query = (
                f"SELECT rowid, {_quoted(column)} FROM {_quoted(table)} "
                f"WHERE instr(CAST({_quoted(column)} AS TEXT), 'papers/') > 0 "
                f"OR instr(CAST({_quoted(column)} AS TEXT), 'papers\\') > 0"
            )
            try:
                for rowid, value in conn.execute(query):
                    yield table, column, int(rowid), str(value or "")
            except sqlite3.OperationalError:
                continue


def _database_plan(
    root: Path,
    pairs: list[tuple[str, str]],
) -> dict[str, list[dict[str, object]]]:
    plan: dict[str, list[dict[str, object]]] = {}
    for relative in DATABASES:
        uri = (root / relative).resolve().as_uri() + "?mode=ro"
        changes: list[dict[str, object]] = []
        with closing(sqlite3.connect(uri, uri=True)) as conn:
            for table, column, rowid, original in _database_candidates(conn):
                updated = _replace(original, pairs)
                if updated != original:
                    changes.append(
                        {
                            "table": table,
                            "column": column,
                            "rowid": rowid,
                            "old_sha256": hashlib.sha256(
                                original.encode("utf-8")
                            ).hexdigest(),
                            "new_value": updated,
                        }
                    )
        plan[relative] = changes
    return plan


def _sqlite_snapshot(source: Path, target: Path) -> dict[str, object]:
    target.parent.mkdir(parents=True, exist_ok=True)
    uri = source.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as source_conn:
        with closing(sqlite3.connect(target)) as target_conn:
            source_conn.backup(target_conn)
            target_conn.commit()
    with closing(sqlite3.connect(target)) as conn:
        integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    if integrity != "ok" or foreign_keys:
        raise RuntimeError(
            f"SQLite 安全快照校验失败：{source}; "
            f"integrity={integrity}, foreign_keys={foreign_keys}"
        )
    return {
        "path": str(source),
        "size": target.stat().st_size,
        "sha256": _sha256(target),
        "integrity_check": integrity,
        "foreign_key_issues": foreign_keys,
    }


def _restore_sqlite_snapshot(source: Path, target: Path) -> None:
    uri = source.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=30)) as source_conn:
        with closing(sqlite3.connect(target, timeout=30)) as target_conn:
            source_conn.backup(target_conn)
            target_conn.commit()


def _build_backup(
    *,
    root: Path,
    backup: Path,
    rows: list[Rename],
    text_changes: dict[Path, tuple[bytes, bytes]],
) -> dict[str, object]:
    root = root.resolve()
    backup = backup.resolve()
    if root == backup or root in backup.parents:
        raise ValueError("迁移安全副本必须位于项目目录之外")
    if "industry_demo" not in backup.name.lower():
        raise ValueError("迁移安全副本目录名必须包含 industry_demo")
    if backup.exists():
        raise FileExistsError(backup)
    backup.mkdir(parents=True)
    copied: list[dict[str, object]] = []
    for relative in sorted(
        {row.old for row in rows}
        | {path.relative_to(root).as_posix() for path in text_changes}
    ):
        source = root / Path(relative)
        target = backup / "files" / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(filesystem_path(source), filesystem_path(target))
        copied.append(
            {
                "path": relative,
                "size": filesystem_path(target).stat().st_size,
                "sha256": _sha256(target),
            }
        )
    databases = [
        _sqlite_snapshot(root / relative, backup / "sqlite" / relative)
        for relative in DATABASES
    ]
    return {"files": copied, "databases": databases}


def _atomic_write(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.paper-path-migration.tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def _apply_databases(
    root: Path,
    plan: dict[str, list[dict[str, object]]],
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for relative, changes in plan.items():
        if not changes:
            counts[relative] = 0
            continue
        with closing(sqlite3.connect(root / relative, timeout=30)) as conn:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN IMMEDIATE")
            try:
                for change in changes:
                    table = _quoted(str(change["table"]))
                    column = _quoted(str(change["column"]))
                    rowid = int(change["rowid"])
                    current = str(
                        conn.execute(
                            f"SELECT {column} FROM {table} WHERE rowid=?",
                            (rowid,),
                        ).fetchone()[0]
                        or ""
                    )
                    current_hash = hashlib.sha256(current.encode("utf-8")).hexdigest()
                    if current_hash != change["old_sha256"]:
                        raise RuntimeError(
                            f"数据库迁移前值已变化：{relative} "
                            f"{change['table']}.{change['column']} rowid={rowid}"
                        )
                    conn.execute(
                        f"UPDATE {table} SET {column}=? WHERE rowid=?",
                        (change["new_value"], rowid),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = len(conn.execute("PRAGMA foreign_key_check").fetchall())
            if integrity != "ok" or foreign_keys:
                raise RuntimeError(
                    f"迁移后数据库校验失败：{relative}; "
                    f"integrity={integrity}, foreign_keys={foreign_keys}"
                )
        counts[relative] = len(changes)
    return counts


def build_plan(root: Path) -> dict[str, object]:
    root = root.resolve()
    rows = _mapping(root)
    pairs = _replacement_pairs(root, rows)
    text_changes = _text_changes(root, pairs)
    database_plan = _database_plan(root, pairs)
    return {
        "rows": rows,
        "pairs": pairs,
        "text_changes": text_changes,
        "database_plan": database_plan,
    }


def render_plan(root: Path, plan: dict[str, object]) -> dict[str, object]:
    rows: list[Rename] = plan["rows"]  # type: ignore[assignment]
    text_changes: dict[Path, tuple[bytes, bytes]] = plan["text_changes"]  # type: ignore[assignment]
    database_plan: dict[str, list[dict[str, object]]] = plan["database_plan"]  # type: ignore[assignment]
    return {
        "schema_version": SCHEMA_VERSION,
        "project_root": str(root.resolve()),
        "max_filename_chars": MAX_FILENAME_CHARS,
        "max_project_relative_path_chars": MAX_PROJECT_RELATIVE_PATH_CHARS,
        "rename_count": len(rows),
        "renames": [
            {
                "old": row.old,
                "new": row.new,
                "size": row.size,
                "sha256": row.sha256,
                "action": row.action,
            }
            for row in rows
        ],
        "text_file_changes": sorted(
            path.relative_to(root).as_posix() for path in text_changes
        ),
        "database_change_count": {
            relative: len(changes)
            for relative, changes in database_plan.items()
        },
    }


def execute(root: Path, backup: Path) -> dict[str, object]:
    root = root.resolve()
    plan = build_plan(root)
    rendered = render_plan(root, plan)
    rows: list[Rename] = plan["rows"]  # type: ignore[assignment]
    pairs: list[tuple[str, str]] = plan["pairs"]  # type: ignore[assignment]
    text_changes: dict[Path, tuple[bytes, bytes]] = plan["text_changes"]  # type: ignore[assignment]
    database_plan: dict[str, list[dict[str, object]]] = plan["database_plan"]  # type: ignore[assignment]
    if not rows:
        return {**rendered, "status": "no_changes"}

    backup_result = _build_backup(
        root=root,
        backup=backup,
        rows=rows,
        text_changes=text_changes,
    )
    (backup / "paper_path_migration_backup_manifest.json").write_text(
        json.dumps(
            {
                **rendered,
                "status": "backup_ready",
                "backup_path": str(backup.resolve()),
                "backup": backup_result,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    renamed: list[tuple[Path, Path]] = []
    deduplicated: list[Path] = []
    written: list[tuple[Path, bytes]] = []
    try:
        for row in rows:
            source = root / Path(row.old)
            target = root / Path(row.new)
            if row.action == "deduplicate":
                if not filesystem_path(target).is_file():
                    raise FileNotFoundError(
                        f"准备合并重复文件时安全目标已不存在：{row.new}"
                    )
                if _sha256(source) != row.sha256 or _sha256(target) != row.sha256:
                    raise RuntimeError(
                        f"准备合并重复文件时内容已变化，停止迁移：{row.old}"
                    )
                filesystem_path(source).unlink()
                deduplicated.append(source)
            else:
                os.replace(filesystem_path(source), filesystem_path(target))
                renamed.append((source, target))
        for path, (original, updated) in text_changes.items():
            _atomic_write(path, updated)
            written.append((path, original))
        database_counts = _apply_databases(root, database_plan)
        remaining = paper_path_violations(root / "papers", project_root=root)
        if remaining:
            raise RuntimeError(f"迁移后仍有 {len(remaining)} 个不安全研报路径")
        post_plan = build_plan(root)
        if post_plan["rows"]:
            raise RuntimeError("迁移后重新审计仍产生改名计划")
    except Exception:
        for relative in DATABASES:
            snapshot = backup / "sqlite" / relative
            if snapshot.is_file():
                _restore_sqlite_snapshot(snapshot, root / relative)
        for path, original in reversed(written):
            _atomic_write(path, original)
        for source in reversed(deduplicated):
            backup_source = backup / "files" / source.relative_to(root)
            if (
                filesystem_path(backup_source).is_file()
                and not filesystem_path(source).exists()
            ):
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(
                    filesystem_path(backup_source),
                    filesystem_path(source),
                )
        for source, target in reversed(renamed):
            if (
                filesystem_path(target).exists()
                and not filesystem_path(source).exists()
            ):
                os.replace(filesystem_path(target), filesystem_path(source))
        raise

    result = {
        **rendered,
        "status": "applied",
        "applied_at": datetime.now(BEIJING).isoformat(timespec="seconds"),
        "backup_path": str(backup.resolve()),
        "backup": backup_result,
        "database_updates": database_counts,
        "remaining_violations": 0,
    }
    manifest = backup / "paper_path_migration_manifest.json"
    manifest.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.apply:
        if args.backup_dir is None:
            parser.error("--apply 必须显式提供项目外 --backup-dir")
        result = execute(root, args.backup_dir)
    else:
        result = render_plan(root, build_plan(root))
        result["status"] = "dry_run"
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
