from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = "project.artifact_inventory.v1"
FEATURE_RETIREMENT_SCHEMA_VERSION = "project.feature_retirement.v1"
FEATURE_RETIREMENT_AUTHORIZATION = "explicit_user_authorization"
FEATURE_RETIREMENT_CLASSIFICATION = "retire_feature"
FEATURE_RETIREMENT_BATCH_PATTERN = re.compile(r"^retire_[a-z0-9][a-z0-9_-]{2,63}$")

LIVE_DB_PATHS = {
    "data/financial.db",
    "data/research.db",
    "data/sentiment.db",
    "data/opportunity_lens.db",
}
LIVE_DB_SIDECAR_PATHS = {
    f"{path}{suffix}"
    for path in LIVE_DB_PATHS
    for suffix in ("-wal", "-shm")
}
SECRET_PREFIX = "tools/dynamic/secrets/"

FEATURE_RETIREMENT_BLOCKED_PREFIXES = (
    SECRET_PREFIX,
    "tools/maintenance/",
)
FEATURE_RETIREMENT_BLOCKED_FILES = {
    "AGENTS.md",
    "config/research_workflow.yaml",
    "codex_context/BACKUP_REGISTRY.md",
    "tools/maintenance/project_artifacts.py",
    "tools/maintenance/apply_project_cleanup.py",
    *LIVE_DB_PATHS,
    *LIVE_DB_SIDECAR_PATHS,
}
FEATURE_RETIREMENT_DATABASE_SUFFIXES = (
    ".db",
    ".db-wal",
    ".db-shm",
    ".db-journal",
    ".sqlite",
    ".sqlite-wal",
    ".sqlite-shm",
    ".sqlite-journal",
    ".sqlite3",
    ".sqlite3-wal",
    ".sqlite3-shm",
    ".sqlite3-journal",
)
FEATURE_RETIREMENT_GLOB_CHARS = frozenset("*?[]{}!")

ALWAYS_PROTECTED_PREFIXES = (
    ".codex/",
    "backup/latest/",
    "config/",
    "docs/industries/",
    "docs/research/",
    "funda/",
    "openspec/",
    "opportunity_lens/intake_requests/",
    "opportunity_lens/intake_templates/",
    "opportunity_lens/research_outputs/",
    "papers/",
    "skills/",
    "templates/",
    "tests/",
    "tools/dynamic/secrets/",
    "tools/opportunity_lens/",
    "tools/research_core/",
    "tools/sentiment/",
    "tools/viewer/",
    "审核代理/",
)

ALWAYS_PROTECTED_FILES = {
    ".gitignore",
    "AGENTS.md",
    "CLAUDE_COMPANY_PROFILE.md",
    "PENDING_USER_REVIEW.md",
    "PROGRESS_LOG.md",
    "requirements.txt",
    "config/research_workflow.yaml",
    "codex_context/BACKUP_REGISTRY.md",
    "codex_context/FILE_DB_INDEX.md",
    "codex_context/LIVE_STATE.md",
    "codex_context/PROJECT_COMPLETE_UNDERSTANDING.md",
    "docs/AUTOMATION_SETUP.md",
    "tools/pipeline/db_writer.py",
    "tools/pipeline/ingest_research.py",
    "tools/pipeline/ingest_industry.py",
    "tools/pipeline/ingest_b_track.py",
    "tools/maintenance/project_artifacts.py",
    "tools/maintenance/apply_project_cleanup.py",
    "tools/maintenance/refresh_project_backup.py",
    "tools/maintenance/prune_external_project_backups.py",
    "观察个股.txt",
    "行业关键词.txt",
    *LIVE_DB_PATHS,
    *LIVE_DB_SIDECAR_PATHS,
}

CURRENT_ROOT_RESEARCH_INPUTS = {
    "PCB制造产业研究数据整理Prompt.md",
    "半导体量测行研.md",
    "测试机研究prompt.md",
    "硅片产业研究Prompt.md",
    "高多层PCB板.md",
}

COMPATIBILITY_ROOT_DOCS = {
    "CHECKLIST_新行业接入_20260628.md",
    "FRAMEWORK_双轨行研_20260628.md",
    "STANDARD_PROMPT驱动行研_20260628.md",
    "STANDARD_行研流程_20260609.md",
}

VERBATIM_HISTORY_ROOT_DOCS = {
    "CLAUDE.md",
}

HISTORICAL_SINGLE_FILES = {
    "DEMO_SCRIPT.md",
    "docs/DEMO_SCRIPT.md",
}

WORKFLOW_REFACTOR_HISTORY_FILES = {
    "cache/workflow_refactor_20260712/DESIGN_DECISION_RECORD.md",
    "cache/workflow_refactor_20260712/FINAL_REFACTOR_AUDIT.md",
    "cache/workflow_refactor_20260712/backup_snapshot.json",
    "cache/workflow_refactor_20260712/context_size_comparison.json",
    "cache/workflow_refactor_20260712/audits/final_live_v17_migration_audit.json",
    "cache/workflow_refactor_20260712/audits/legacy_run_pack_audit_runtime_wiring.json",
    "cache/workflow_refactor_20260712/audits/runtime_microbenchmark.json",
    "cache/workflow_refactor_20260712/audits/sentiment_backup_vs_live.json",
    "cache/workflow_refactor_20260712/audits/workflow_contract_audit.json",
    "cache/workflow_refactor_20260712/viewer/browser_audit_runtime_wiring.json",
    "cache/workflow_refactor_20260712/viewer/db_hashes_after_final_browser.json",
    "cache/workflow_refactor_20260712/viewer/db_hashes_before_final_browser.json",
}

HISTORICAL_ROOT_DOC_PATTERNS = (
    re.compile(r"^(?:PHASE|STAGE|RUN_LOG|AUDIT|DESIGN_|UI_).+\.md$", re.IGNORECASE),
    re.compile(r"^OPPORTUNITY_LENS_.+(?:PROMPT|COMMAND)\.md$", re.IGNORECASE),
)

