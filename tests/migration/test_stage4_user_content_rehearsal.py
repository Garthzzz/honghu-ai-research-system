from pathlib import Path

import pytest

from tools.migration.stage4_user_content_rehearsal import (
    TEST_DATABASE_PREFIX,
    _schema_identity,
    validate_rehearsal_target,
)


ROOT = Path(__file__).resolve().parents[2]


def test_stage4_target_is_loopback_nonstandard_and_test_named() -> None:
    validate_rehearsal_target("127.0.0.1", 55432, f"{TEST_DATABASE_PREFIX}notes")
    with pytest.raises(ValueError, match="loopback"):
        validate_rehearsal_target("0.0.0.0", 55432, f"{TEST_DATABASE_PREFIX}notes")
    with pytest.raises(ValueError, match="5432"):
        validate_rehearsal_target("127.0.0.1", 5432, f"{TEST_DATABASE_PREFIX}notes")
    with pytest.raises(ValueError, match="must start"):
        validate_rehearsal_target("127.0.0.1", 55432, "research")


def test_stage4_expand_preserves_0001_and_adds_cutover_contract() -> None:
    sql = (ROOT / "migrations/postgresql/0002_user_content_notes_cutover_expand.sql").read_text(
        encoding="utf-8"
    )
    upper = sql.upper()
    assert "DROP TABLE" not in upper
    assert "DROP COLUMN" not in upper
    assert "Q_LABEL TEXT" in upper
    assert "LEGACY_ENTITY_ID_TEXT TEXT" in upper
    assert "CUTOVER_UNIT_AUTHORITY" in upper
    assert "CUTOVER_UNIT_AUTHORITY_REVISION" in upper
    assert "CUTOVER_DEPENDENCY_MAPPING" in upper
    assert "CUTOVER_DEPENDENCY_MAPPING_REVISION" in upper
    assert "POSTGRESQL_FIRST_FORMAL_COMMIT" in upper
    assert "S2/S3/S4 AUTHORITY BACKEND MUST REMAIN POSTGRESQL" in upper
    assert "S3 TO S4 MUST PRESERVE AUTHORITY IDENTITY AND USE A NEW APPROVAL REFERENCE" in upper
    assert "ACTOR, APPROVAL REFERENCE AND REASON ARE REQUIRED" in upper
    assert "S2 CANNOT RETURN TO S1 AFTER A FORMAL COMMIT" in upper
    assert "POSTGRESQL ANALYST-NOTE WRITER IS FENCED" in upper
    assert "P_WRITER_IDENTITY <> SESSION_USER" in upper
    assert "UNVERIFIED ENTITY IDENTITY MAPPING" in upper
    assert "REGISTER_USER_CONTENT_NOTES_DEPENDENCY_MAPPING" in upper
    assert "DEPENDENCY MAPPING CHANGES ARE FENCED IN THE CURRENT AUTHORITY STATE" in upper
    assert "STABLE BUSINESS IDENTITIES ARE DELIBERATELY MANY-TO-ONE" in upper
    assert "STABLE DEPENDENCY IDENTITY IS ALREADY MAPPED" not in upper
    assert "PUT_ANALYST_NOTE_V2" in upper
    assert "SOFT_DELETE_ANALYST_NOTE_V2" in upper
    assert "PROMOTE_USER_CONTENT_NOTES_ON_FIRST_FORMAL_MUTATION" in upper
    assert "FORMAL MUTATION AUTHORITY IS FENCED" in upper
    assert "REVOKE ALL ON FUNCTION" in upper
    assert "SECURITY DEFINER" in upper
    assert "ANALYST_NOTE_READ_V1" in upper
    assert "USER_CONTENT_NOTES_AUTHORITY_V1" in upper
    assert "ANALYST_NOTE_IDENTITY_V1" in upper


