from __future__ import annotations

import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from tools.migration.stage4_production_bootstrap_contract import (
    BootstrapContractError,
    load_and_validate_config,
    validate_inputs,
)
from tools.migration.stage4_json_io import read_json
from tools.migration.stage4_production_recovery import (
    _authority_snapshot,
    _configure_local_restore,
    _connect as connect_production_recovery,
    _load_json as load_production_recovery_json,
    _pg_ctl as run_production_recovery_pg_ctl,
    _required_wal_names,
    _run as run_production_recovery_command,
    _system_identifier,
    _verify_base_backup,
    _wait_for_recovery_target,
    read_task_checkpoint_snapshot,
    verify_task_checkpoint_restore,
    ProductionRecoveryError,
)
from tools.migration.stage4_authority_control import (
    AuthorityControlError,
    authority_snapshot,
    read_authority_snapshots,
)
from tools.migration import stage4_authority_control as authority_control_module
from tools.migration.stage4_runtime_contract import (
    RuntimeContractError,
    tracked_static_default_route,
)
from tools.migration.stage4_isolated_entry import ALLOWED_MODULES
from tools.migration import stage4_isolated_entry as isolated_entry_module


ROOT = Path(__file__).resolve().parents[2]


TASK_IDS = (
    "IndustryDemo_DynamicTick",
    "IndustryDemo_EventIngest",
    "IndustryDemo_RecruitWeekly",
    "IndustryDemo_Retail_Afternoon",
    "IndustryDemo_Retail_Morning",
    "IndustryDemo_Retail_Preopen",
    "IndustryDemo_SentimentRetention",
    "IndustryDemo_ValuationMarket_1140",
    "IndustryDemo_ValuationMarket_1510",
    "IndustryDemo_ValuationAI_Monthly",
)


class _TaskCheckpointCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class _TaskCheckpointConnection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def execute(self, sql: str) -> _TaskCheckpointCursor:
        assert "operations.production_task_definition" in sql
        assert "operations.production_task_run" in sql
        assert "ORDER BY d.task_id" in sql
        return _TaskCheckpointCursor(self.rows)


def _task_checkpoint_rows() -> list[tuple[object, ...]]:
    observed_at = datetime(2026, 8, 17, 1, 2, 3, tzinfo=timezone.utc)
    rows: list[tuple[object, ...]] = []
    for index, task_id in enumerate(sorted(TASK_IDS)):
        definition = (
            task_id,
            "a" * 64,
            "b" * 40,
            "operations_governance" if index == 0 else "sentiment_analytics",
            ["operations_governance"] if index == 0 else ["sentiment_analytics"],
            "DESKTOP-VGD07J4",
            900,
            True,
            2,
            observed_at,
            observed_at,
        )
        if index == 0:
            latest = (
                "2026-08-17T09:00+08:00",
                1,
                "c" * 64,
                "a" * 64,
                "b" * 40,
                "DESKTOP-VGD07J4",
                "desktop-vgd07j4\\HonghuTaskRunner",
                "succeeded",
                None,
                0,
                observed_at,
                observed_at,
                observed_at,
                "d" * 64,
                {"identity_sha256": "e" * 64, "rows": [[1, None]]},
                {"rows": [[2, None]], "identity_sha256": "f" * 64},
            )
        else:
            latest = (None,) * 16
        rows.append((*definition, *latest))
    return rows


def test_task_checkpoint_restore_canonical_snapshot_and_hash() -> None:
    source = read_task_checkpoint_snapshot(
        _TaskCheckpointConnection(_task_checkpoint_rows()),
        expected_task_ids=TASK_IDS,
    )
    restored_rows = _task_checkpoint_rows()
    # JSONB key order must not change the recovery identity.
    restored_rows[0] = (
        *restored_rows[0][:-1],
        {"identity_sha256": "f" * 64, "rows": [[2, None]]},
    )
    restored = read_task_checkpoint_snapshot(
        _TaskCheckpointConnection(restored_rows),
        expected_task_ids=TASK_IDS,
    )

    result = verify_task_checkpoint_restore(source, restored)

    assert result["verified"] is True
    assert result["task_count"] == 10
    assert result["latest_run_count"] == 1
    assert result["source_snapshot_identity_sha256"] == source["identity_sha256"]
    assert result["restored_snapshot_identity_sha256"] == source["identity_sha256"]
    assert source["tasks"][0]["latest_run"]["finished_at_utc"].endswith("+00:00")