REFERENCED_HISTORY_ROOT_FILES = {
    "OPPORTUNITY_LENS_DESIGN_PATCH_PROMPT.md",
    "OPPORTUNITY_LENS_DESIGN_PATCH_V1_1_PROMPT.md",
    "OPPORTUNITY_LENS_DESIGN_PATCH_V1_4_INTAKE_EVIDENCE_POLICY_PROMPT.md",
    "OPPORTUNITY_LENS_DESIGN_START_PROMPT.md",
    "OPPORTUNITY_LENS_ENGINEER_FULL_IMPLEMENTATION_PROMPT.md",
    "OPPORTUNITY_LENS_ENGINEER_PREFLIGHT_CONTEXT_UPDATE_PROMPT.md",
    "OPPORTUNITY_LENS_ENGINEER_V14_INTAKE_EVIDENCE_POLICY_PATCH_PROMPT.md",
    "OPPORTUNITY_LENS_IMPLEMENTATION_PLAN_START_PROMPT.md",
    "OPPORTUNITY_LENS_PLAN_PATCH_V1_4_INTAKE_EVIDENCE_POLICY_PROMPT.md",
    "OPPORTUNITY_LENS_PREFLIGHT_CONTEXT_PATCH_PROMPT.md",
    "PHASE2_WU1_REVISION.md",
    "PHASE3_STAGE2C_G_COMMAND.md",
    "RUN_LOG_星瀚情绪重构_20260624.md",
}

GENERATED_CACHE_DIR_PATTERNS = (
    re.compile(r"^cache/chrome", re.IGNORECASE),
    re.compile(r"^cache/.*chrome", re.IGNORECASE),
)

GENERATED_CACHE_DIRS = {
    "cache/shots",
    "cache/theme_review",
    "cache/ui_screenshots",
}

GENERATED_DEPLOYMENT_VALIDATION_DIRS = {
    "cache/broadcast_validation",
    "cache/cache_bundle_validation_20260729",
    "cache/installer_e2e_20260729",
    "cache/installer_hotfix_validation_20260729",
    "cache/installer_lock_simulation",
    "cache/package_dependency_audit_20260729",
    "cache/paper_path_hotfix_validation_20260729",
    "cache/tar_safe_test_20260728",
    "cache/tar_safe_v2_test_20260728",
    "cache/tarv1",
    "cache/v15b",
    "cache/v15c",
    "cache/zip_safe_test_20260728",
}

GENERATED_VISUAL_TOKENS = (
    "browser",
    "browser_audit",
    "plotly_render",
    "screenshot",
    "screenshots",
    "human_table_audit",
    "visual",
)

REGENERABLE_CACHE_FILES = {
    "cache/broadcast_build_self_install_20260729.stderr.log",
    "cache/broadcast_build_self_install_20260729.stdout.log",
    "cache/broadcast_build_self_install_final.pid",
    "cache/broadcast_build_self_install_final_20260729.stderr.log",
    "cache/broadcast_build_self_install_final_20260729.stdout.log",
    "cache/broadcast_extract_final.pid",
    "cache/broadcast_extract_final.stderr.log",
    "cache/broadcast_extract_final.stdout.log",
    "cache/broadcast_extract_self_install.pid",
    "cache/broadcast_extract_self_install.stderr.log",
    "cache/broadcast_extract_self_install.stdout.log",
    "cache/installer_syntax_test.ps1",
    "cache/package_validation_8091.pid",
    "cache/viewer_debug.log",
    "cache/xinghan_dump.json",
}

HISTORICAL_CACHE_DIR_PATTERNS = (
    re.compile(r"^cache/viewer_backup_", re.IGNORECASE),
    re.compile(r"^cache/templates_backup", re.IGNORECASE),
    re.compile(r"^cache/q1md_backup", re.IGNORECASE),
    re.compile(r"^cache/removed_opportunity_lens", re.IGNORECASE),
    re.compile(r"^cache/backup(?:/|$)", re.IGNORECASE),
)

ONE_OFF_ROOT_FILES = {
    "107341",
    "300",
    "_shot_recruit.py",
    "diag_plotly.py",
    "shot_ours.py",
    "shot_v7.py",
    "图一.png",
    "图二.png",
}

TEXT_EXTENSIONS = {
    ".css", ".html", ".ini", ".js", ".json", ".md", ".ps1", ".py",
    ".sql", ".toml", ".txt", ".yaml", ".yml",
}

# These workflow artifact names are intentionally reused by every research run.
# A bare basename must not keep an unrelated exact path alive forever. Full
# POSIX/Windows relative paths remain reference tokens, so real references are
# still protected.
AMBIGUOUS_REFERENCE_BASENAMES = {
    "brief.json",
    "calculation_ledger.json",
    "manifest.json",
    "workflow_request.json",
}

REFERENCE_SCAN_PREFIXES = (
    ".codex/", "AGENTS.md", "config/", "codex_context/", "docs/", "openspec/",
    "opportunity_lens/", "skills/", "templates/", "tests/", "tools/", "审核代理/",
)


@dataclass
class ArtifactRecord:
    path: str
    size: int
    modified_at: str
    sha256: str | None
    top_level: str
    classification: str
    batch: str | None
    reason: str
    protected_reasons: list[str] = field(default_factory=list)
    active_references: list[str] = field(default_factory=list)
    recovery: str | None = None
    target_path: str | None = None
    distilled_to: str | None = None
    retirement_spec_hash: str | None = None
    retirement_peer_references: list[str] = field(default_factory=list)


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _io_path(path: Path) -> Path:
    """Return a Windows extended-length path for filesystem I/O."""
    resolved = path.resolve()
    if os.name != "nt":
        return resolved
    value = str(resolved)
    if value.startswith("\\\\?\\"):
        return resolved
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value.lstrip("\\"))
    return Path("\\\\?\\" + value)


