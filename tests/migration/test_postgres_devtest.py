from pathlib import Path

import pytest

from tools.migration.postgres_devtest import TEST_DATABASE_PREFIX, validate_test_target


def test_devtest_target_requires_loopback_nonstandard_port_and_prefix() -> None:
    validate_test_target("127.0.0.1", 55432, f"{TEST_DATABASE_PREFIX}notes")
    with pytest.raises(ValueError, match="loopback"):
        validate_test_target("0.0.0.0", 55432, f"{TEST_DATABASE_PREFIX}notes")
    with pytest.raises(ValueError, match="5432"):
        validate_test_target("127.0.0.1", 5432, f"{TEST_DATABASE_PREFIX}notes")
    with pytest.raises(ValueError, match="must start"):
        validate_test_target("127.0.0.1", 55432, "research")


def test_migration_is_expand_only_and_has_revision_contract() -> None:
    sql = (
        Path(__file__).resolve().parents[2]
        / "migrations/postgresql/0001_user_content_notes_expand.sql"
    ).read_text(encoding="utf-8")
    upper = sql.upper()
    assert "CREATE TABLE" in upper
    assert "DROP TABLE" not in upper
    assert "ALTER TABLE" not in upper
    assert "EXPECTED_REVISION" in upper
    assert "IDEMPOTENCY" in upper
    assert "SOFT_DELETE" in upper
