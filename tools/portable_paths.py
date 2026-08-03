from __future__ import annotations

"""Portable filesystem identity helpers.

Windows can expose the same directory through both its long name and an 8.3
alias (for example ``runneradmin`` and ``RUNNER~1``).  ``Path.relative_to`` is
lexical, so callers must normalize both operands before enforcing containment.
"""

import ctypes
import os
from pathlib import Path


def _windows_long_path(path: Path) -> Path:
    """Return a long-name spelling, including for a not-yet-created leaf."""
    if os.name != "nt":
        return path

    missing: list[str] = []
    existing = path
    while not existing.exists() and existing != existing.parent:
        missing.append(existing.name)
        existing = existing.parent

    raw = os.fspath(existing)
    size = ctypes.windll.kernel32.GetLongPathNameW(raw, None, 0)
    if size:
        buffer = ctypes.create_unicode_buffer(size)
        written = ctypes.windll.kernel32.GetLongPathNameW(raw, buffer, size)
        if written:
            existing = Path(buffer.value)

    for name in reversed(missing):
        existing /= name
    return existing


def canonical_path(path: Path) -> Path:
    """Return an absolute path with aliases normalized for identity checks."""
    return _windows_long_path(Path(path).resolve(strict=False))


def relative_path(path: Path, root: Path) -> Path:
    """Return *path* relative to *root*, rejecting paths outside the root."""
    return canonical_path(path).relative_to(canonical_path(root))