def _normal_path(path: Path) -> Path:
    """Remove the Windows extended-length prefix while preserving the path."""
    value = str(path)
    if value.startswith("\\\\?\\UNC\\"):
        return Path("\\\\" + value[8:])
    if value.startswith("\\\\?\\"):
        return Path(value[4:])
    return path


def _is_regular_file(path: Path) -> bool:
    return _io_path(path).is_file()


def _file_stat(path: Path):
    return _io_path(path).stat()


def _canonical_include_prefix(value: Any) -> str:
    """Validate one exact project-relative file or directory inventory scope."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("inventory include prefix must be a non-empty string")
    if value != value.strip() or "\\" in value or "\x00" in value:
        raise ValueError(f"inventory include prefix must use canonical POSIX syntax: {value!r}")
    if any(char in value for char in FEATURE_RETIREMENT_GLOB_CHARS):
        raise ValueError(f"inventory include prefix does not allow glob syntax: {value}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"inventory include prefix must stay inside the project: {value}")
    if any(":" in part for part in pure.parts) or pure.as_posix() != value:
        raise ValueError(f"inventory include prefix is not canonical POSIX syntax: {value}")
    if value == SECRET_PREFIX.rstrip("/") or value.startswith(SECRET_PREFIX):
        raise ValueError("inventory include prefix must not select tools/dynamic/secrets")
    return value


def _scoped_inventory_files(root: Path, include_prefixes: Iterable[str] | None) -> tuple[list[Path], list[str]]:
    """Enumerate either the whole project or an explicit, non-glob scope."""
    if include_prefixes is None:
        return (
            sorted(
                (path for path in root.rglob("*") if path.is_file()),
                key=lambda path: path.as_posix().lower(),
            ),
            [],
        )

    prefixes = sorted({_canonical_include_prefix(value) for value in include_prefixes})
    if not prefixes:
        raise ValueError("include_prefixes must contain at least one exact path when provided")
    files: set[Path] = set()
    for rel in prefixes:
        target = root.joinpath(*PurePosixPath(rel).parts)
        if target.is_symlink() or not _inside(target, root):
            raise ValueError(f"inventory include prefix is unsafe: {rel}")
        if not target.exists():
            raise FileNotFoundError(f"inventory include prefix does not exist: {rel}")
        if _is_regular_file(target):
            files.add(target.resolve())
            continue
        if not target.is_dir():
            raise ValueError(f"inventory include prefix is not a regular file or directory: {rel}")
        for current, directory_names, file_names in os.walk(str(_io_path(target))):
            current_path = Path(current)
            for name in directory_names:
                candidate = current_path / name
                if candidate.is_symlink():
                    raise ValueError(
                        "inventory include prefix contains a symlink: "
                        + _relative(_normal_path(candidate), root)
                    )
            for name in file_names:
                candidate = current_path / name
                if candidate.is_symlink():
                    raise ValueError(
                        "inventory include prefix contains a symlink: "
                        + _relative(_normal_path(candidate), root)
                    )
                if candidate.is_file():
                    files.add(_normal_path(candidate).resolve())
    return sorted(files, key=lambda path: path.as_posix().lower()), prefixes


def _canonical_retirement_path(value: Any) -> str:
    """Validate one exact, project-relative POSIX file path.

    Feature retirement deliberately does not expand globs or accept directory
    shorthand. Requiring canonical POSIX spelling also prevents the same file
    from being authorized through multiple textual aliases.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError("feature retirement path 必须是非空字符串")
    if value != value.strip() or "\\" in value or "\x00" in value:
        raise ValueError(f"feature retirement path 不是规范 POSIX 相对路径: {value!r}")
    if any(char in value for char in FEATURE_RETIREMENT_GLOB_CHARS):
        raise ValueError(f"feature retirement 禁止 glob/模式字符: {value}")
    pure = PurePosixPath(value)
    if pure.is_absolute() or not pure.parts or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError(f"feature retirement path 必须是项目内精确相对路径: {value}")
    if any(":" in part for part in pure.parts) or pure.as_posix() != value:
        raise ValueError(f"feature retirement path 不是规范 POSIX 相对路径: {value}")
    return value


def feature_retirement_forbidden_reason(rel: str) -> str | None:
    """Return the non-bypassable retirement guard hit for an exact path."""
    if rel in FEATURE_RETIREMENT_BLOCKED_FILES:
        return "治理锚点、live SQLite 或清理维护脚本不得通过 feature retirement 删除"
    if any(rel.startswith(prefix) for prefix in FEATURE_RETIREMENT_BLOCKED_PREFIXES):
        return "secrets 或 tools/maintenance 不得通过 feature retirement 删除"
    if rel.lower().endswith(FEATURE_RETIREMENT_DATABASE_SUFFIXES):
        return "SQLite 数据库及 sidecar 必须走独立事务迁移/备份流程"
    return None


