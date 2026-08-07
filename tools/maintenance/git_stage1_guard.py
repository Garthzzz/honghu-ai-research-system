"""Stage-1 Git boundary inventory and non-destructive repository gates.

The tool never follows symlinks, never reads files classified as secrets/live
data, and never mutates application data.  Generated full inventories belong
under ignored ``cache/git_bootstrap``; only policy and reviewed summaries are
intended for Git.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Iterator


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = ROOT / "config" / "git_tracked_policy.json"
TEXT_SUFFIXES = {
    "", ".bat", ".cfg", ".css", ".html", ".ini", ".js", ".json",
    ".jsonl", ".md", ".ps1", ".py", ".sql", ".template", ".toml",
    ".txt", ".yaml", ".yml",
}
WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL", *{f"COM{i}" for i in range(1, 10)},
    *{f"LPT{i}" for i in range(1, 10)},
}
FORBIDDEN_ASSET_SUFFIXES = (
    ".db", ".db-wal", ".db-shm", ".db-journal", ".sqlite",
    ".sqlite-wal", ".sqlite-shm", ".sqlite-journal", ".sqlite3",
    ".sqlite3-wal", ".sqlite3-shm", ".sqlite3-journal", ".dump",
)
HIGH_CONFIDENCE_SECRET_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\bgh(?:p|o|u|s|r)_[A-Za-z0-9]{20,}\b"),
    "aws_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "bearer_token": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{24,}\b", re.I),
}
GENERIC_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)\b"
    r"\s*[:=]\s*([\"'])([^\"'\r\n]{8,})\2"
)
PLACEHOLDER_TOKENS = (
    "example", "placeholder", "changeme", "redacted", "masked", "dummy",
    "your_", "<", "${", "env:", "none", "null",
)
SQLITE_RULES = {
    "sqlite3_connect": re.compile(r"\bsqlite3\s*\.\s*connect\s*\("),
    "attach": re.compile(r"(?i)\bATTACH\s+(?:DATABASE\s+)?"),
    "pragma": re.compile(r"(?i)\bPRAGMA\s+[A-Za-z_]"),
    "begin_immediate": re.compile(r"(?i)\bBEGIN\s+IMMEDIATE\b"),
    "sqlite_conflict_dml": re.compile(
        r"(?i)\b(?:INSERT\s+OR\s+(?:REPLACE|IGNORE)|ON\s+CONFLICT\b|REPLACE\s+INTO\b)"
    ),
    "hardcoded_data_db": re.compile(r"(?i)(?:data[/\\][A-Za-z0-9_.-]+\.db\b)"),
}


@dataclass(frozen=True)
class Policy:
    raw: dict[str, Any]

    @property
    def tracked_exact(self) -> set[str]:
        return set(self.raw["tracked_exact"])

    @property
    def tracked_prefixes(self) -> tuple[str, ...]:
        return tuple(self.raw["tracked_prefixes"])

    @property
    def excluded_prefixes(self) -> tuple[str, ...]:
        return tuple(self.raw["excluded_prefixes"])


def _canonical(rel: str) -> str:
    rel = rel.replace("\\", "/")
    if rel.startswith("./"):
        rel = rel[2:]
    pure = PurePosixPath(rel)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"unsafe relative path: {rel!r}")
    return pure.as_posix()


def load_policy(path: Path) -> Policy:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != "honghu.git_boundary.v1":
        raise ValueError("unsupported Git boundary policy")
    for key in ("tracked_exact", "tracked_prefixes", "excluded_prefixes"):
        normalized: list[str] = []
        for value in raw[key]:
            canonical = _canonical(value)
            if key.endswith("prefixes"):
                canonical = canonical.rstrip("/") + "/"
            normalized.append(canonical)
        raw[key] = normalized
    return Policy(raw)


def _under(rel: str, prefixes: Iterable[str]) -> bool:
    return any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in prefixes)


def classify(rel: str, policy: Policy) -> tuple[str, str]:
    lower = rel.lower()
    suffix = Path(rel).suffix.lower()
    parts = PurePosixPath(rel).parts
    if any(part == "venv" or part.startswith(".venv") for part in parts):
        return "runtime", "local Python virtual environment"
    if rel == ".git" or rel.startswith(".git/"):
        return "runtime", "Git metadata"
    if rel.startswith("tools/dynamic/secrets/"):
        return "secret", "credential/browser state boundary"
    if rel.startswith("data/") or lower.endswith(FORBIDDEN_ASSET_SUFFIXES):
        return "live_data", "database/live data"
    if rel.startswith("backup/"):
        return "backup", "backup authority is outside Git"
    if rel.startswith("broadcast_packages/"):
        return "broadcast", "deployment package is not source"
    if rel.startswith(("papers/", "funda/")) or suffix in {".pdf", ".ppt", ".pptx", ".xls", ".xlsx"}:
        return "paper_evidence", "paper/evidence or binary research input"
    if rel.startswith("cache/") or any(part in policy.raw["excluded_name_fragments"] for part in parts):
        return "generated_cache", "runtime/generated cache"
    if rel.startswith("archive/"):
        return "history_archive", "historical archive"
    if rel.startswith(("workpapers/", "opportunity_lens/intake_requests/", "opportunity_lens/research_outputs/")):
        return "personal_context", "request/research/user content"
    if _under(rel, policy.excluded_prefixes) or any(lower.endswith(sfx.lower()) for sfx in policy.raw["excluded_suffixes"]):
        return "runtime", "explicit policy exclusion"
    selected = rel in policy.tracked_exact or _under(rel, policy.tracked_prefixes)
    if selected and suffix in set(policy.raw["tracked_extensions"]):
        if rel.startswith(("tests/",)):
            return "tracked_test", "test source"
        if rel.startswith(("openspec/", ".codex/", "skills/", "docs/", "codex_context/", "opportunity_lens/", "templates/", "审核代理/")) or rel == "AGENTS.md":
            return "tracked_governance_spec", "formal governance/specification"
        if rel.startswith(("config/", ".github/")) or rel in {"restart_viewer.bat", "requirements.txt"}:
            return "tracked_deployment_config_template", "configuration/deployment source"
        return "tracked_source", "application source"
    return "pending_review", "not covered by approved tracked policy"


def _iter_files(root: Path, policy: Policy) -> Iterator[tuple[str, Path, os.stat_result]]:
    # Keep the trailing slash for prefix matching.  Stripping it would make
    # ``.git/`` also match a legitimate sibling such as ``.github/``.
    excluded_walk = policy.excluded_prefixes
    for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        rel_dir = current_path.relative_to(root).as_posix()
        kept: list[str] = []
        for name in dirs:
            candidate = current_path / name
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            if candidate.is_symlink() or _under(rel, excluded_walk):
                continue
            kept.append(name)
        dirs[:] = kept
        for name in names:
            path = current_path / name
            if path.is_symlink():
                continue
            rel = name if rel_dir == "." else f"{rel_dir}/{name}"
            try:
                yield rel, path, path.stat()
            except OSError:
                yield rel, path, os.stat_result((0,) * 10)


def build_inventory(root: Path, policy: Policy) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    for rel, _path, stat in _iter_files(root, policy):
        category, reason = classify(rel, policy)
        size = int(stat.st_size)
        counts[category] += 1
        sizes[category] += size
        records.append({"path": rel, "size": size, "classification": category, "reason": reason})
    # Sensitive and very large excluded trees are intentionally represented as
    # boundaries rather than enumerated child paths.
    for prefix in policy.excluded_prefixes:
        target = root / prefix.rstrip("/")
        if target.exists():
            category, reason = classify(prefix.rstrip("/") + "/placeholder", policy)
            records.append({
                "path": prefix,
                "size": null_size(),
                "classification": category,
                "reason": reason + "; subtree intentionally not enumerated",
                "boundary_only": True,
            })
    return {
        "schema_version": "honghu.git_inventory.v1",
        "root": str(root),
        "policy_sha256": sha256_bytes(json.dumps(policy.raw, ensure_ascii=False, sort_keys=True).encode()),
        "counts": dict(sorted(counts.items())),
        "bytes": dict(sorted(sizes.items())),
        "records": sorted(records, key=lambda row: row["path"].lower()),
    }


def null_size() -> None:
    return None


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def tracked_allowlist(inventory: dict[str, Any]) -> list[str]:
    return [
        row["path"] for row in inventory["records"]
        if str(row["classification"]).startswith("tracked_")
    ]


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, text=True, encoding="utf-8",
        errors="replace", capture_output=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout


def staged_paths(root: Path) -> list[str]:
    output = _git(root, "diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    return sorted({_canonical(value) for value in output.split("\0") if value})


def tracked_paths(root: Path) -> list[str]:
    output = _git(root, "ls-files", "-z")
    return sorted({_canonical(value) for value in output.split("\0") if value})


def _unsafe_windows_path(rel: str) -> str | None:
    if len(rel) > 240:
        return "relative_path_over_240_chars"
    for part in PurePosixPath(rel).parts:
        stem = part.split(".", 1)[0].upper()
        if stem in WINDOWS_RESERVED:
            return "windows_reserved_name"
        if part.endswith((" ", ".")):
            return "windows_trailing_space_or_dot"
        if any(char in part for char in '<>:"|?*'):
            return "windows_unsafe_character"
    return None


def _is_reparse(path: Path, root: Path) -> bool:
    current = path
    while current != root:
        if current.is_symlink():
            return True
        try:
            attrs = current.stat(follow_symlinks=False).st_file_attributes
        except (AttributeError, OSError):
            attrs = 0
        if attrs & getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            return True
        current = current.parent
    return False


def _scan_text(path: Path, rel: str) -> list[dict[str, Any]]:
    if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > 5 * 1024 * 1024:
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return [{"path": rel, "type": "non_utf8_text_candidate", "line": None, "fingerprint": None}]
    findings: list[dict[str, Any]] = []
    for line_no, line in enumerate(text.splitlines(), 1):
        for kind, pattern in HIGH_CONFIDENCE_SECRET_PATTERNS.items():
            for match in pattern.finditer(line):
                findings.append({
                    "path": rel, "type": kind, "line": line_no,
                    "fingerprint": sha256_bytes(match.group(0).encode())[:23],
                })
        if "/static/vendor/" not in f"/{rel}":
            for match in GENERIC_SECRET_RE.finditer(line):
                value = match.group(3).strip().lower()
                if not any(token in value for token in PLACEHOLDER_TOKENS):
                    findings.append({
                        "path": rel, "type": "generic_secret_assignment", "line": line_no,
                        "fingerprint": sha256_bytes(match.group(3).encode())[:23],
                    })
    return findings


def run_gate(root: Path, policy: Policy, paths: list[str]) -> dict[str, Any]:
    allow = policy.tracked_exact
    inventory = build_inventory(root, policy)
    allow.update(tracked_allowlist(inventory))
    failures: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    extensions: Counter[str] = Counter()
    total = 0
    largest: list[tuple[int, str]] = []
    file_rows: list[dict[str, Any]] = []
    for rel in paths:
        category, _reason = classify(rel, policy)
        path = root / rel
        if rel not in allow or not category.startswith("tracked_"):
            failures.append({"path": rel, "type": "not_in_tracked_allowlist"})
            continue
        if not path.is_file():
            failures.append({"path": rel, "type": "missing_or_not_regular_file"})
            continue
        if _is_reparse(path, root):
            failures.append({"path": rel, "type": "symlink_or_reparse_path"})
        unsafe = _unsafe_windows_path(rel)
        if unsafe:
            failures.append({"path": rel, "type": unsafe})
        lower = rel.lower()
        if lower.endswith(FORBIDDEN_ASSET_SUFFIXES):
            failures.append({"path": rel, "type": "database_or_dump_asset"})
        size = path.stat().st_size
        total += size
        extensions[path.suffix.lower() or "<none>"] += 1
        largest.append((size, rel))
        file_rows.append({
            "path": rel,
            "size": size,
            "classification": category,
            "sha256": sha256_file(path),
        })
        if size > int(policy.raw["large_file_block_bytes"]) and rel not in policy.raw["explicit_large_file_allowlist"]:
            failures.append({"path": rel, "type": "large_file_block", "size": size})
        elif size > int(policy.raw["large_file_warning_bytes"]):
            warnings.append({"path": rel, "type": "large_file_warning", "size": size})
        failures.extend(_scan_text(path, rel))
    return {
        "schema_version": "honghu.git_gate.v1",
        "status": "blocked" if failures else "pass",
        "file_count": len(paths),
        "total_bytes": total,
        "largest_files": [
            {"path": rel, "size": size} for size, rel in sorted(largest, reverse=True)[:25]
        ],
        "extension_counts": dict(sorted(extensions.items())),
        "files": file_rows,
        "failures": failures,
        "warnings": warnings,
    }


def _function_ranges(source: str) -> list[tuple[int, int, str]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    rows: list[tuple[int, int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            rows.append((node.lineno, getattr(node, "end_lineno", node.lineno), node.name))
    return rows


def sqlite_inventory(root: Path, paths: list[str]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    counts: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for rel in paths:
        path = root / rel
        if path.suffix.lower() != ".py" or rel.startswith("tests/"):
            continue
        try:
            source = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        ranges = _function_ranges(source)
        for line_no, line in enumerate(source.splitlines(), 1):
            for rule, pattern in SQLITE_RULES.items():
                if not pattern.search(line):
                    continue
                symbol = "<module>"
                candidates = [(end - start, name) for start, end, name in ranges if start <= line_no <= end]
                if candidates:
                    symbol = min(candidates)[1]
                fingerprint = sha256_bytes(re.sub(r"\s+", " ", line.strip()).encode())
                records.append({
                    "path": rel,
                    "rule": rule,
                    "line": line_no,
                    "writer_operation_candidate": symbol,
                    "fingerprint": fingerprint,
                })
                counts[rel][rule] += 1
    return {
        "schema_version": "honghu.sqlite_dependency_baseline.v1",
        "definition": {
            "writer": "domain mutation path/write endpoint/writer operation/transaction contract",
            "not_equivalent_to": "whole process, Viewer application, or scheduled-task process",
            "phase1_scope": "static operation-level ratchet; no cutover-unit ownership assignment",
        },
        "counts_by_file_rule": {
            path: dict(sorted(rule_counts.items())) for path, rule_counts in sorted(counts.items())
        },
        "records": sorted(records, key=lambda row: (row["path"], row["line"], row["rule"])),
    }


def check_sqlite_ratchet(current: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    applied_exceptions: list[dict[str, Any]] = []
    old = baseline.get("counts_by_file_rule", {})
    exceptions: dict[tuple[str, str], dict[str, Any]] = {}
    required_exception_fields = (
        "path",
        "rule",
        "max_count",
        "domain",
        "reason",
        "owner",
        "future_cutover_unit_candidate",
        "sunset_condition",
    )
    for item in baseline.get("documented_exceptions", []):
        if not isinstance(item, dict) or not all(item.get(field) not in (None, "") for field in required_exception_fields):
            continue
        exceptions[(str(item["path"]), str(item["rule"]))] = item
    for path, rules in current.get("counts_by_file_rule", {}).items():
        for rule, count in rules.items():
            allowed = int(old.get(path, {}).get(rule, 0))
            exception = exceptions.get((path, rule))
            if exception is not None:
                exception_limit = int(exception["max_count"])
                if exception_limit > allowed:
                    allowed = exception_limit
                    applied_exceptions.append({
                        "path": path,
                        "rule": rule,
                        "baseline": int(old.get(path, {}).get(rule, 0)),
                        "exception_limit": exception_limit,
                        "current": int(count),
                        "domain": exception["domain"],
                        "owner": exception["owner"],
                        "sunset_condition": exception["sunset_condition"],
                    })
            if int(count) > allowed:
                failures.append({"path": path, "rule": rule, "baseline": allowed, "current": count})
    return {
        "status": "blocked" if failures else "pass",
        "failures": failures,
        "applied_exceptions": sorted(applied_exceptions, key=lambda row: (row["path"], row["rule"])),
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("inventory")
    inv.add_argument("--output", type=Path, required=True)
    inv.add_argument("--allowlist-output", type=Path)
    gate = sub.add_parser("gate")
    gate.add_argument("--scope", choices=("staged", "tracked", "allowlist"), required=True)
    gate.add_argument("--output", type=Path, required=True)
    sql = sub.add_parser("sqlite-baseline")
    sql.add_argument("--output", type=Path, required=True)
    ratchet = sub.add_parser("sqlite-ratchet")
    ratchet.add_argument("--baseline", type=Path, required=True)
    ratchet.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    policy = load_policy(args.policy.resolve())
    inventory = build_inventory(root, policy)
    allowlist = tracked_allowlist(inventory)
    if args.command == "inventory":
        write_json(args.output, inventory)
        if args.allowlist_output:
            args.allowlist_output.parent.mkdir(parents=True, exist_ok=True)
            args.allowlist_output.write_text("\n".join(allowlist) + "\n", encoding="utf-8")
        print(json.dumps({"status": "pass", "counts": inventory["counts"], "allowlist": len(allowlist)}, ensure_ascii=False))
        return 0
    if args.command == "gate":
        if args.scope == "staged":
            paths = staged_paths(root)
        elif args.scope == "tracked":
            paths = tracked_paths(root)
        else:
            paths = allowlist
        result = run_gate(root, policy, paths)
        write_json(args.output, result)
        print(json.dumps({k: result[k] for k in ("status", "file_count", "total_bytes")}, ensure_ascii=False))
        return 1 if result["status"] != "pass" else 0
    current = sqlite_inventory(root, tracked_paths(root) if (root / ".git").exists() else allowlist)
    if args.command == "sqlite-baseline":
        write_json(args.output, current)
        print(json.dumps({"status": "pass", "records": len(current["records"])}, ensure_ascii=False))
        return 0
    baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    result = check_sqlite_ratchet(current, baseline)
    write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result["status"] != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
