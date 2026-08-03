from __future__ import annotations

"""Windows-safe, deterministic paths for locally stored research materials.

The original title remains in source metadata.  The filesystem name is an
operational locator and is deliberately bounded so that a complete deployment
can be extracted below an ordinary Windows user directory.
"""

import hashlib
import os
import re
from pathlib import Path

from tools.portable_paths import canonical_path, relative_path


MAX_FILENAME_CHARS = 96
MAX_PROJECT_RELATIVE_PATH_CHARS = 180
MIN_FILENAME_CHARS = 48
HASH_CHARS = 10

_INVALID_WINDOWS_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_SPACE_RUN = re.compile(r"\s+")
_RESERVED_WINDOWS_NAMES = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def filesystem_path(path: Path) -> Path:
    """Return a Windows extended-length path for actual filesystem I/O."""
    absolute = path.absolute()
    if os.name != "nt":
        return absolute
    raw = os.fspath(absolute)
    if raw.startswith("\\\\?\\"):
        return absolute
    if raw.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + raw[2:])
    return Path("\\\\?\\" + raw)


def iter_paper_files(papers_root: Path) -> list[Path]:
    """Enumerate files without ``Path.is_file()``, which can lie past MAX_PATH."""
    files: list[Path] = []
    for current, _directories, filenames in os.walk(papers_root.absolute()):
        files.extend(Path(current) / filename for filename in filenames)
    return files


def sanitize_filename(filename: str) -> str:
    """Return a portable filename without changing its final extension."""
    raw = _SPACE_RUN.sub(" ", str(filename or "").strip())
    cleaned = _INVALID_WINDOWS_CHARS.sub("_", raw).rstrip(" .")
    if not cleaned:
        cleaned = "research_material"
    if Path(cleaned).stem.casefold() in _RESERVED_WINDOWS_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def _bounded_filename_length(
    path: Path,
    *,
    project_root: Path,
    max_filename_chars: int,
    max_relative_path_chars: int,
) -> int:
    parent_relative = relative_path(path.parent, project_root)
    relative_prefix_chars = len(parent_relative.as_posix()) + 1
    relative_budget = max_relative_path_chars - relative_prefix_chars
    return max(
        MIN_FILENAME_CHARS,
        min(max_filename_chars, relative_budget),
    )


def proposed_paper_path(
    path: Path,
    *,
    project_root: Path,
    max_filename_chars: int = MAX_FILENAME_CHARS,
    max_relative_path_chars: int = MAX_PROJECT_RELATIVE_PATH_CHARS,
) -> Path:
    """Return the deterministic safe path for a paper without touching disk."""
    source = canonical_path(path)
    root = canonical_path(project_root)
    papers_root = root / "papers"
    relative_path(source, papers_root)

    cleaned_name = sanitize_filename(source.name)
    candidate = source.with_name(cleaned_name)
    limit = _bounded_filename_length(
        candidate,
        project_root=root,
        max_filename_chars=max_filename_chars,
        max_relative_path_chars=max_relative_path_chars,
    )
    relative = relative_path(candidate, root).as_posix()
    if len(cleaned_name) <= limit and len(relative) <= max_relative_path_chars:
        return candidate

    # Only the final suffix is treated as the extension.  Report titles often
    # contain ticker-like dots such as "002463.SZ", which are not suffixes.
    extension = source.suffix
    stem = cleaned_name[: -len(extension)] if extension else cleaned_name
    identity = relative_path(source, root).as_posix()
    token = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:HASH_CHARS]
    available = limit - len(extension) - len(token) - 2
    if available < 12:
        raise ValueError(f"研报父目录过长，无法生成安全文件名：{source}")
    prefix = stem[:available].rstrip(" ._-")
    return source.with_name(f"{prefix}__{token}{extension}")


def paper_path_violations(
    papers_root: Path,
    *,
    project_root: Path,
    max_filename_chars: int = MAX_FILENAME_CHARS,
    max_relative_path_chars: int = MAX_PROJECT_RELATIVE_PATH_CHARS,
) -> list[Path]:
    root = canonical_path(project_root)
    violations: list[Path] = []
    for path in iter_paper_files(papers_root):
        if proposed_paper_path(
            path,
            project_root=root,
            max_filename_chars=max_filename_chars,
            max_relative_path_chars=max_relative_path_chars,
        ) != canonical_path(path):
            violations.append(path.absolute())
    return sorted(violations, key=lambda item: relative_path(item, root).as_posix())


def normalize_new_paper_file(
    path: Path,
    *,
    project_root: Path,
) -> Path:
    """Rename a newly created, not-yet-referenced paper when needed.

    Existing referenced corpora must use ``migrate_paper_paths`` so databases
    and manifests are updated together.
    """
    source = canonical_path(path)
    if not filesystem_path(source).is_file():
        raise FileNotFoundError(source)
    target = proposed_paper_path(source, project_root=project_root)
    if target == source:
        return source
    if filesystem_path(target).exists():
        raise FileExistsError(f"研报安全文件名冲突：{target}")
    os.replace(filesystem_path(source), filesystem_path(target))
    return target