def test_stage4_role_grants_keep_application_roles_off_base_tables() -> None:
    sql = (ROOT / "migrations/postgresql/0002_user_content_notes_role_grants.sql").read_text(
        encoding="utf-8"
    )
    upper = sql.upper()
    assert "REVOKE ALL ON ALL TABLES" in upper
    assert "GRANT SELECT ON USER_CONTENT.ANALYST_NOTE_READ_V1" in upper
    assert "GRANT SELECT ON USER_CONTENT.ANALYST_NOTE_IDENTITY_V1" in upper
    assert "GRANT SELECT ON OPERATIONS.USER_CONTENT_NOTES_AUTHORITY_V1" in upper
    assert "GRANT EXECUTE ON FUNCTION USER_CONTENT.PUT_ANALYST_NOTE_V2" in upper
    assert "GRANT EXECUTE ON FUNCTION OPERATIONS.TRANSITION_USER_CONTENT_NOTES" in upper
    assert "GRANT EXECUTE ON FUNCTION OPERATIONS.REGISTER_USER_CONTENT_NOTES_DEPENDENCY_MAPPING" in upper
    assert "GRANT EXECUTE ON FUNCTION OPERATIONS.TRANSITION_CUTOVER_UNIT" not in upper
    assert "GRANT INSERT ON USER_CONTENT.ANALYST_NOTE" not in upper


def test_stage4_rehearsal_covers_state_and_compatibility_failures() -> None:
    sql = (
        ROOT / "migrations/postgresql/0002_user_content_notes_cutover_rehearsal.sql"
    ).read_text(encoding="utf-8")
    upper = sql.upper()
    assert "REHEARSAL_S1_ABANDON" in upper
    assert "REHEARSAL_S2_NO_FORMAL_WRITE" in upper
    assert "Q6" in upper
    assert "AI_DATACENTER" in upper
    assert "FIRST-FORMAL-DELETE-1" in upper
    assert "MISSING S2 DELETE UNEXPECTEDLY SUCCEEDED" in upper
    assert "VERIFICATION-AFTER-FAILED-DELETE" in upper
    assert "USER_CONTENT.SOFT_DELETE_ANALYST_NOTE_V2" in upper
    assert "DELETE-FIRST FORMAL WATERMARK WAS NOT PRESERVED" in upper
    assert "FORMAL-CREATE-1" in upper
    assert "S4 WITH SQLITE BACKEND UNEXPECTEDLY SUCCEEDED" in upper
    assert "S4 WITHOUT APPROVAL UNEXPECTEDLY SUCCEEDED" in upper
    assert "S4 WITH WRITER DRIFT UNEXPECTEDLY SUCCEEDED" in upper
    assert "S4 WITH REUSED APPROVAL UNEXPECTEDLY SUCCEEDED" in upper
    assert "STAGE4-S4-APPROVED" in upper
    assert "UNMAPPED DEPENDENCY UNEXPECTEDLY SUCCEEDED" in upper
    assert "STAGE4-INCREMENTAL-MAPPING-APPROVED" in upper
    assert upper.count("COMPANY:COHU:US-EQUITY") >= 3
    assert "STABLE_ALIAS_COUNT" in upper
    assert "STALE UPDATE UNEXPECTEDLY SUCCEEDED" in upper
    assert "SOFT_DELETE_ANALYST_NOTE_V2" in upper
    assert "AUTHORITY_STATE" in upper


def test_schema_identity_ignores_row_growth_but_detects_schema_change() -> None:
    before = {
        "databases": {
            "research.db": {
                "user_version": 0,
                "tables": [
                    {"name": "analyst_note", "schema_sha256": "abc", "row_count": 0}
                ],
            }
        }
    }
    after = {
        "databases": {
            "research.db": {
                "user_version": 0,
                "tables": [
                    {"name": "analyst_note", "schema_sha256": "abc", "row_count": 9}
                ],
            }
        }
    }
    assert _schema_identity(before) == _schema_identity(after)
    after["databases"]["research.db"]["tables"][0]["schema_sha256"] = "changed"
    assert _schema_identity(before) != _schema_identity(after)


def test_rehearsal_cleanup_does_not_mask_primary_failure() -> None:
    source = (ROOT / "tools/migration/stage4_user_content_rehearsal.py").read_text(
        encoding="utf-8"
    )
    assert "primary_error.add_note(message)" in source
    assert "drop database" in source
    assert "drop role" in source


def test_rehearsal_executes_real_reader_writer_adapter_contract() -> None:
    source = (ROOT / "tools/migration/stage4_user_content_rehearsal.py").read_text(
        encoding="utf-8"
    )
    assert "_run_adapter_rehearsal" in source
    assert "stale_route_fenced" in source
    assert "schema_compatible_reader" in source
    assert "reader_writer_roles_distinct" in source