def normalize_feature_retirement_spec(
    payload: Mapping[str, Any],
    *,
    root: Path,
) -> dict[str, Any]:
    """Validate and canonicalize an explicit user-authorized retirement spec."""
    if not isinstance(payload, Mapping):
        raise ValueError("feature retirement spec 必须是 JSON object")
    required = {"schema_version", "authorization", "batch", "reason", "paths"}
    missing = sorted(required - set(payload))
    extra = sorted(set(payload) - required)
    if missing or extra:
        raise ValueError(
            "feature retirement spec 字段不合法: "
            + json.dumps({"missing": missing, "extra": extra}, ensure_ascii=False)
        )
    if payload.get("schema_version") != FEATURE_RETIREMENT_SCHEMA_VERSION:
        raise ValueError("不支持的 feature retirement spec schema")
    if payload.get("authorization") != FEATURE_RETIREMENT_AUTHORIZATION:
        raise ValueError("feature retirement 缺少显式用户授权声明")
    batch = payload.get("batch")
    if not isinstance(batch, str) or not FEATURE_RETIREMENT_BATCH_PATTERN.fullmatch(batch):
        raise ValueError("feature retirement batch 必须匹配 retire_<exact_scope>")
    reason = payload.get("reason")
    if not isinstance(reason, str) or len(reason.strip()) < 8 or len(reason.strip()) > 2000:
        raise ValueError("feature retirement reason 必须是 8-2000 字符的明确理由")
    raw_paths = payload.get("paths")
    if not isinstance(raw_paths, list) or not raw_paths or len(raw_paths) > 500:
        raise ValueError("feature retirement paths 必须是 1-500 个 exact file path")

    root = root.resolve()
    paths: list[str] = []
    seen: set[str] = set()
    for raw in raw_paths:
        rel = _canonical_retirement_path(raw)
        if rel in seen:
            raise ValueError(f"feature retirement path 重复: {rel}")
        seen.add(rel)
        forbidden = feature_retirement_forbidden_reason(rel)
        if forbidden:
            raise ValueError(f"feature retirement 禁止路径 {rel}: {forbidden}")
        source = root.joinpath(*PurePosixPath(rel).parts)
        if source.is_symlink():
            raise ValueError(f"feature retirement 禁止 symlink: {rel}")
        if not _inside(source, root):
            raise ValueError(f"feature retirement path 越出项目根目录: {rel}")
        if not source.exists():
            raise FileNotFoundError(f"feature retirement 文件不存在: {rel}")
        if not source.is_file():
            raise ValueError(f"feature retirement 禁止目录/非普通文件: {rel}")
        paths.append(rel)

    canonical = {
        "schema_version": FEATURE_RETIREMENT_SCHEMA_VERSION,
        "authorization": FEATURE_RETIREMENT_AUTHORIZATION,
        "batch": batch,
        "reason": reason.strip(),
        "paths": sorted(paths),
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    canonical["spec_hash"] = "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return canonical


def read_feature_retirement_spec(path: Path, *, root: Path) -> dict[str, Any]:
    """Read a spec without ever reading one placed under the secrets tree."""
    if path.is_symlink():
        raise ValueError("feature retirement spec 不得是 symlink")
    source = path.resolve()
    root = root.resolve()
    if _inside(source, root):
        rel = _relative(source, root)
        if rel.startswith(SECRET_PREFIX):
            raise ValueError("不得从 secrets 目录读取 feature retirement spec")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("feature retirement spec 必须是 JSON object")
    return payload


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with _io_path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def _is_under(rel: str, prefixes: Iterable[str]) -> bool:
    return any(rel == prefix.rstrip("/") or rel.startswith(prefix) for prefix in prefixes)


def _generated_bytecode(rel: str) -> bool:
    parts = rel.split("/")
    return "__pycache__" in parts or ".pytest_cache" in parts or rel.endswith((".pyc", ".pyo"))


def _known_internal_backup(rel: str) -> bool:
    return (
        rel.startswith("tools/viewer/templates_backup_")
        or rel.startswith("tools/viewer/templates/_ckpt/")
        or rel.startswith("tools/viewer/static/_ckpt/")
        or (rel.startswith("tools/viewer/static/") and rel.endswith(".bak"))
    )


def _generated_cache_visual(rel: str) -> bool:
    if not rel.startswith("cache/"):
        return False
    suffix = Path(rel).suffix.lower()
    name = Path(rel).name.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".html"}:
        return False
    lowered = rel.lower()
    return (
        any(token in lowered for token in GENERATED_VISUAL_TOKENS)
        or name.startswith(("ui_", "shot_", "screenshot_"))
    )


def _cache_validation_database(rel: str) -> bool:
    if not rel.startswith("cache/"):
        return False
    lowered = rel.lower()
    return lowered.endswith((".db", ".db-wal", ".db-shm", ".db-journal"))


def protected_reasons(rel: str) -> list[str]:
    reasons: list[str] = []
    if rel in ALWAYS_PROTECTED_FILES:
        reasons.append("explicit_live_file")
    if rel in LIVE_DB_PATHS or rel in LIVE_DB_SIDECAR_PATHS:
        reasons.append("live_sqlite_or_sidecar")
    # Generated bytecode under a protected source tree is still rebuildable. The
    # source tree remains protected; only the generated leaf files are eligible.
    if (
        _is_under(rel, ALWAYS_PROTECTED_PREFIXES)
        and not _generated_bytecode(rel)
        and not _known_internal_backup(rel)
    ):
        reasons.append("protected_runtime_or_source_root")
    if rel in CURRENT_ROOT_RESEARCH_INPUTS:
        reasons.append("current_user_research_input")
    if rel in COMPATIBILITY_ROOT_DOCS:
        reasons.append("active_compatibility_contract")
    if rel.startswith("archive/project_history/"):
        reasons.append("central_history_record")
    return reasons

