from __future__ import annotations

"""Resolve code, live-data, content, and mutable-state roots explicitly.

The historical deployment keeps all four roots in one project directory.  An
immutable release instead keeps code below ``releases/<sha>`` while databases,
research content, and mutable runtime state stay outside the release.  These
helpers make that split opt-in and preserve the historical layout by default.
"""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RuntimeLayout:
    code_root: Path
    data_root: Path
    content_root: Path
    state_root: Path

    @property
    def cache_root(self) -> Path:
        return self.state_root / "cache"


def _resolve_env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default.resolve()


def resolve_runtime_layout(code_root: str | Path | None = None) -> RuntimeLayout:
    code = (
        Path(code_root).expanduser().resolve()
        if code_root is not None
        else Path(__file__).resolve().parents[1]
    )
    return RuntimeLayout(
        code_root=code,
        data_root=_resolve_env_path("HONGHU_DATA_ROOT", code / "data"),
        content_root=_resolve_env_path("HONGHU_CONTENT_ROOT", code),
        state_root=_resolve_env_path("HONGHU_STATE_ROOT", code),
    )


def readonly_candidate_enabled() -> bool:
    return os.environ.get("HONGHU_VIEWER_MODE", "").strip().lower() == "readonly_candidate"