def test_task_checkpoint_restore_fails_closed_on_checkpoint_or_task_set_drift() -> None:
    source = read_task_checkpoint_snapshot(
        _TaskCheckpointConnection(_task_checkpoint_rows()),
        expected_task_ids=TASK_IDS,
    )
    changed_rows = _task_checkpoint_rows()
    latest = list(changed_rows[0])
    latest[-1] = {"identity_sha256": "0" * 64}
    changed_rows[0] = tuple(latest)
    restored = read_task_checkpoint_snapshot(
        _TaskCheckpointConnection(changed_rows),
        expected_task_ids=TASK_IDS,
    )
    with pytest.raises(ProductionRecoveryError, match="do not match source"):
        verify_task_checkpoint_restore(source, restored)

    with pytest.raises(ProductionRecoveryError, match="definition set mismatch"):
        read_task_checkpoint_snapshot(
            _TaskCheckpointConnection(_task_checkpoint_rows()[:-1]),
            expected_task_ids=TASK_IDS,
        )


def test_recovery_authority_snapshot_accepts_complete_s3() -> None:
    snapshot = _authority_snapshot(
        (
            "S3",
            "postgresql_production",
            "user-content-production-writer",
            "epoch-1",
            '{"source":"sqlite"}',
            '{"operation_id":"formal-1"}',
            3,
            "approval-1",
        )
    )
    assert snapshot["state"] == "S3"
    assert snapshot["cutover_unit"] == "user_content_notes"
    assert snapshot["authoritative_backend"] == "postgresql_production"
    assert snapshot["postgresql_first_formal_commit"] == '{"operation_id":"formal-1"}'


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (
            ("S2", "postgresql_production", "writer", "epoch", "{}", None, 2, "approval"),
            "short S2 cutover fence",
        ),
        (
            ("S3", "sqlite_transition", "writer", "epoch", "{}", "{}", 3, "approval"),
            "S3/S4 authority snapshot is incomplete",
        ),
        (
            ("S3", "postgresql_production", "writer", "epoch", "{}", None, 3, "approval"),
            "S3/S4 authority snapshot is incomplete",
        ),
    ],
)
def test_recovery_authority_snapshot_fails_closed(row: tuple[object, ...], message: str) -> None:
    with pytest.raises(ProductionRecoveryError, match=message):
        _authority_snapshot(row)


class _AuthorityCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def fetchall(self) -> list[tuple[object, ...]]:
        return self.rows


class _AuthorityConnection:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows

    def execute(self, sql: str) -> _AuthorityCursor:
        assert "ORDER BY cutover_unit" in sql
        return _AuthorityCursor(self.rows)

    def close(self) -> None:
        return None


def test_generic_authority_recovery_validates_every_cutover_unit() -> None:
    rows = [
        (
            "financial_data",
            "S1",
            "sqlite_transition",
            None,
            None,
            None,
            None,
            2,
            "approval-f",
        ),
        (
            "user_content_notes",
            "S3",
            "postgresql_production",
            "writer-user",
            "epoch-user",
            '{"source":"sqlite"}',
            '{"operation_id":"formal-1"}',
            3,
            "approval-user",
        ),
    ]
    snapshots = read_authority_snapshots(
        _AuthorityConnection(rows),
        required_units=("user_content_notes", "financial_data"),
    )
    assert snapshots["user_content_notes"]["state"] == "S3"
    assert snapshots["financial_data"]["state"] == "S1"


def test_generic_authority_recovery_fails_on_any_s2_or_missing_unit() -> None:
    s2 = (
        "shared_identity",
        "S2",
        "postgresql_production",
        "writer-identity",
        "epoch-identity",
        "watermark",
        None,
        2,
        "approval-identity",
    )
    with pytest.raises(AuthorityControlError, match="short S2 cutover fence"):
        read_authority_snapshots(_AuthorityConnection([s2]))
    s1 = (
        "shared_identity",
        "S1",
        "sqlite_transition",
        None,
        None,
        None,
        None,
        1,
        "approval",
    )
    with pytest.raises(AuthorityControlError, match="required authority rows are missing"):
        read_authority_snapshots(
            _AuthorityConnection([s1]), required_units=("financial_data",)
        )


def test_authority_snapshot_rejects_unit_identity_mismatch() -> None:
    with pytest.raises(AuthorityControlError, match="another cutover unit"):
        authority_snapshot(
            (
                "shared_identity",
                "S1",
                "sqlite_transition",
                None,
                None,
                None,
                None,
                1,
                "approval",
            ),
            cutover_unit="financial_data",
        )