def initial_classification(rel: str) -> tuple[str, str | None, str, str | None, str | None]:
    reasons = protected_reasons(rel)
    if reasons:
        return "keep_live", None, ";".join(reasons), None, None
    if _generated_bytecode(rel) or rel.endswith((".tmp", ".temp")):
        return "delete_redundant", "generated_temp", "可重建字节码或临时文件", "regenerate", None
    if rel.startswith(".codegraph/"):
        return "delete_redundant", "generated_temp", "可重建代码图索引", "regenerate", None
    if any(
        rel == base or rel.startswith(base + "/")
        for base in GENERATED_DEPLOYMENT_VALIDATION_DIRS
    ):
        return (
            "delete_redundant",
            "deployment_validation",
            "广播包解压、Windows 路径或部署预检产生的完整临时副本，可由原广播包和验收流程重建",
            "regenerate",
            None,
        )
    if _known_internal_backup(rel):
        return "delete_redundant", "internal_backup", "viewer 下旧模板、checkpoint 或样式备份，已由项目外恢复点覆盖", "external_backup", None
    if _cache_validation_database(rel):
        return "delete_redundant", "validation_databases", "cache 中的验证、排练或临时 SQLite；live 数据库仅位于 data/", "external_backup", None
    if _generated_cache_visual(rel):
        return "delete_redundant", "generated_visual", "可重建的浏览器审计、Plotly 渲染或界面截图；数据库显式引用项会在盘点阶段自动保护", "external_backup", None
    if rel in REGENERABLE_CACHE_FILES:
        return "delete_redundant", "generated_temp", "一次性 dump 或可重建 Viewer 日志", "external_backup", None
    if re.match(r"^cache/viewer\.log\.\d{8}_\d{6}\.bak$", rel, re.IGNORECASE):
        return "delete_redundant", "generated_temp", "已轮转的 Viewer 空日志备份", "external_backup", None
    if rel in {
        "cache/project_cleanup_20260721/inventory.json",
        "cache/project_cleanup_20260721/inventory_v2.json",
        "cache/project_cleanup_20260721/inventory_v3.json",
    }:
        return "delete_redundant", "generated_temp", "已由数据库引用保护版盘点清单取代", "external_backup", None
    if rel.startswith("cache/retire_") and Path(rel).suffix.lower() == ".json":
        target = f"archive/project_history/cleanup_manifests/retirements_20260721/{Path(rel).name}"
        return "retain_verbatim_history", "historical_reference", "功能退役审计原件迁入统一历史目录", "external_backup", target
    if rel.startswith("archive/workflow_v1_20260712/"):
        target = f"archive/project_history/retained_originals/workflow_v1_20260712/{rel.removeprefix('archive/workflow_v1_20260712/')}"
        return "retain_verbatim_history", "historical_reference", "旧 V1 工作流权威文件已归档，迁入统一历史目录", "external_backup", target
    if rel == "NODE_DECISION_20260610.md":
        target = "archive/project_history/retained_originals/root/NODE_DECISION_20260610.md"
        return "retain_verbatim_history", "historical_reference", "半导体上游节点拆分的独特历史决策依据", "external_backup", target
    if "/" not in rel and rel in REFERENCED_HISTORY_ROOT_FILES:
        target = f"archive/project_history/retained_originals/root_protocols/{rel}"
        return "retain_verbatim_history", "historical_reference", "仍被设计说明、代码注释或运维文档引用的历史协议原件", "external_backup", target
    if rel in WORKFLOW_REFACTOR_HISTORY_FILES:
        target = f"archive/project_history/retained_originals/workflow_refactor_20260712/{rel.removeprefix('cache/workflow_refactor_20260712/')}"
        return "retain_verbatim_history", "historical_reference", "V2 重构的关键设计或独立验收凭证", "external_backup", target
    if rel.startswith("1/docs/"):
        return "delete_redundant", "duplicate_mirror", "已逐路径、逐 SHA256 确认为 funda/docs 的完整重复镜像", "external_backup", None
    if rel == "1/shot.py" or rel.startswith("1/shots/"):
        return "delete_redundant", "generated_visual", "旧 FUNDA 静态页截图及其一次性截图脚本", "external_backup", None
    if rel.startswith("1/reference2/"):
        target = f"archive/project_history/retained_originals/design_reference/{rel}"
        return "retain_verbatim_history", "historical_reference", "影响现有界面设计的独特历史参考页，集中保留原文", "external_backup", target
    if rel.startswith("shots_ours/"):
        return "delete_redundant", "generated_visual", "历史页面截图，可由浏览器审计重建", "external_backup", None
    if any(pattern.match(rel) for pattern in GENERATED_CACHE_DIR_PATTERNS):
        return "delete_redundant", "browser_profiles", "Chrome/CDP 临时 profile 或页面审计缓存", "regenerate", None
    if any(rel == base or rel.startswith(base + "/") for base in GENERATED_CACHE_DIRS):
        return "delete_redundant", "generated_visual", "可重建截图或主题审计产物", "regenerate", None
    if rel.startswith("cache/workflow_refactor_20260712/viewer/screenshots/"):
        return "delete_redundant", "generated_visual", "已由 JSON 审计报告记录的可重建截图", "external_backup", None
    if any(pattern.match(rel) for pattern in HISTORICAL_CACHE_DIR_PATTERNS):
        return "delete_redundant", "historical_cache", "已被现行结果和项目外备份覆盖的历史 cache/备份", "external_backup", None
    if rel.startswith("backup_before_company_profile_20260601_012322/"):
        return "delete_redundant", "internal_backup", "项目内旧备份，已由完整项目外备份覆盖", "external_backup", None
    if rel.startswith("data/") and re.search(r"(?:\.bak|\.before_|backup|\.old)", Path(rel).name, re.IGNORECASE):
        return "delete_redundant", "internal_backup", "项目内旧 SQLite 备份，已由事务一致项目外备份覆盖", "external_backup", None
    if rel.startswith("cache/") and (
        re.search(r"(?:^|/)(?:research|sentiment|opportunity_lens).*(?:\.bak|backup|before_)", rel, re.IGNORECASE)
        or (
            rel.startswith("cache/workflow_refactor_20260712/db_migration_validation/")
            and rel.endswith(".db")
        )
    ):
        return "delete_redundant", "internal_backup", "cache 内旧数据库快照或迁移临时库，已由外部恢复点覆盖", "external_backup", None
    name = Path(rel).name
    if "/" not in rel and name in VERBATIM_HISTORY_ROOT_DOCS:
        target = f"archive/project_history/retained_originals/root/{name}"
        return "retain_verbatim_history", "historical_docs", "项目宪法/全量进度历史需保留原文但不应继续位于活动根目录", "external_backup", target
    if rel in HISTORICAL_SINGLE_FILES:
        return "distill_then_delete", "historical_docs", "旧演示或节点决策文档，先提炼仍有效结论", "external_backup", None
    if "/" not in rel and name.endswith(".md") and any(pattern.match(name) for pattern in HISTORICAL_ROOT_DOC_PATTERNS):
        return "distill_then_delete", "historical_docs", "旧 command/protocol/design/completion 文档，先提炼耐久信息", "external_backup", None
    if "/" not in rel and name in ONE_OFF_ROOT_FILES:
        return "delete_redundant", "one_off_root", "根目录一次性诊断、截图或临时文件", "external_backup", None
    return "pending_review", None, "尚未证明可删除或必须迁移", None, None


