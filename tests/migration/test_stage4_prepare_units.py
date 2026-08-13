from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tools.migration.stage4_prepare_units import (
    Stage4PreparationError,
    _verify_durable_snapshots,
    prepare_units,
)


class _Cursor:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self.row = row

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, _sql: str, _params: tuple[str, ...] = ()) -> None:
        return None

    def fetchone(self) -> tuple[Any, ...] | None:
        return self.row


class _Connection:
    def __init__(self, row: tuple[Any, ...] | None) -> None:
        self.row = row

    def cursor(self) -> _Cursor:
        return _Cursor(self.row)

    def close(self) -> None:
        return None


def _expected() -> list[dict[str, Any]]:
    return [
        {
            "cutover_unit": "user_content_notes",
            "snapshot_id": "user_content_notes:fixture",
            "source_row_count": 7,
        }
    ]


def test_fresh_session_probe_accepts_committed_reconciled_snapshot() -> None:
    result = _verify_durable_snapshots(
        _Connection(("user_content_notes", "reconciled", False, 7)),
        _expected(),
    )

    assert result == [
        {
            "cutover_unit": "user_content_notes",
            "snapshot_id": "user_content_notes:fixture",
            "lifecycle_state": "reconciled",
            "formal_business_data": False,
            "source_row_count": 7,
        }
    ]


@pytest.mark.parametrize(
    "row",
    [
        None,
        ("user_content_notes", "staging", False, 7),
        ("user_content_notes", "reconciled", True, 7),
        ("user_content_notes", "reconciled", False, 6),
    ],
)
def test_fresh_session_probe_rejects_rolled_back_or_incomplete_snapshot(
    row: tuple[Any, ...] | None,
) -> None:
    with pytest.raises(Stage4PreparationError, match="not durably visible"):
        _verify_durable_snapshots(_Connection(row), _expected())


def test_prepare_units_uses_top_level_transactions_and_fresh_session_probe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class AuthorityCursor(_Cursor):
        def fetchall(self) -> list[tuple[Any, ...]]:
            return []

    class LoadConnection(_Connection):
        def __init__(self) -> None:
            super().__init__(None)
            self.autocommit = False

        def cursor(self) -> AuthorityCursor:
            return AuthorityCursor(None)

    load_connection = LoadConnection()
    durable_connection = _Connection(
        ("user_content_notes", "reconciled", False, 1)
    )
    connections = iter([load_connection, durable_connection])
    monkeypatch.setattr(
        "tools.migration.stage4_prepare_units._connection_from_runtime",
        lambda *_args: next(connections),
    )

    def fake_build(**kwargs: Any) -> dict[str, Any]:
        output = Path(kwargs["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        (output / "user_content_notes.rows.jsonl").write_text(
            '{"fixture":true}\n', encoding="utf-8"
        )
        (output / "user_content_notes.snapshot.json").write_text(
            "{}", encoding="utf-8"
        )
        return {
            "snapshot_id": "user_content_notes:fixture",
            "manifest_sha256": "a" * 64,
        }

    def fake_load(connection: Any, **_kwargs: Any) -> dict[str, Any]:
        assert connection.autocommit is True
        return {
            "source_row_count": 1,
            "source_content_sha256": "b" * 64,
            "target_content_sha256": "b" * 64,
        }

    monkeypatch.setattr(
        "tools.migration.stage4_prepare_units.build_unit_snapshot", fake_build
    )
    monkeypatch.setattr(
        "tools.migration.stage4_prepare_units.load_snapshot", fake_load
    )
    monkeypatch.setattr(
        "tools.migration.stage4_prepare_units.shutil.disk_usage",
        lambda _path: SimpleNamespace(free=10 * 1024**3),
    )

    data = tmp_path / "data"
    data.mkdir()
    for name in ("research.db", "financial.db", "opportunity_lens.db", "sentiment.db"):
        (data / name).write_bytes(b"fixture")
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "validation": {"passed": True},
                "registry_sha256": "c" * 64,
            }
        ),
        encoding="utf-8",
    )
    route = tmp_path / "route.json"
    route.write_text(
        json.dumps(
            {
                "authority_state": "S0",
                "backend": "sqlite_transition",
                "sqlite_writer_enabled": True,
                "production_postgresql_enabled": False,
            }
        ),
        encoding="utf-8",
    )

    result = prepare_units(
        source_data_root=data,
        registry_path=registry,
        route_path=route,
        runtime_path=tmp_path / "runtime.json",
        application_commit_sha="d" * 40,
        work_root=tmp_path / "work",
        units=("user_content_notes",),
    )

    assert load_connection.autocommit is True
    assert result["failures"] == []
    assert result["durable_snapshots"][0]["source_row_count"] == 1
