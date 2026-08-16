from tools.release.direct_candidate import ALLOWED_MODULES


def test_direct_candidate_allows_reviewed_stage5_migration_entrypoint():
    assert (
        ALLOWED_MODULES["tools.migration.stage4_apply_postgresql_migrations"]
        == "main"
    )
