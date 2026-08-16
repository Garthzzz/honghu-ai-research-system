import sys

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