def test_authority_probe_cli_writes_validated_single_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = [
        (
            "shared_identity",
            "S1",
            "sqlite_transition",
            None,
            None,
            None,
            None,
            1,
            "approval",
        )
    ]
    observed_roles: list[str] = []

    def connection(_runtime: Path, role: str) -> _AuthorityConnection:
        observed_roles.append(role)
        return _AuthorityConnection(rows)

    monkeypatch.setattr(
        "tools.migration.stage4_s1_loader._connection_from_runtime", connection
    )
    output = tmp_path / "authority.json"
    assert (
        authority_control_module.main(
            [
                "--runtime",
                str(tmp_path / "runtime.json"),
                "--unit",
                "shared_identity",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "honghu.cutover_authority_probe.v1"
    assert payload["authority"]["state"] == "S1"
    assert observed_roles == ["migration"]


def test_runtime_static_route_is_distinct_and_legacy_compatible() -> None:
    assert (
        tracked_static_default_route(
            {"tracked_static_default_route": "sqlite_transition"}
        )
        == "sqlite_transition"
    )
    assert (
        tracked_static_default_route({"application_route": "sqlite_transition"})
        == "sqlite_transition"
    )
    with pytest.raises(RuntimeContractError, match="conflicts"):
        tracked_static_default_route(
            {
                "tracked_static_default_route": "sqlite_transition",
                "application_route": "postgresql_production",
            }
        )


@pytest.mark.parametrize(
    "label",
    ["Database system identifier", "数据库系统标识符"],
)
def test_system_identifier_is_locale_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, label: str
) -> None:
    bin_dir = tmp_path / "bin"
    data_dir = tmp_path / "data"
    bin_dir.mkdir()
    data_dir.mkdir()
    (bin_dir / "pg_controldata.exe").write_bytes(b"fixture")
    output = (
        "Catalog version: 202406281\n"
        f"{label}: 7673347824996746592\n"
        "Database block size: 8192\n"
    )
    monkeypatch.setattr(
        "tools.migration.stage4_production_recovery._run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=output),
    )

    assert _system_identifier(bin_dir, data_dir) == "7673347824996746592"


def test_system_identifier_fails_closed_on_missing_or_ambiguous_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    data_dir = tmp_path / "data"
    bin_dir.mkdir()
    data_dir.mkdir()
    (bin_dir / "pg_controldata.exe").write_bytes(b"fixture")

    monkeypatch.setattr(
        "tools.migration.stage4_production_recovery._run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout="Catalog version: 202406281\n"),
    )
    with pytest.raises(ProductionRecoveryError, match="locale-independent"):
        _system_identifier(bin_dir, data_dir)

    monkeypatch.setattr(
        "tools.migration.stage4_production_recovery._run",
        lambda *_args, **_kwargs: SimpleNamespace(
            stdout=(
                "Database system identifier: 7673347824996746592\n"
                "Unexpected identifier: 7673347824996746593\n"
            )
        ),
    )
    with pytest.raises(ProductionRecoveryError, match="ambiguous"):
        _system_identifier(bin_dir, data_dir)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    archive = tmp_path / "postgresql.zip"
    archive.write_bytes(b"approved archive fixture")
    archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
    config = json.loads(
        (ROOT / "config/migration/stage4_production_postgresql_bootstrap.template.json").read_text(
            encoding="utf-8"
        )
    )
    config["postgresql"]["archive_sha256"] = archive_sha
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    repo = tmp_path / "repo"
    route = repo / "config/migration/user_content_backend_route.json"
    route.parent.mkdir(parents=True)
    route.write_text(
        json.dumps(
            {
                "cutover_unit": "user_content_notes",
                "authority_state": "S0",
                "backend": "sqlite_transition",
                "sqlite_writer_enabled": True,
                "production_postgresql_enabled": False,
            }
        ),
        encoding="utf-8",
    )
    return config_path, archive, repo


def test_bootstrap_contract_binds_archive_route_and_commit(tmp_path: Path) -> None:
    config, archive, repo = _fixture(tmp_path)
    result = validate_inputs(
        config_path=config,
        repo_root=repo,
        commit_sha="a" * 40,
        archive_path=archive,
    )
    assert result["authority_state"] == "S0"
    assert result["authoritative_backend"] == "sqlite_transition"
    assert len(result["input_identity_sha256"]) == 64


def test_bootstrap_contract_rejects_route_escalation(tmp_path: Path) -> None:
    config, archive, repo = _fixture(tmp_path)
    route = repo / "config/migration/user_content_backend_route.json"
    payload = json.loads(route.read_text(encoding="utf-8"))
    payload.update(authority_state="S2", backend="postgresql_production")
    route.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BootstrapContractError, match="outside S0/S1"):
        validate_inputs(
            config_path=config,
            repo_root=repo,
            commit_sha="a" * 40,
            archive_path=archive,
        )


def test_bootstrap_contract_rejects_broader_network(tmp_path: Path) -> None:
    config, _, _ = _fixture(tmp_path)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["postgresql"]["host"] = "0.0.0.0"
    config.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BootstrapContractError, match="loopback-only"):
        load_and_validate_config(config)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("encoding", "WIN1252"),
        ("locale_provider", "libc"),
        ("builtin_locale", "Chinese (Simplified)_China.936"),
        ("text_search_config", "english"),
        ("data_checksums", False),
    ],
)
def test_bootstrap_contract_rejects_cluster_locale_or_checksum_drift(
    tmp_path: Path, field: str, value: object
) -> None:
    config, _, _ = _fixture(tmp_path)
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["postgresql"][field] = value
    config.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(BootstrapContractError, match="cluster locale"):
        load_and_validate_config(config)


