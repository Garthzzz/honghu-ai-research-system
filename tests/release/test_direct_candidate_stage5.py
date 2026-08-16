import sys
from types import SimpleNamespace

from tools.release import direct_candidate
from tools.release.direct_candidate import ALLOWED_MODULES, prepare_import_path


def test_direct_candidate_allows_reviewed_stage5_migration_entrypoint():
    assert (
        ALLOWED_MODULES["tools.migration.stage4_apply_postgresql_migrations"]
        == "main"
    )


def test_locked_pywin32_extension_paths_are_explicit_without_pth_execution(tmp_path):
    (tmp_path / "win32" / "lib").mkdir(parents=True)
    original = list(sys.path)
    try:
        release_root, locked_site = prepare_import_path(tmp_path)
        assert sys.path[:4] == [
            str(release_root),
            str(locked_site),
            str(tmp_path / "win32"),
            str(tmp_path / "win32" / "lib"),
        ]
    finally:
        sys.path[:] = original


def test_outer_bootstrap_preserves_distinct_inner_site_packages_option(
    monkeypatch, tmp_path
):
    captured = {}

    def entrypoint(argv):
        captured["argv"] = argv
        return 0

    monkeypatch.setattr(direct_candidate, "prepare_import_path", lambda _path: None)
    monkeypatch.setattr(
        direct_candidate.importlib,
        "import_module",
        lambda _name: SimpleNamespace(main=entrypoint),
    )
    assert direct_candidate.main([
        "--site-packages", str(tmp_path / "outer"),
        "--module", "tools.operations.task_service_preflight",
        "--locked-site-packages", str(tmp_path / "inner"),
    ]) == 0
    assert captured["argv"] == [
        "--locked-site-packages", str(tmp_path / "inner")
    ]
