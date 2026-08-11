from __future__ import annotations

"""Build a small deployment ZIP containing durable, referenced cache artifacts."""

import argparse
import hashlib
import json
import sqlite3
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from tools.portable_paths import canonical_path, relative_path


ROOT = Path(__file__).resolve().parents[2]
BEIJING = ZoneInfo("Asia/Shanghai")
SCHEMA_VERSION = "industry_demo.required_cache_bundle.v2"
DATABASES = (
    "data/research.db",
    "data/sentiment.db",
    "data/opportunity_lens.db",
    "data/financial.db",
)
DB_COLUMN_TOKENS = (
    "path",
    "file",
    "ref",
    "json",
    "manifest",
    "uri",
    "snapshot",
    "assumption",
)
CONFIG_SUFFIXES = {".json", ".yaml", ".yml"}
CACHE_FILE_SUFFIXES = {
    ".csv",
    ".html",
    ".htm",
    ".json",
    ".md",
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".txt",
    ".webp",
    ".xls",
    ".xlsx",
    ".yaml",
    ".yml",
}
DURABLE_MODEL_DIRECTORIES = (
    "cache/lithium_research/models",
    "cache/copper_research/models",
    "cache/lithium_battery_research/models",
    "cache/lithium_battery_research/sources",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _walk_strings(
    value: Any,
    *,
    skip_screenshot_references: bool = False,
) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, child in value.items():
            if skip_screenshot_references and "screenshot" in str(key).lower():
                continue
            yield from _walk_strings(
                child,
                skip_screenshot_references=skip_screenshot_references,
            )
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(
                child,
                skip_screenshot_references=skip_screenshot_references,
            )


def _candidate_from_string(root: Path, value: str) -> set[Path]:
    normalized = value.replace("\\", "/")
    starts: list[int] = []
    offset = 0
    while True:
        index = normalized.find("cache/", offset)
        if index < 0:
            break
        if index == 0 or normalized[index - 1] in "/:\"' =([{":
            starts.append(index)
        offset = index + len("cache/")

    found: set[Path] = set()
    for start in starts:
        tail = normalized[start:]
        direct = root / Path(tail)
        if direct.is_file():
            found.add(direct.resolve())
            continue

        # Structured JSON normally gives one path per string. For legacy text
        # values, test every plausible file-extension boundary and keep the
        # longest existing path.
        existing: list[Path] = []
        lower = tail.lower()
        for suffix in CACHE_FILE_SUFFIXES:
            search_from = 0
            while True:
                end = lower.find(suffix, search_from)
                if end < 0:
                    break
                candidate = root / Path(tail[: end + len(suffix)])
                if candidate.is_file():
                    existing.append(candidate.resolve())
                search_from = end + len(suffix)
        if existing:
            found.add(max(existing, key=lambda path: len(path.as_posix())))
    return found


def _paths_from_value(
    root: Path,
    raw: str,
    *,
    skip_screenshot_references: bool = False,
) -> set[Path]:
    values: Iterable[str]
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        values = (raw,)
    else:
        values = _walk_strings(
            parsed,
            skip_screenshot_references=skip_screenshot_references,
        )
    found: set[Path] = set()
    for value in values:
        found.update(_candidate_from_string(root, value))
    return found


def _config_paths(root: Path) -> set[Path]:
    found: set[Path] = set()
    for path in (root / "config").rglob("*"):
        if not path.is_file() or path.suffix.lower() not in CONFIG_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found.update(_paths_from_value(root, text))
    return found


def _database_paths(root: Path) -> tuple[set[Path], dict[str, int]]:
    found: set[Path] = set()
    counts: dict[str, int] = {}
    for relative in DATABASES:
        uri = (root / relative).resolve().as_uri() + "?mode=ro"
        values_seen = 0
        with closing(sqlite3.connect(uri, uri=True)) as conn:
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
                    for row in conn.execute(f'PRAGMA table_info("{table}")')
                    if "TEXT" in str(row[2]).upper()
                    and any(
                        token in str(row[1]).lower()
                        for token in DB_COLUMN_TOKENS
                    )
                ]
                for column in columns:
                    if "screenshot" in column.lower():
                        continue
                    query = (
                        f'SELECT DISTINCT "{column}" FROM "{table}" '
                        f'WHERE instr(CAST("{column}" AS TEXT), \'cache/\') > 0 '
                        f'OR instr(CAST("{column}" AS TEXT), \'cache\\\') > 0'
                    )
                    try:
                        rows = conn.execute(query)
                    except sqlite3.OperationalError:
                        continue
                    for (value,) in rows:
                        if value is None:
                            continue
                        values_seen += 1
                        found.update(
                            _paths_from_value(
                                root,
                                str(value),
                                skip_screenshot_references=True,
                            )
                        )
        counts[relative] = values_seen
    return found, counts