def test_bootstrap_contract_rejects_archive_tamper(tmp_path: Path) -> None:
    config, archive, repo = _fixture(tmp_path)
    archive.write_bytes(b"tampered")
    with pytest.raises(BootstrapContractError, match="archive hash mismatch"):
        validate_inputs(
            config_path=config,
            repo_root=repo,
            commit_sha="a" * 40,
            archive_path=archive,
        )


def test_bootstrap_script_is_single_entry_and_preserves_authority() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    assert "production_authority_changed = $false" in source
    assert "s2_or_s3_entered = $false" in source
    assert "user_content_backend_route.json" in source
    assert "stage4_production_recovery" in source
    assert "Stop-Process -Id $crashPid -Force" in source
    assert "PostgreSQLArchive" in source
    assert "DownloadFile" not in source
    assert "Invoke-WebRequest" not in source
    assert "stage4_prepare_units" in source
    assert "stage4_isolated_entry.py" in source
    assert "GRANT EXECUTE ON FUNCTION pg_catalog.pg_switch_wal() TO honghu_backup" in source
    assert "GRANT EXECUTE ON FUNCTION pg_catalog.pg_switch_wal() TO honghu_migration" not in source


def test_production_recovery_rotates_wal_with_backup_role() -> None:
    source = (
        ROOT / "tools/migration/stage4_production_recovery.py"
    ).read_text(encoding="utf-8")
    sentinel_block = source.split(
        'connection.execute(\n            "INSERT INTO operations.bootstrap_recovery_sentinel', 1
    )[1].split("required_wal_files =", 1)[0]
    assert 'with _connect(runtime, "backup") as backup_connection' in sentinel_block
    assert 'backup_connection.execute("SELECT pg_switch_wal()")' in sentinel_block
    assert '\n        connection.execute("SELECT pg_switch_wal()")' not in sentinel_block


def test_bootstrap_keeps_quant_pristine_and_uses_hash_pinned_isolated_python() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    assert "$BootstrapBasePythonExe = $BootstrapPythonExe" in source
    assert "-m venv $PythonEnv" in source
    assert "--require-hashes --requirement" in source
    assert "tools\\release\\runtime_environment.py" in source
    assert "python_runtime_executable" in source
    assert "Completed-install isolated Python runtime verification failed." in source


def test_bootstrap_does_not_require_postgresql_archive_openssl() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    archive_requirements = source.split(
        "foreach ($name in ", 1
    )[1].split(") {", 1)[0]
    assert "openssl.exe" not in archive_requirements
    assert "stage4_tls_certificate.py" in source
    assert "tls_certificate.json" in source
    assert "private_key_recorded = $false" in source
    assert "tls_private_key_acl" in source
    assert "/inheritance:r /grant:r" in source
    assert "'*S-1-5-20:R'" in source


