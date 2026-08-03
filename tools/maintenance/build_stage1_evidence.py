"""Build public-safe Stage-1 evidence for the exact checked-out Git commit.

The output is generated after checkout (locally or in GitHub Actions), so it can
bind inventory and specification hashes to a real commit without attempting to
embed a commit's SHA inside that same commit.  Only tracked files are examined;
ignored runtime data, databases, papers, credentials, and user content are not
opened.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHANGE = "openspec/changes/github-vm-dual-node-operations"
SPEC_GLOB = f"{CHANGE}/specs/*/spec.md"
PENDING_INDEX = "config/pending_review_index.json"


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", *args], cwd=root, text=True, encoding="utf-8"
    ).strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tracked_files(root: Path) -> list[str]:
    # ``git ls-files`` quotes non-ASCII names by default on Windows.  NUL
    # framing plus ``core.quotepath=false`` preserves the real repository
    # paths and is also safe for whitespace/newlines in names.
    raw = subprocess.check_output(
        ["git", "-c", "core.quotepath=false", "ls-files", "-z"], cwd=root
    )
    return [item for item in raw.decode("utf-8").split("\0") if item]


def _kind(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".py":
        return "python"
    if suffix == ".md":
        return "markdown"
    if suffix in {".json", ".jsonl"}:
        return "json"
    if suffix in {".yaml", ".yml"}:
        return "yaml"
    if suffix in {".html", ".css", ".js"}:
        return suffix[1:]
    if suffix in {".woff", ".woff2", ".ttf"}:
        return "font"
    return suffix[1:] or "no_extension"


def build_evidence(root: Path = ROOT) -> dict:
    root = root.resolve()
    commit = os.environ.get("GITHUB_SHA") or _git(root, "rev-parse", "HEAD")
    branch = (
        os.environ.get("GITHUB_REF_NAME")
        or _git(root, "branch", "--show-current")
        or "detached-head"
    )
    tracked = _tracked_files(root)
    records = []
    type_counts: Counter[str] = Counter()
    total_bytes = 0
    largest = {"path": "", "bytes": -1}
    for rel in tracked:
        path = root / rel
        size = path.stat().st_size
        total_bytes += size
        type_counts[_kind(rel)] += 1
        if size > largest["bytes"]:
            largest = {"path": rel, "bytes": size}
        records.append({"path": rel, "bytes": size, "sha256": _sha256(path)})

    spec_paths = sorted(root.glob(SPEC_GLOB))
    specs = [
        {"path": path.relative_to(root).as_posix(), "sha256": _sha256(path)}
        for path in spec_paths
    ]
    pending_path = root / PENDING_INDEX
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    pending_count = len(pending.get("records", []))

    return {
        "schema_version": "honghu.stage1_runtime_evidence.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "binding": {
            "repository": "Garthzzz/honghu-ai-research-system",
            "branch_or_ref": branch,
            "commit_sha": commit,
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        },
        "tracked_inventory": {
            "file_count": len(tracked),
            "total_bytes": total_bytes,
            "largest_object": largest,
            "type_distribution": dict(sorted(type_counts.items())),
            "records": records,
        },
        "capability_specs": specs,
        "pending_review": {
            "index_path": PENDING_INDEX,
            "index_sha256": _sha256(pending_path),
            "record_count": pending_count,
            "contains_raw_paths": False,
        },
    }


def write_evidence(evidence: dict, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "final_inventory.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    identity = {
        "schema_version": "honghu.capability_spec_identity.runtime.v1",
        "generated_at": evidence["generated_at"],
        "binding": evidence["binding"],
        "specs": evidence["capability_specs"],
    }
    (output_dir / "capability_spec_identities.runtime.json").write_text(
        json.dumps(identity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    inv = evidence["tracked_inventory"]
    pending = evidence["pending_review"]
    binding = evidence["binding"]
    report = f"""# 阶段 1 精确提交运行时证据

- 生成时间（UTC）：{evidence['generated_at']}
- branch/ref：`{binding['branch_or_ref']}`
- commit SHA：`{binding['commit_sha']}`
- GitHub run id：`{binding['github_run_id'] or 'local'}`
- tracked 文件：{inv['file_count']} 个，共 {inv['total_bytes']} bytes
- 最大对象：`{inv['largest_object']['path']}`（{inv['largest_object']['bytes']} bytes）
- capability specs：{len(evidence['capability_specs'])} 份
- pending-review 安全索引：{pending['record_count']} 条，SHA256 `{pending['index_sha256']}`

本证据只读取该提交的 Git tracked 文件。它没有读取 ignored cache、数据库、papers、备份、凭据或用户内容。详细逐文件哈希见同一 artifact 中的 `final_inventory.json`。
"""
    (output_dir / "stage1_completion_report.runtime.md").write_text(
        report, encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "cache" / "git_bootstrap" / "stage1_evidence",
    )
    args = parser.parse_args()
    evidence = build_evidence(ROOT)
    write_evidence(evidence, args.output_dir)
    print(
        json.dumps(
            {
                "commit_sha": evidence["binding"]["commit_sha"],
                "tracked_files": evidence["tracked_inventory"]["file_count"],
                "specs": len(evidence["capability_specs"]),
                "pending_review": evidence["pending_review"]["record_count"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
