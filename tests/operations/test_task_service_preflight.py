from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tools.operations import task_service_preflight
from tools.release.direct_candidate import ALLOWED_MODULES
from tools.operations.task_credential_transfer import TASK_ROLES


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "config/operations/production_tasks.json"


class Connection:
    def __init__(self, user: str, database: str = "honghu"):
        self.user = user
        self.database = database

    def execute(self, _query: str):
        return self

    def fetchone(self):
        return self.user, self.database, "on"

    def close(self):
        return None


def _run(tmp_path: Path, monkeypatch, *, wrong_user: bool = False, write_denied: bool = True):
    release = tmp_path / "release"
    release.mkdir()
    (release / "RELEASE_MANIFEST.json").write_text(
        json.dumps({"commit_sha": "a" * 40}), encoding="utf-8"
    )
    catalog_path = tmp_path / "postgresql_runtime.json"
    catalog_path.write_text("{}", encoding="utf-8")
    registry_path = tmp_path / "registry.json"
    registry_path.write_text("{}", encoding="utf-8")
    roles = {name: SimpleNamespace(user=f"pg_{name}") for name in TASK_ROLES}
    catalog = SimpleNamespace(roles=roles, dbname="honghu", role=lambda name: roles[name])
    monkeypatch.setattr(task_service_preflight, "load_postgres_runtime_catalog", lambda _: catalog)
    monkeypatch.setattr(task_service_preflight, "_readable", lambda _: True)
    monkeypatch.setattr(task_service_preflight, "_write_is_denied", lambda _: write_denied)
    monkeypatch.setattr(task_service_preflight, "_writable", lambda _: True)
    monkeypatch.setattr(task_service_preflight.getpass, "getuser", lambda: "HonghuTaskRunner")
    monkeypatch.setattr(task_service_preflight.socket, "gethostname", lambda: "DESKTOP-VGD07J4")

    def factory(_catalog, *, role: str):
        observed = "wrong_user" if wrong_user and role == "reader" else roles[role].user
        return lambda: Connection(observed)

    monkeypatch.setattr(task_service_preflight, "build_catalog_connection_factory", factory)
    return task_service_preflight.run_service_account_preflight(
        release_dir=release,
        site_packages=tmp_path / "site-packages",
        manifest_path=MANIFEST,
        runtime_catalog_path=catalog_path,
        registry_path=registry_path,
        runtime_dir=tmp_path / "runtime",
        data_root=tmp_path / "data",
        content_root=tmp_path / "content",
        expected_principal=r"DESKTOP-VGD07J4\HonghuTaskRunner",
    )


def test_service_preflight_binds_release_manifest_access_and_current_users(
    tmp_path: Path, monkeypatch
) -> None:
    result = _run(tmp_path, monkeypatch)
    assert result["application_commit_sha"] == "a" * 40
    assert result["checked_at"].endswith("+00:00")
    assert result["task_manifest_sha256"]
    assert result["access_verified"] is True
    assert result["postgresql_roles_verified"] is True
    assert result["overall_verified"] is True
    assert len(result["postgresql_roles"]) == 4
    assert result["secret_recorded"] is False


def test_service_preflight_fails_when_readonly_root_is_writable(
    tmp_path: Path, monkeypatch
) -> None:
    result = _run(tmp_path, monkeypatch, write_denied=False)
    assert result["access_verified"] is False
    assert result["overall_verified"] is False


def test_service_preflight_fails_when_current_user_differs(
    tmp_path: Path, monkeypatch
) -> None:
    result = _run(tmp_path, monkeypatch, wrong_user=True)
    assert result["postgresql_roles_verified"] is False
    assert result["overall_verified"] is False
def test_service_preflight_is_reachable_through_exact_release_bootstrap():
    assert ALLOWED_MODULES["tools.operations.task_service_preflight"] == "main"