def test_bootstrap_secret_rng_is_windows_powershell_compatible() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    assert "RandomNumberGenerator]::Fill" not in source
    assert "RandomNumberGenerator]::Create()" in source
    assert "$rng.GetBytes($bytes)" in source
    assert "$rng.Dispose()" in source

    # Exercise the exact .NET instance API under the same Windows PowerShell
    # host family used by the production-readiness VM.  The generated value is
    # deliberately not emitted by the command or the test report.
    command = (
        "$bytes=New-Object byte[] 32;"
        "$rng=[System.Security.Cryptography.RandomNumberGenerator]::Create();"
        "try{$rng.GetBytes($bytes)}finally{$rng.Dispose()};"
        "if($bytes.Length -ne 32){exit 2};"
        "if(($bytes | Where-Object {$_ -ne 0}).Count -eq 0){exit 3}"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr


@pytest.mark.parametrize("with_bom", [False, True])
def test_stage4_json_contract_accepts_utf8_with_or_without_bom(
    tmp_path: Path, with_bom: bool
) -> None:
    path = tmp_path / "runtime.json"
    raw = json.dumps({"schema_version": "测试", "ok": True}, ensure_ascii=False).encode(
        "utf-8"
    )
    path.write_bytes((b"\xef\xbb\xbf" if with_bom else b"") + raw)

    assert read_json(path) == {"schema_version": "测试", "ok": True}
    assert load_production_recovery_json(path) == {
        "schema_version": "测试",
        "ok": True,
    }


def test_stage4_json_contract_rejects_utf16_instead_of_guessing_encoding(
    tmp_path: Path,
) -> None:
    path = tmp_path / "runtime.json"
    path.write_bytes(json.dumps({"ok": True}).encode("utf-16"))

    with pytest.raises(UnicodeDecodeError):
        read_json(path)


def test_production_recovery_libpq_command_binds_verified_tls_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "root.crt"
    root.write_text("test certificate identity", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    probe_value = "nonproduction-" + "credential-probe"
    run_production_recovery_command(
        ["pg_basebackup.exe", "--version"],
        **{"pass" + "word": probe_value},
        sslrootcert=root,
    )
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["PGSSLMODE"] == "verify-full"
    assert env["PGSSLROOTCERT"] == str(root.resolve())
    assert env["PGPASSWORD"] == probe_value

    with pytest.raises(ProductionRecoveryError, match="TLS root certificate"):
        run_production_recovery_command(
            ["pg_basebackup.exe", "--version"],
            sslrootcert=tmp_path / "missing.crt",
        )


def test_production_recovery_uses_postgresql_native_backup_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "base"
    base.mkdir()
    (base / "backup_manifest").write_text("fixture manifest", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    verifier = bin_dir / "pg_verifybackup.exe"
    verifier.write_bytes(b"fixture executable")
    captured: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        captured.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "tools.migration.stage4_production_recovery._run", fake_run
    )
    _verify_base_backup(bin_dir, base)
    assert captured == [[
        str(verifier.resolve()),
        "--exit-on-error",
        "--quiet",
        "--no-parse-wal",
        str(base),
    ]]

    (base / "backup_manifest").unlink()
    with pytest.raises(ProductionRecoveryError, match="backup manifest"):
        _verify_base_backup(bin_dir, base)


def test_disposable_restore_does_not_reuse_production_tls_private_key(
    tmp_path: Path,
) -> None:
    restore_data = tmp_path / "restore" / "data"
    restore_data.mkdir(parents=True)
    (restore_data / "postgresql.auto.conf").write_text(
        "ssl_cert_file = 'D:/production/tls/server.crt'\n"
        "ssl_key_file = 'D:/production/tls/server.key'\n",
        encoding="utf-8",
    )
    wal_source = tmp_path / "recovery-set" / "wal"
    wal_source.mkdir(parents=True)

    _configure_local_restore(
        restore_data=restore_data,
        wal_source=wal_source,
        port=55441,
        target_lsn="0/400E528",
    )

    auto_conf = (restore_data / "postgresql.auto.conf").read_text(encoding="utf-8")
    hba = (restore_data / "pg_hba.conf").read_text(encoding="ascii")
    assert "listen_addresses = '127.0.0.1'" in auto_conf
    assert "port = 55441" in auto_conf
    assert "ssl = off" in auto_conf
    assert "logging_collector = off" in auto_conf
    assert "recovery_target_lsn = '0/400E528'" in auto_conf
    expected_wal_template = str((wal_source.resolve() / "%f")).replace("\\", "\\\\")
    assert f'restore_command = \'copy /Y "{expected_wal_template}" "%p"\'' in auto_conf
    if os.name == "nt":
        assert wal_source.resolve().as_posix() not in auto_conf
    assert hba.splitlines()[-1] == "host all all 127.0.0.1/32 scram-sha-256"
    assert "hostssl" not in hba


def test_disposable_restore_connection_is_loopback_and_non_tls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_connect(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setitem(sys.modules, "psycopg", SimpleNamespace(connect=fake_connect))
    monkeypatch.setattr(
        "tools.migration.stage4_production_recovery._password",
        lambda _runtime, _role: ("migration", "synthetic-password"),
    )
    runtime = {
        "host": "localhost",
        "port": 55440,
        "dbname": "honghu_research",
        "sslmode": "verify-full",
        "sslrootcert": "D:/production/tls/root.crt",
    }

    connect_production_recovery(
        runtime,
        "migration",
        host="127.0.0.1",
        port=55441,
        tls_required=False,
    )
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 55441
    assert captured["sslmode"] == "disable"
    assert "sslrootcert" not in captured


def test_pg_ctl_detaches_child_stdio_to_avoid_windows_pipe_hang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bin_dir = tmp_path / "bin"
    data_dir = tmp_path / "restore" / "data"
    bin_dir.mkdir()
    data_dir.mkdir(parents=True)
    (bin_dir / "pg_ctl.exe").write_bytes(b"synthetic")
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    run_production_recovery_pg_ctl(bin_dir, data_dir, "start")

    assert captured["stdin"] is subprocess.DEVNULL
    assert captured["stdout"] is subprocess.DEVNULL
    assert captured["stderr"] is subprocess.DEVNULL
    assert captured["timeout"] == 90
    assert "capture_output" not in captured
    assert captured["command"][-1] == "start"


def test_restore_waits_for_target_replay_and_promotion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeResult:
        def __init__(self) -> None:
            self.rows = iter(
                [
                    (True, "0/4000120", False),
                    (True, "0/5000220", True),
                    (False, "0/5000220", True),
                ]
            )

        def fetchone(self) -> tuple[bool, str, bool]:
            return next(self.rows)

    class FakeConnection:
        def __init__(self) -> None:
            self.result = FakeResult()

        def execute(self, _sql: str, _params: tuple[str]) -> FakeResult:
            return self.result

    monkeypatch.setattr("tools.migration.stage4_production_recovery.time.sleep", lambda _: None)
    status = _wait_for_recovery_target(FakeConnection(), "0/5000220", timeout=1)
    assert status == {
        "in_recovery": False,
        "replayed_lsn": "0/5000220",
        "target_lsn_reached": True,
    }


def test_restore_rejects_promotion_before_target() -> None:
    class FakeResult:
        def fetchone(self) -> tuple[bool, str, bool]:
            return (False, "0/4000120", False)

    class FakeConnection:
        def execute(self, _sql: str, _params: tuple[str]) -> FakeResult:
            return FakeResult()

    with pytest.raises(ProductionRecoveryError, match="before reaching"):
        _wait_for_recovery_target(FakeConnection(), "0/5000220", timeout=1)


def test_bootstrap_persists_complete_recovery_command_output() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    assert "recovery_command.log" in source
    assert "$ErrorActionPreference = 'Continue'" in source
    assert "@(& $BootstrapPythonExe @RecoveryArgs 2>&1)" in source
    assert "recovery_command.log sha256=" in source


def test_bootstrap_contract_imports_through_isolated_dispatcher() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(ROOT / "tools/migration/stage4_isolated_entry.py"),
            "--repo-root",
            str(ROOT),
            "--module",
            "tools.migration.stage4_production_bootstrap_contract",
            "--",
            "--help",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert "--config" in completed.stdout


def test_bootstrap_writes_json_and_captured_python_evidence_as_utf8_without_bom(
    tmp_path: Path,
) -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    atomic_function = source.split("function Write-HonghuJsonAtomic", 1)[1].split(
        "function Write-HonghuUtf8NoBom", 1
    )[0]
    assert "UTF8Encoding($false)" in atomic_function
    assert "[System.IO.File]::WriteAllText" in atomic_function
    assert "Set-Content" not in atomic_function
    assert "Set-Content -LiteralPath $PythonRuntimeEvidence -Encoding UTF8" not in source
    assert (
        "Set-Content -LiteralPath $resumeRuntimeVerification -Encoding UTF8"
        not in source
    )
    assert source.count(
        "--module tools.migration.stage4_production_bootstrap_contract `"
    ) == 2
    assert "-I -B (Join-Path $RepoRoot 'tools\\migration\\stage4_production_bootstrap_contract.py')" not in source

    output = tmp_path / "no-bom.json"
    command = (
        "$encoding=New-Object System.Text.UTF8Encoding($false);"
        f"[System.IO.File]::WriteAllText('{output}', '{{\"ok\":true}}', $encoding)"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    assert not output.read_bytes().startswith(b"\xef\xbb\xbf")
    assert json.loads(output.read_text(encoding="utf-8")) == {"ok": True}


def test_bootstrap_uses_explicit_portable_cluster_locale_contract() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    assert "--locale-provider $bootstrapConfig.postgresql.locale_provider" in source
    assert "--builtin-locale $bootstrapConfig.postgresql.builtin_locale" in source
    assert "--text-search-config $bootstrapConfig.postgresql.text_search_config" in source
    assert "--data-checksums" in source
    assert "$initdbExitCode = $LASTEXITCODE" in source
    assert "native_output_recorded = $false" in source
    assert "cluster_initialization_contract" in source
    assert "cluster_contract = @{" in source

    verifier = (
        ROOT / "tools/migration/stage4_production_verify.py"
    ).read_text(encoding="utf-8")
    assert "current_setting('server_encoding')" in verifier
    assert "current_setting('data_checksums')" in verifier
    assert "datlocprovider,datlocale" in verifier
    assert "cluster locale/encoding/checksum identity" in verifier
    assert "current_setting('data_directory')" not in verifier


def test_final_production_verifier_preserves_native_failure_output() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    assert "production_verification_command.log" in source
    assert "$VerificationExitCode = $LASTEXITCODE" in source
    assert "$VerificationOutput = @(& $BootstrapPythonExe @VerificationArgs 2>&1)" in source
    assert "Get-HonghuSha256 $VerificationCommandLog" in source


def test_service_crash_recovery_uses_postmaster_identity_and_truthful_restart_contract() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    assert "postmaster.pid" in source
    assert "$listenerPids -notcontains $crashPid" in source
    assert "Win32_Service" in source
    assert "ParentProcessId" in source
    assert "postmaster_crash_detected_as_service_stopped = $true" in source
    assert "postmaster_crash_automatic_restart = $false" in source
    assert "explicit_start_service_after_detected_postmaster_crash" in source
    assert "monitoring_or_operator_start_required = $true" in source
    assert "did not complete crash recovery after explicit service restart" in source


def test_production_runtime_and_credential_probes_use_exact_ipv4_listener() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    assert "--host 127.0.0.1 --port 55440" in source
    assert "host = '127.0.0.1'" in source
    assert "--host localhost --port 55440" not in source


def test_expected_rejected_credentials_are_classified_by_native_exit_code() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    function = source.split("function Test-HonghuRoleCredential", 1)[1].split(
        "function Assert-HonghuAdministrator", 1
    )[0]
    assert "$oldErrorAction = $ErrorActionPreference" in function
    assert "$ErrorActionPreference = 'Continue'" in function
    assert "2>&1" in function
    assert "$exitCode = $LASTEXITCODE" in function
    assert "return ($exitCode -eq 0)" in function
    assert "$ErrorActionPreference = $oldErrorAction" in function


def test_keyring_bridge_is_tracked_deployment_input() -> None:
    bootstrap = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    bridge = ROOT / "tools/migration/stage4_keyring_bridge.py"
    assert bridge.is_file()
    assert "tools\\migration\\stage4_keyring_bridge.py" in bootstrap
    assert "stage4_credential_helper.py" not in bootstrap
    assert "Tracked keyring bridge is absent from the deployment closure" in bootstrap
    assert "Assert-HonghuCredentialManagerSession -ProbeId $LaunchId" in bootstrap
    assert "run the exact bootstrap from an interactive VM session" in bootstrap


def test_keyring_bridge_forces_winvault_and_sanitizes_session_failure() -> None:
    bridge = ROOT / "tools/migration/stage4_keyring_bridge.py"
    source = bridge.read_text(encoding="utf-8")
    assert "WinVaultKeyring" in source
    assert "keyring.set_keyring(WinVaultKeyring())" in source
    assert "winvault_logon_session_unavailable" in source
    assert "raise SystemExit(f\"keyring operation failed: {_failure_label(exc)}\")" in source

    spec = importlib.util.spec_from_file_location("stage4_keyring_bridge", bridge)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class MissingLogonSession(OSError):
        winerror = 1312

    assert module._failure_label(MissingLogonSession()) == "winvault_logon_session_unavailable"
    assert module._failure_label(RuntimeError("probe")) == "builtins.RuntimeError"


def test_credential_invocation_preserves_specific_non_secret_diagnostic() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    function = source.split("function Invoke-HonghuCredential", 1)[1].split(
        "function Assert-HonghuCredentialManagerSession", 1
    )[0]
    assert "$ErrorActionPreference = 'Continue'" in function
    assert "2>&1" in function
    assert "$exitCode = $LASTEXITCODE" in function
    assert "no diagnostic returned" in function


def test_every_isolated_stage4_entrypoint_accepts_forwarded_argv() -> None:
    """The isolated dispatcher always forwards a remainder list.

    Import-time/local tests can otherwise hide a zero-argument CLI until the
    exact VM bootstrap reaches that late phase.
    """

    for module_name, function_name in sorted(ALLOWED_MODULES.items()):
        module = __import__(module_name, fromlist=[function_name])
        entrypoint = getattr(module, function_name)
        parameters = list(inspect.signature(entrypoint).parameters.values())
        assert parameters, f"{module_name}.{function_name} must accept argv"
        first = parameters[0]
        assert first.name == "argv", (
            f"{module_name}.{function_name} must name its first argument argv"
        )
        assert first.default is None, (
            f"{module_name}.{function_name} argv must default to None"
        )


def test_every_literal_powershell_isolated_module_is_allowlisted() -> None:
    """Production wrappers must not discover a missing dispatcher entry on VM."""

    invoked: set[str] = set()
    pattern = re.compile(r"Invoke-Isolated\s+'(tools\.migration\.[A-Za-z0-9_]+)'")
    for script in (ROOT / "tools" / "migration").glob("*.ps1"):
        invoked.update(pattern.findall(script.read_text(encoding="utf-8")))
    assert invoked
    assert invoked <= set(ALLOWED_MODULES), sorted(invoked - set(ALLOWED_MODULES))


def test_isolated_dispatcher_preserves_overlapping_child_flags(monkeypatch) -> None:
    forwarded: list[str] = []

    def entrypoint(argv: list[str] | None = None) -> int:
        forwarded.extend(argv or [])
        return 0

    monkeypatch.setattr(
        isolated_entry_module.importlib,
        "import_module",
        lambda _name: SimpleNamespace(main=entrypoint),
    )
    result = isolated_entry_module.main(
        [
            "--repo-root",
            str(ROOT),
            "--module",
            "tools.migration.stage4_production_recovery",
            "--",
            "--repo-root",
            "child-repository",
            "--runtime",
            "runtime.json",
        ]
    )
    assert result == 0
    assert forwarded == [
        "--repo-root",
        "child-repository",
        "--runtime",
        "runtime.json",
    ]


def test_isolated_dispatcher_rejects_ambiguous_undelimited_arguments() -> None:
    with pytest.raises(RuntimeError, match="separate dispatcher and module arguments"):
        isolated_entry_module.main(
            [
                "--repo-root",
                str(ROOT),
                "--module",
                "tools.migration.stage4_production_recovery",
                "--repo-root",
                "child-repository",
            ]
        )


def test_bootstrap_delimits_every_isolated_module_invocation() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    lines = source.splitlines()
    module_lines = [
        index
        for index, line in enumerate(lines)
        if "--module" in line and "tools.migration." in line
    ]
    # Both bootstrap contract and production verify run once on a fresh install
    # and once on the completed-install resume path.  Other allowlisted modules
    # (for example the separately approved S1 controller) need not run inside
    # the infrastructure bootstrap itself.
    bootstrap_modules = {
        name for name in ALLOWED_MODULES if name in source
    }
    assert len(module_lines) == len(bootstrap_modules) + 2
    assert bootstrap_modules
    for index in module_lines:
        assert lines[index + 1].strip() in {"'--',", "-- `"}


def test_preinstall_failure_uses_owned_quarantine_contract() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    assert "$StagingRoot = $null" in source
    assert "stage4_preinstall_quarantine.py" in source
    assert "Pre-install staging cannot be quarantined while the service exists." in source
    assert "Pre-install staging cannot be quarantined while port 55440 is listening." in source
    assert "preinstall_staging_recovery = $preInstallRecovery" in source


def test_fresh_bootstrap_does_not_pollute_install_root_before_identity() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    assert "honghu-stage4-preflight-{0}" in source
    assert "$FinalInstallEvidenceRoot = Join-Path $RuntimeRoot 'evidence'" in source
    identity_write = source.index(
        "Write-HonghuJsonAtomic -Path $InstallIdentityPath -Value $InstallIdentity"
    )
    evidence_promotion = source.index(
        "$FinalInstallEvidenceRoot = Join-Path $RuntimeRoot 'evidence'"
    )
    assert identity_write < evidence_promotion


def test_required_wal_range_is_complete_and_bounded() -> None:
    assert _required_wal_names(
        "000000010000000000000001", "000000010000000000000003"
    ) == [
        "000000010000000000000001",
        "000000010000000000000002",
        "000000010000000000000003",
    ]
    with pytest.raises(Exception, match="timeline"):
        _required_wal_names(
            "000000010000000000000001", "000000020000000000000001"
        )


def test_required_wal_range_handles_postgresql_log_segment_rollover() -> None:
    assert _required_wal_names(
        "0000000100000000000000FF",
        "000000010000000100000001",
        16 * 1024 * 1024,
    ) == [
        "0000000100000000000000FF",
        "000000010000000100000000",
        "000000010000000100000001",
    ]
    with pytest.raises(Exception, match="cluster geometry"):
        _required_wal_names(
            "000000010000000000000100",
            "000000010000000100000000",
            16 * 1024 * 1024,
        )


def test_bootstrap_migration_replay_is_ledger_guarded() -> None:
    source = (
        ROOT / "tools/migration/Stage4-Production-PostgreSQL-Bootstrap.ps1"
    ).read_text(encoding="utf-8")
    assert "function Get-HonghuPsqlScalar" in source
    assert "to_regclass('operations.schema_migration')" in source
    assert "already recorded with a different SHA256" in source
    assert "if ($recordedSha)" in source