def _durable_model_paths(root: Path) -> set[Path]:
    found: set[Path] = set()
    for relative in DURABLE_MODEL_DIRECTORIES:
        directory = root / relative
        if not directory.is_dir():
            raise FileNotFoundError(directory)
        found.update(path.resolve() for path in directory.rglob("*") if path.is_file())
    return found


def collect_required_cache(
    root: Path,
) -> tuple[list[Path], dict[str, object]]:
    """Return the durable cache closure and its auditable manifest.

    This is shared by the standalone cache ZIP and the normal broadcast
    builder so a release cannot silently forget cache files referenced by
    configuration or one of the four live databases.
    """
    caller_root = Path(root).absolute()
    root = canonical_path(caller_root)
    config_paths = _config_paths(root)
    database_paths, database_value_counts = _database_paths(root)
    durable_paths = _durable_model_paths(root)
    paths = sorted(
        config_paths | database_paths | durable_paths,
        key=lambda path: relative_path(path, root).as_posix(),
    )
    records = [
        {
            "path": relative_path(path, root).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
            "reason": sorted(
                reason
                for reason, collection in (
                    ("config_reference", config_paths),
                    ("database_reference", database_paths),
                    ("durable_model", durable_paths),
                )
                if path in collection
            ),
        }
        for path in paths
    ]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(BEIJING).isoformat(timespec="seconds"),
        "source_root": str(root),
        "package_root": "industry_demo",
        "file_count": len(records),
        "content_bytes": sum(int(record["size"]) for record in records),
        "database_values_scanned": database_value_counts,
        "durable_model_directories": list(DURABLE_MODEL_DIRECTORIES),
        "files": records,
    }
    # Preserve the caller's path spelling at the API boundary.  In particular,
    # TemporaryDirectory on GitHub's Windows runner may return an 8.3 root even
    # though child resolution uses the long spelling.
    caller_paths = [caller_root / relative_path(path, root) for path in paths]
    return caller_paths, manifest


def build(root: Path, output: Path) -> dict[str, object]:
    root = canonical_path(root)
    output = canonical_path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(output)

    paths, manifest = collect_required_cache(root)
    with zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=6,
        allowZip64=True,
    ) as archive:
        for path in paths:
            relative = relative_path(path, root).as_posix()
            archive.write(path, f"industry_demo/{relative}")
        archive.writestr(
            "industry_demo/cache/REQUIRED_CACHE_BUNDLE_MANIFEST.json",
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        )
    with zipfile.ZipFile(output) as archive:
        bad_member = archive.testzip()
        if bad_member is not None:
            raise RuntimeError(f"cache ZIP CRC 校验失败：{bad_member}")

    result = {
        **manifest,
        "archive_path": str(output),
        "archive_size": output.stat().st_size,
        "archive_sha256": _sha256(output),
        "archive_test": "PASS",
    }
    output.with_suffix(output.suffix + ".manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.root, args.output)
    print(
        json.dumps(
            {
                "archive_path": result["archive_path"],
                "archive_size": result["archive_size"],
                "archive_sha256": result["archive_sha256"],
                "file_count": result["file_count"],
                "content_bytes": result["content_bytes"],
                "archive_test": result["archive_test"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