def _scan_text_files(root: Path) -> list[tuple[str, str]]:
    corpus: list[tuple[str, str]] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = _relative(path, root)
        if rel.startswith(SECRET_PREFIX) or path.suffix.lower() not in TEXT_EXTENSIONS or path.stat().st_size > 2_000_000:
            continue
        if not _is_under(rel, REFERENCE_SCAN_PREFIXES):
            continue
        try:
            corpus.append((rel, path.read_text(encoding="utf-8", errors="ignore")))
        except OSError:
            continue
    return corpus


def _references_for(rel: str, corpus: list[tuple[str, str]], *, limit: int = 8) -> list[str]:
    basename = Path(rel).name
    tokens = {rel, rel.replace("/", "\\")}
    if len(basename) >= 8:
        tokens.add(basename)
    refs: list[str] = []
    for source_rel, text in corpus:
        if source_rel == rel:
            continue
        if any(token in text for token in tokens):
            refs.append(source_rel)
            if len(refs) >= limit:
                break
    return refs


def _build_reference_map(
    candidates: list[str],
    corpus: list[tuple[str, str]],
    *,
    limit: int = 8,
    include_basename: bool = True,
) -> dict[str, list[str]]:
    token_owners: dict[str, set[str]] = defaultdict(set)
    for rel in candidates:
        basename = Path(rel).name
        for token in {
            rel,
            rel.replace("/", "\\"),
            (
                basename
                if (
                    include_basename
                    and len(basename) >= 8
                    and basename.lower() not in AMBIGUOUS_REFERENCE_BASENAMES
                )
                else ""
            ),
        }:
            if token:
                token_owners[token].add(rel)
    if not token_owners:
        return {}
    pattern = re.compile("|".join(re.escape(token) for token in sorted(token_owners, key=len, reverse=True)))
    references: dict[str, list[str]] = defaultdict(list)
    ignored_sources = {
        "tools/maintenance/project_artifacts.py",
        "tools/maintenance/apply_project_cleanup.py",
    }
    for source_rel, text in corpus:
        if source_rel in ignored_sources:
            continue
        seen_in_source: set[str] = set()
        for match in pattern.finditer(text):
            for owner in token_owners[match.group(0)]:
                if owner == source_rel or owner in seen_in_source or len(references[owner]) >= limit:
                    continue
                references[owner].append(source_rel)
                seen_in_source.add(owner)
    return dict(references)


def feature_retirement_active_references(
    root: Path,
    paths: Iterable[str],
) -> dict[str, list[str]]:
    """Rescan current project text and return references outside the retirement set."""
    exact_paths = sorted({_canonical_retirement_path(path) for path in paths})
    retirement_paths = set(exact_paths)
    corpus = _scan_text_files(root.resolve())
    broadcast_paths = [
        path for path in exact_paths if path.startswith("broadcast_packages/")
    ]
    ordinary_paths = [
        path for path in exact_paths if not path.startswith("broadcast_packages/")
    ]
    reference_map = _build_reference_map(ordinary_paths, corpus)
    reference_map.update(
        _build_reference_map(
            broadcast_paths,
            corpus,
            include_basename=False,
        )
    )
    return {
        rel: sorted(ref for ref in reference_map.get(rel, []) if ref not in retirement_paths)
        for rel in exact_paths
    }


def _should_scan_references(
    rel: str,
    *,
    classification: str,
    batch: str | None,
    size: int,
) -> bool:
    if classification == FEATURE_RETIREMENT_CLASSIFICATION:
        return True
    if size > 2_000_000 or Path(rel).suffix.lower() not in TEXT_EXTENSIONS:
        return False
    if batch in {
        "generated_temp",
        "browser_profiles",
        "generated_visual",
        "deployment_validation",
        "duplicate_mirror",
        "historical_cache",
        "internal_backup",
    }:
        return False
    if classification in {
        "delete_redundant",
        "distill_then_delete",
        "retain_verbatim_history",
    }:
        return True
    # Pending executable/contract candidates need references. Research caches and
    # large evidence corpora stay pending without an expensive all-to-all scan.
    return classification == "pending_review" and (
        "/" not in rel
        or rel.startswith(("tools/", "config/", "docs/", "skills/", ".codex/"))
    )


def _db_snapshot(root: Path) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for rel in sorted(LIVE_DB_PATHS):
        path = root / rel
        if not path.is_file():
            continue
        conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
        try:
            result[rel] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
                "foreign_key_issues": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
                "table_count": conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0],
            }
        finally:
            conn.close()
    return result


