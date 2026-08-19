import sys
from types import SimpleNamespace

from tools.release import direct_candidate
from tools.release.direct_candidate import ALLOWED_MODULES, prepare_import_path


def test_direct_candidate_allows_reviewed_stage5_migration_entrypoint():
    assert (
        ALLOWED_MODULES["tools.migration.stage4_apply_postgresql_migrations"]
        == "main"
    )


def test_direct_candidate_allows_reviewed_release_binding_and_valuation_history():
    assert (
        ALLOWED_MODULES["tools.migration.stage4_runtime_release_binding"] == "main"
    )
    assert (
        ALLOWED_MODULES["tools.financial.fiber_yfinance_valuation_history"] == "main"
    )


def test_direct_candidate_allows_task_enable_evidence_entrypoint():
    assert ALLOWED_MODULES["tools.operations.task_enable_evidence"] == "main"


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


def test_locked_pywin32_dll_directory_is_registered_and_retained(monkeypatch, tmp_path):
    (tmp_path / "win32" / "lib").mkdir(parents=True)
    (tmp_path / "pywin32_system32").mkdir()
    handles = []
    handle = object()
    monkeypatch.setattr(direct_candidate.os, "name", "nt")
    monkeypatch.setattr(
        direct_candidate.os,
        "add_dll_directory",
        lambda path: handles.append(path) or handle,
    )
    before = list(direct_candidate._DLL_DIRECTORY_HANDLES)
    original_path = list(sys.path)
    try:
        prepare_import_path(tmp_path)
        assert handles == [str(tmp_path / "pywin32_system32")]
        assert direct_candidate._DLL_DIRECTORY_HANDLES[-1] is handle
    finally:
        sys.path[:] = original_path
        direct_candidate._DLL_DIRECTORY_HANDLES[:] = before


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


def test_outer_bootstrap_preserves_same_named_inner_option_after_boundary(
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
        "--module", "tools.operations.task_runner",
        "--",
        "run", "--site-packages", str(tmp_path / "inner"),
    ]) == 0
    assert captured["argv"] == [
        "run", "--site-packages", str(tmp_path / "inner")
    ]