def _walk_json_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _walk_json_strings(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_json_strings(item)


def _normalize_project_file_reference(root: Path, value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw.replace("\\", "/")
    root_posix = root.resolve().as_posix().rstrip("/")
    if raw.lower().startswith(root_posix.lower() + "/"):
        rel = raw[len(root_posix) + 1:]
    elif raw.startswith("cache/"):
        rel = raw
    else:
        return None
    try:
        pure = PurePosixPath(rel)
        if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
            return None
        canonical = pure.as_posix()
        target = root.joinpath(*pure.parts).resolve()
        if not _inside(target, root) or not target.is_file():
            return None
        return canonical
    except OSError:
        return None


def _database_file_references(root: Path) -> dict[str, list[str]]:
    """Extract current C-track file references without scanning arbitrary DB prose."""
    path = root / "data" / "opportunity_lens.db"
    if not path.is_file():
        return {}
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    references: dict[str, set[str]] = defaultdict(set)

    def add(value: str, owner: str) -> None:
        rel = _normalize_project_file_reference(root, value)
        if rel:
            references[rel].add(owner)

    try:
        tables = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "opportunity_source" in tables:
            for row_id, value in conn.execute(
                "SELECT id,local_path FROM opportunity_source WHERE local_path IS NOT NULL"
            ):
                add(value, f"opportunity_source:{row_id}")
        for table, id_column, json_column in (
            ("opportunity_run_manifest", "id", "manifest_json"),
            ("opportunity_handoff_package", "id", "package_json"),
        ):
            if table not in tables:
                continue
            for row_id, payload in conn.execute(
                f"SELECT {id_column},{json_column} FROM {table} WHERE {json_column} IS NOT NULL"
            ):
                try:
                    decoded = json.loads(payload)
                except (TypeError, json.JSONDecodeError):
                    continue
                for value in _walk_json_strings(decoded):
                    add(value, f"{table}:{row_id}")
    finally:
        conn.close()
    return {rel: sorted(owners) for rel, owners in sorted(references.items())}


def build_inventory(
    root: Path,
    *,
    backup_path: Path,
    feature_retirement: Mapping[str, Any] | None = None,
    include_prefixes: Iterable[str] | None = None,
) -> dict:
    root = root.resolve()
    backup_path = backup_path.resolve()
    if not root.is_dir() or not backup_path.is_dir():
        raise FileNotFoundError("project root 或 backup path 不存在")
    if _inside(backup_path, root):
        raise ValueError("backup path 必须位于项目根目录之外")
    retirement = (
        normalize_feature_retirement_spec(feature_retirement, root=root)
        if feature_retirement is not None
        else None
    )
    retirement_paths = set(retirement["paths"]) if retirement else set()
    database_references = _database_file_references(root)
    files, normalized_include_prefixes = _scoped_inventory_files(root, include_prefixes)
    preliminary: list[dict] = []
    reference_candidates: list[str] = []
    for path in files:
        rel = _relative(path, root)
        if rel in retirement_paths:
            classification = FEATURE_RETIREMENT_CLASSIFICATION
            batch = retirement["batch"]
            reason = retirement["reason"]
            recovery_kind = "external_backup"
            target = None
        else:
            classification, batch, reason, recovery_kind, target = initial_classification(rel)
        stat = _file_stat(path)
        preliminary.append({
            "path": path,
            "rel": rel,
            "classification": classification,
            "batch": batch,
            "reason": reason,
            "recovery_kind": recovery_kind,
            "target": target,
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(timespec="seconds"),
        })
        if _should_scan_references(
            rel,
            classification=classification,
            batch=batch,
            size=stat.st_size,
        ):
            reference_candidates.append(rel)
    corpus = _scan_text_files(root) if reference_candidates else []
    reference_map = _build_reference_map(reference_candidates, corpus)
    broadcast_retirement_paths = sorted(
        path for path in retirement_paths
        if path.startswith("broadcast_packages/")
    )
    ordinary_retirement_paths = sorted(
        path for path in retirement_paths
        if not path.startswith("broadcast_packages/")
    )
    retirement_reference_map = _build_reference_map(
        ordinary_retirement_paths,
        corpus,
    )
    retirement_reference_map.update(
        _build_reference_map(
            broadcast_retirement_paths,
            corpus,
            include_basename=False,
        )
    )
    records: list[ArtifactRecord] = []
    for item in preliminary:
        path = item["path"]
        rel = item["rel"]
        classification = item["classification"]
        batch = item["batch"]
        reason = item["reason"]
        recovery_kind = item["recovery_kind"]
        target = item["target"]
        file_size = item["size"]
        refs = (
            retirement_reference_map.get(rel, [])
            if classification == FEATURE_RETIREMENT_CLASSIFICATION
            else reference_map.get(rel, [])
        )
        retirement_peer_references: list[str] = []
        if classification == FEATURE_RETIREMENT_CLASSIFICATION:
            retirement_peer_references = sorted(ref for ref in refs if ref in retirement_paths)
            refs = sorted(ref for ref in refs if ref not in retirement_paths)
        if refs and classification == "delete_redundant" and batch not in {"generated_temp", "browser_profiles", "generated_visual"}:
            classification = "pending_review"
            batch = None
            reason = "活动文本仍引用该候选，需人工复核"
            recovery_kind = None
            target = None
        protected = protected_reasons(rel)
        if rel in database_references:
            protected.append("live_database_file_reference")
            if classification in {
                "delete_redundant", "distill_then_delete", "retain_verbatim_history",
            }:
                classification = "keep_live"
                batch = None
                reason = "live Opportunity Lens 数据库仍显式引用该文件"
                recovery_kind = None
                target = None
        if rel.startswith(SECRET_PREFIX) or rel in LIVE_DB_PATHS or rel in LIVE_DB_SIDECAR_PATHS:
            digest = None
        else:
            try:
                digest = sha256_file(path)
            except PermissionError:
                if classification == FEATURE_RETIREMENT_CLASSIFICATION:
                    raise PermissionError(f"feature retirement 文件正被占用，无法核验: {rel}")
                # 活动抓取器会独占 cache/*.lock。全项目盘点不应因此失败，
                # 但不可读文件也绝不能进入任何清理批次。
                digest = None
                classification = "pending_review"
                batch = None
                reason = "盘点时文件正被运行中进程占用，未计算 SHA256，禁止自动清理"
                recovery_kind = None
                target = None
                protected = [*protected, "unreadable_at_inventory"]
        if recovery_kind == "external_backup":
            recovery = str(backup_path / Path(rel))
        elif recovery_kind == "regenerate":
            recovery = "regenerate"
        else:
            recovery = None
        records.append(ArtifactRecord(
            path=rel,
            size=file_size,
            modified_at=item["modified_at"],
            sha256=digest,
            top_level=rel.split("/", 1)[0],
            classification=classification,
            batch=batch,
            reason=reason,
            protected_reasons=protected,
            active_references=refs,
            recovery=recovery,
            target_path=target,
            distilled_to=(
                "archive/project_history/HISTORICAL_DECISIONS.md"
                if classification == "distill_then_delete"
                else None
            ),
            retirement_spec_hash=(
                retirement["spec_hash"]
                if retirement and classification == FEATURE_RETIREMENT_CLASSIFICATION
                else None
            ),
            retirement_peer_references=retirement_peer_references,
        ))

    counts = Counter(record.classification for record in records)
    bytes_by_class = Counter()
    top_level = defaultdict(lambda: {"files": 0, "bytes": 0})
    extension = defaultdict(lambda: {"files": 0, "bytes": 0})
    age_distribution = defaultdict(lambda: {"files": 0, "bytes": 0})
    directory_distribution = defaultdict(lambda: {"files": 0, "bytes": 0})
    duplicate_groups: dict[str, list[str]] = defaultdict(list)
    now = datetime.now(timezone.utc)
    for record in records:
        bytes_by_class[record.classification] += record.size
        top_level[record.top_level]["files"] += 1
        top_level[record.top_level]["bytes"] += record.size
        suffix = Path(record.path).suffix.lower() or "<none>"
        extension[suffix]["files"] += 1
        extension[suffix]["bytes"] += record.size
        age_days = max(0, (now - datetime.fromisoformat(record.modified_at)).days)
        if age_days <= 7:
            age_bucket = "0-7d"
        elif age_days <= 30:
            age_bucket = "8-30d"
        elif age_days <= 90:
            age_bucket = "31-90d"
        elif age_days <= 365:
            age_bucket = "91-365d"
        else:
            age_bucket = ">365d"
        age_distribution[age_bucket]["files"] += 1
        age_distribution[age_bucket]["bytes"] += record.size
        path_parts = Path(record.path).parts[:-1]
        for depth in range(1, len(path_parts) + 1):
            directory = Path(*path_parts[:depth]).as_posix()
            directory_distribution[directory]["files"] += 1
            directory_distribution[directory]["bytes"] += record.size
        if record.sha256 and record.size > 0:
            duplicate_groups[record.sha256].append(record.path)
    duplicates = [
        {"sha256": digest, "files": paths, "reclaimable_bytes": records_by_path_size(records, paths) * (len(paths) - 1)}
        for digest, paths in duplicate_groups.items()
        if len(paths) > 1
    ]
    duplicates.sort(key=lambda item: item["reclaimable_bytes"], reverse=True)
    serialized_records: list[dict[str, Any]] = []
    for record in records:
        serialized = asdict(record)
        if record.classification != FEATURE_RETIREMENT_CLASSIFICATION:
            serialized.pop("retirement_spec_hash")
            serialized.pop("retirement_peer_references")
        serialized_records.append(serialized)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project_root": str(root),
        "backup_path": str(backup_path),
        "scope": {
            "include_prefixes": normalized_include_prefixes or None,
        },
        "summary": {
            "file_count": len(records),
            "bytes": sum(record.size for record in records),
            "classification_counts": dict(sorted(counts.items())),
            "classification_bytes": dict(sorted(bytes_by_class.items())),
        },
        "top_level": dict(sorted(top_level.items(), key=lambda item: item[1]["bytes"], reverse=True)),
        "extensions": dict(sorted(extension.items(), key=lambda item: item[1]["bytes"], reverse=True)),
        "age_distribution": dict(age_distribution),
        "large_directories": [
            {"path": path, **stats}
            for path, stats in sorted(
                directory_distribution.items(), key=lambda item: item[1]["bytes"], reverse=True
            )[:200]
        ],
        "duplicate_groups": duplicates,
        "live_databases": _db_snapshot(root),
        "reference_scan": {
            "text_files_scanned": len(corpus),
            "scope_prefixes": list(REFERENCE_SCAN_PREFIXES),
            "secret_content_excluded": SECRET_PREFIX,
        },
        "database_file_references": database_references,
        "protected_prefixes": list(ALWAYS_PROTECTED_PREFIXES),
        "protected_files": sorted(ALWAYS_PROTECTED_FILES),
        "records": serialized_records,
    }
    if retirement:
        payload["feature_retirement"] = retirement
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["inventory_hash"] = "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def records_by_path_size(records: list[ArtifactRecord], paths: list[str]) -> int:
    sizes = {record.path: record.size for record in records}
    return sizes[paths[0]] if paths else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="只读生成项目文件生命周期盘点和清理候选清单")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--backup-path", type=Path, required=True)
    parser.add_argument(
        "--feature-retirement-spec",
        type=Path,
        help="可选：显式用户授权的 exact-file feature retirement JSON（不支持 glob/目录）",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--include-prefix",
        action="append",
        dest="include_prefixes",
        help="可重复：仅盘点一个精确的项目相对文件或目录；不支持 glob",
    )
    args = parser.parse_args()
    feature_retirement = (
        read_feature_retirement_spec(args.feature_retirement_spec, root=args.root)
        if args.feature_retirement_spec
        else None
    )
    payload = build_inventory(
        args.root,
        backup_path=args.backup_path,
        feature_retirement=feature_retirement,
        include_prefixes=args.include_prefixes,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "inventory_hash": payload["inventory_hash"],
        **payload["summary"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
