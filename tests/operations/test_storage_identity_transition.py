from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import json
import tempfile
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

from tools.migration.stage4_recovery_set import sha256_json
from tools.operations.storage_identity_transition import (
    COLLECTOR_FACTS_SCHEMA,
    COLLECTOR_MAX_AGE_SECONDS,
    COLLECTOR_SIGNATURE_SCHEMA,
    COLLECTOR_SIGNED_FACTS_SCHEMA,
    COLLECTOR_SCHEMA,
    REMOTE_ATTESTATION_SCHEMA,
    SOURCE_HOST_IDENTITY_SCHEMA,
    STAGE5_EXECUTION_AUTHORIZATION_REFERENCE,
    TRANSITION_REASON,
    TRANSITION_SCHEMA,
    StorageIdentityTransitionError,
    artifact_anchor_identity,
    build_transition_from_collector_facts,
    collector_script_path,
    collector_script_sha256,
    collector_signed_facts,
    endpoint_identity,
    verify_storage_identity_transition,
)
from tools.release.direct_candidate import ALLOWED_MODULES


def test_transition_collector_module_is_allowed_by_isolated_bootstrap() -> None:
    assert ALLOWED_MODULES["tools.operations.storage_identity_transition"] == "main"


NOW = datetime(2026, 8, 17, 2, 0, tzinfo=timezone.utc)
SOURCE_MACHINE = "1" * 64
REMOTE_MACHINE = "2" * 64

_TEST_KEY = rsa.generate_private_key(public_exponent=65537, key_size=3072)
_TEST_CERT = (
    x509.CertificateBuilder()
    .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "HonghuStage5StorageAttestation")]))
    .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "HonghuStage5StorageAttestation")]))
    .public_key(_TEST_KEY.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime(2025, 1, 1, tzinfo=timezone.utc))
    .not_valid_after(datetime(2030, 1, 1, tzinfo=timezone.utc))
    .sign(_TEST_KEY, hashes.SHA256())
)
_TEST_CERT_DIR = tempfile.TemporaryDirectory()
TEST_CERT_PATH = Path(_TEST_CERT_DIR.name) / "collector.cer"
TEST_CERT_PATH.write_bytes(_TEST_CERT.public_bytes(serialization.Encoding.DER))
TEST_CERT_SHA256 = hashlib.sha256(TEST_CERT_PATH.read_bytes()).hexdigest()


def _signature(signed_facts: dict[str, object]) -> dict[str, object]:
    payload = json.dumps(
        signed_facts, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    signature = _TEST_KEY.sign(
        payload,
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
        hashes.SHA256(),
    )
    return {
        "schema_version": COLLECTOR_SIGNATURE_SCHEMA,
        "algorithm": "rsa-pss-sha256",
        "certificate_sha256": TEST_CERT_SHA256,
        "certificate_thumbprint": _TEST_CERT.fingerprint(hashes.SHA1()).hex(),
        "signed_payload_sha256": hashlib.sha256(payload).hexdigest(),
        "signed_payload_base64": base64.b64encode(payload).decode("ascii"),
        "signature_base64": base64.b64encode(signature).decode("ascii"),
    }


def _endpoint(server: str, address: str) -> dict[str, object]:
    return {
        "kind": "windows_unc",
        "server": server,
        "share": "honghupgrecovery",
        "resolved_addresses": [address],
        "volume_serial": "1234abcd",
        "filesystem": "NTFS",
    }


def _evidence() -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    old = _endpoint("old-endpoint", "10.0.0.8")
    new = _endpoint("new-endpoint", "10.0.0.9")
    signed_artifacts = [
        {"name": "000000010000000000000001", "size": 4, "sha256": "a" * 64}
    ]
    signed_artifacts_identity = sha256_json(signed_artifacts)
    anchor = artifact_anchor_identity(
        pointer_sha256="3" * 64,
        manifest_identity_sha256="4" * 64,
        manifest_file_sha256="5" * 64,
        artifacts_identity_sha256=signed_artifacts_identity,
        artifact_count=1,
    )
    collector_core = {
        "schema_version": COLLECTOR_SCHEMA,
        "collector_script_sha256": collector_script_sha256(),
        "host_name": "win-g7vo0dd37ce",
        "checked_at_utc": (NOW - timedelta(minutes=1)).isoformat(),
        "share_name": "honghupgrecovery",
        "share_local_path": r"D:\quant\industry_demo_backup_package\postgresql_recovery",
        "approved_backup_root": r"D:\quant\industry_demo_backup_package\postgresql_recovery",
        "share_local_path_verified": True,
        "unc_live_probe_path": r"\\new-endpoint\honghupgrecovery",
        "smb_endpoint_tcp_445_verified": True,
        "smb_transport_encryption_required": True,
        "machine_guid_sha256": REMOTE_MACHINE,
        "volume_serial": "1234abcd",
        "filesystem": "NTFS",
        "bitlocker": {
            "protection_status": "On",
            "volume_status": "FullyEncrypted",
            "encryption_percentage": 100.0,
            "verified": True,
        },
        "artifact_hashes_verified": True,
    }
    collector = {
        **collector_core,
        "collector_identity_sha256": sha256_json(collector_core),
    }
    attestation_core = {
        "schema_version": REMOTE_ATTESTATION_SCHEMA,
        "machine_guid_sha256": REMOTE_MACHINE,
        "share": "honghupgrecovery",
        "volume_serial": "1234abcd",
        "filesystem": "NTFS",
        "current_addresses": ["10.0.0.9"],
        "checked_at_utc": (NOW - timedelta(minutes=1)).isoformat(),
        "artifact_anchor_identity_sha256": anchor,
        "collector_identity_sha256": collector["collector_identity_sha256"],
    }
    attestation = {
        **attestation_core,
        "attestation_identity_sha256": sha256_json(attestation_core),
    }
    signed_facts = {
        "schema_version": COLLECTOR_SIGNED_FACTS_SCHEMA,
        "authorization_reference": STAGE5_EXECUTION_AUTHORIZATION_REFERENCE,
        "collector": collector_core,
        "source_host_identity_evidence": None,
        "source_machine_guid_sha256": SOURCE_MACHINE,
        "old_endpoint_core": old,
        "new_endpoint_core": new,
        "old_storage_identity": endpoint_identity(old),
        "new_storage_identity": endpoint_identity(new),
        "prior_pointer_sha256": "3" * 64,
        "prior_manifest_identity_sha256": "4" * 64,
        "prior_manifest_file_sha256": "5" * 64,
        "prior_artifacts": signed_artifacts,
        "prior_artifacts_identity_sha256": signed_artifacts_identity,
        "prior_artifact_count": 1,
        "initial_boundary_evidence_identity_sha256": "7" * 64,
        "old_at_rest_evidence_identity_sha256": "8" * 64,
        "artifact_anchor_identity_sha256": anchor,
    }
    core = {
        "schema_version": TRANSITION_SCHEMA,
        "approved": True,
        "approved_at_utc": (NOW - timedelta(seconds=30)).isoformat(),
        "authorization_reference": STAGE5_EXECUTION_AUTHORIZATION_REFERENCE,
        "reason": TRANSITION_REASON,
        "collector_signed_facts": signed_facts,
        "collector_signature": _signature(signed_facts),
        "collector": collector,
        "old_endpoint_core": old,
        "new_endpoint_core": new,
        "source_machine_guid_sha256": SOURCE_MACHINE,
        "remote_host_attestation": attestation,
        "old_storage_identity": endpoint_identity(old),
        "new_storage_identity": endpoint_identity(new),
        "prior_pointer_sha256": "3" * 64,
        "prior_manifest_identity_sha256": "4" * 64,
        "prior_manifest_file_sha256": "5" * 64,
        "prior_artifacts_identity_sha256": signed_artifacts_identity,
        "prior_artifact_count": 1,
        "initial_boundary_evidence_identity_sha256": "7" * 64,
        "old_at_rest_evidence_identity_sha256": "8" * 64,
        "new_at_rest_evidence_identity_sha256": "9" * 64,
        "artifact_anchor_identity_sha256": anchor,
    }
    evidence = {**core, "transition_identity_sha256": sha256_json(core)}
    observed = {
        **new,
        "derived_storage_identity": endpoint_identity(new),
        "failure_domain": "remote_host_storage",
        "independent_from_source_host": True,
    }
    return evidence, observed, new


def _verify(evidence: dict[str, object], observed: dict[str, object]) -> dict[str, object]:
    return verify_storage_identity_transition(
        evidence,
        observed_new_storage=observed,
        observed_source_machine_guid_sha256=SOURCE_MACHINE,
        prior_storage_identity=evidence["old_storage_identity"],
        prior_pointer_sha256="3" * 64,
        prior_manifest_identity_sha256="4" * 64,
        prior_manifest_file_sha256="5" * 64,
        prior_artifacts_identity_sha256=evidence["prior_artifacts_identity_sha256"],
        prior_artifact_count=evidence["prior_artifact_count"],
        initial_boundary_evidence_identity_sha256="7" * 64,
        old_at_rest_evidence_identity_sha256="8" * 64,
        new_at_rest_evidence_identity_sha256="9" * 64,
        now=NOW,
        public_certificate_path=TEST_CERT_PATH,
        expected_certificate_sha256=TEST_CERT_SHA256,
    )


def _reseal(evidence: dict[str, object]) -> None:
    core = dict(evidence)
    core.pop("transition_identity_sha256", None)
    evidence["transition_identity_sha256"] = sha256_json(core)


def _reseal_collector_and_attestation(evidence: dict[str, object]) -> None:
    collector = evidence["collector"]  # type: ignore[assignment]
    collector_core = dict(collector)  # type: ignore[arg-type]
    collector_core.pop("collector_identity_sha256")
    collector["collector_identity_sha256"] = sha256_json(collector_core)  # type: ignore[index]
    signed_facts = evidence["collector_signed_facts"]  # type: ignore[assignment]
    signed_facts["collector"] = collector_core  # type: ignore[index]
    evidence["collector_signature"] = _signature(signed_facts)  # type: ignore[arg-type]
    attestation = evidence["remote_host_attestation"]  # type: ignore[assignment]
    attestation["collector_identity_sha256"] = collector["collector_identity_sha256"]  # type: ignore[index]
    attestation_core = dict(attestation)  # type: ignore[arg-type]
    attestation_core.pop("attestation_identity_sha256")
    attestation["attestation_identity_sha256"] = sha256_json(attestation_core)  # type: ignore[index]
    _reseal(evidence)


def test_explicit_transition_binds_host_volume_artifacts_and_evidence() -> None:
    evidence, observed, _ = _evidence()
    result = _verify(evidence, observed)
    assert result["single_explicit_transition"] is True
    assert result["old_storage_identity"] != result["new_storage_identity"]
    assert result["remote_machine_guid_sha256"] == REMOTE_MACHINE


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("prior_pointer_sha256", "a" * 64, "prior artifacts"),
        ("prior_artifacts_identity_sha256", "a" * 64, "prior artifacts"),
        ("initial_boundary_evidence_identity_sha256", "a" * 64, "initial_boundary"),
        ("old_at_rest_evidence_identity_sha256", "a" * 64, "old_at_rest"),
        ("new_at_rest_evidence_identity_sha256", "a" * 64, "new_at_rest"),
    ],
)
def test_observed_evidence_mismatch_fails_closed(
    field: str,
    replacement: str,
    message: str,
) -> None:
    evidence, observed, _ = _evidence()
    kwargs = {
        "observed_new_storage": observed,
        "observed_source_machine_guid_sha256": SOURCE_MACHINE,
        "prior_storage_identity": evidence["old_storage_identity"],
        "prior_pointer_sha256": "3" * 64,
        "prior_manifest_identity_sha256": "4" * 64,
        "prior_manifest_file_sha256": "5" * 64,
        "prior_artifacts_identity_sha256": evidence["prior_artifacts_identity_sha256"],
        "prior_artifact_count": evidence["prior_artifact_count"],
        "initial_boundary_evidence_identity_sha256": "7" * 64,
        "old_at_rest_evidence_identity_sha256": "8" * 64,
        "new_at_rest_evidence_identity_sha256": "9" * 64,
        "now": NOW,
        "public_certificate_path": TEST_CERT_PATH,
        "expected_certificate_sha256": TEST_CERT_SHA256,
    }
    kwargs[field] = replacement
    with pytest.raises(StorageIdentityTransitionError, match=message):
        verify_storage_identity_transition(evidence, **kwargs)


def test_remote_machine_must_differ_from_source() -> None:
    evidence, observed, _ = _evidence()
    evidence["collector"]["machine_guid_sha256"] = SOURCE_MACHINE  # type: ignore[index]
    evidence["remote_host_attestation"]["machine_guid_sha256"] = SOURCE_MACHINE  # type: ignore[index]
    _reseal_collector_and_attestation(evidence)
    with pytest.raises(StorageIdentityTransitionError, match="equals the source"):
        _verify(evidence, observed)


def test_changed_volume_cannot_be_called_an_alias() -> None:
    evidence, observed, _ = _evidence()
    evidence["new_endpoint_core"]["volume_serial"] = "ffffffff"  # type: ignore[index]
    _reseal(evidence)
    with pytest.raises(StorageIdentityTransitionError, match="signed payload|live storage probe|volume_serial"):
        _verify(evidence, observed)


def test_caller_cannot_fake_transition_identity() -> None:
    evidence, observed, _ = _evidence()
    evidence["prior_artifact_count"] = 18
    with pytest.raises(StorageIdentityTransitionError, match="transition identity"):
        _verify(evidence, observed)


def test_future_approval_fails_closed() -> None:
    evidence, observed, _ = _evidence()
    evidence["approved_at_utc"] = (NOW + timedelta(seconds=1)).isoformat()
    _reseal(evidence)
    with pytest.raises(StorageIdentityTransitionError, match="future"):
        _verify(evidence, observed)


def test_stale_collector_fails_closed() -> None:
    evidence, observed, _ = _evidence()
    stale = NOW - timedelta(seconds=COLLECTOR_MAX_AGE_SECONDS + 1)
    evidence["collector"]["checked_at_utc"] = stale.isoformat()  # type: ignore[index]
    evidence["remote_host_attestation"]["checked_at_utc"] = stale.isoformat()  # type: ignore[index]
    _reseal_collector_and_attestation(evidence)
    with pytest.raises(StorageIdentityTransitionError, match="stale"):
        _verify(evidence, observed)


def test_previously_embedded_transition_does_not_reapprove_stale_collector() -> None:
    evidence, observed, _ = _evidence()
    result = verify_storage_identity_transition(
        evidence,
        observed_new_storage=observed,
        observed_source_machine_guid_sha256=SOURCE_MACHINE,
        prior_storage_identity=evidence["old_storage_identity"],
        prior_pointer_sha256="3" * 64,
        prior_manifest_identity_sha256="4" * 64,
        prior_manifest_file_sha256="5" * 64,
        prior_artifacts_identity_sha256=evidence["prior_artifacts_identity_sha256"],
        prior_artifact_count=evidence["prior_artifact_count"],
        initial_boundary_evidence_identity_sha256="7" * 64,
        old_at_rest_evidence_identity_sha256="8" * 64,
        new_at_rest_evidence_identity_sha256="9" * 64,
        now=NOW + timedelta(hours=2),
        enforce_collector_freshness=False,
        public_certificate_path=TEST_CERT_PATH,
        expected_certificate_sha256=TEST_CERT_SHA256,
    )
    assert result["transition_identity_sha256"] == evidence["transition_identity_sha256"]


def test_fake_bitlocker_and_machine_guid_fail_closed() -> None:
    evidence, observed, _ = _evidence()
    evidence["collector"]["bitlocker"]["verified"] = False  # type: ignore[index]
    _reseal_collector_and_attestation(evidence)
    with pytest.raises(StorageIdentityTransitionError, match="BitLocker"):
        _verify(evidence, observed)

    evidence, observed, _ = _evidence()
    evidence["remote_host_attestation"]["machine_guid_sha256"] = "a" * 64  # type: ignore[index]
    attestation = evidence["remote_host_attestation"]  # type: ignore[assignment]
    attestation_core = dict(attestation)  # type: ignore[arg-type]
    attestation_core.pop("attestation_identity_sha256")
    attestation["attestation_identity_sha256"] = sha256_json(attestation_core)  # type: ignore[index]
    _reseal(evidence)
    with pytest.raises(StorageIdentityTransitionError, match="MachineGuid"):
        _verify(evidence, observed)


def test_forged_machine_and_bitlocker_with_resealed_self_hash_still_fails_signature() -> None:
    evidence, observed, _ = _evidence()
    collector = evidence["collector"]  # type: ignore[assignment]
    collector["machine_guid_sha256"] = "a" * 64  # type: ignore[index]
    collector["bitlocker"]["verified"] = False  # type: ignore[index]
    collector_core = dict(collector)  # type: ignore[arg-type]
    collector_core.pop("collector_identity_sha256")
    collector["collector_identity_sha256"] = sha256_json(collector_core)  # type: ignore[index]
    evidence["collector_signed_facts"]["collector"] = collector_core  # type: ignore[index]
    attestation = evidence["remote_host_attestation"]  # type: ignore[assignment]
    attestation["machine_guid_sha256"] = "a" * 64  # type: ignore[index]
    attestation["collector_identity_sha256"] = collector["collector_identity_sha256"]  # type: ignore[index]
    attestation_core = dict(attestation)  # type: ignore[arg-type]
    attestation_core.pop("attestation_identity_sha256")
    attestation["attestation_identity_sha256"] = sha256_json(attestation_core)  # type: ignore[index]
    _reseal(evidence)
    with pytest.raises(StorageIdentityTransitionError, match="signed payload|signature"):
        _verify(evidence, observed)


def test_collector_is_host_bound_and_does_not_accept_identity_claims() -> None:
    text = collector_script_path().read_text(encoding="utf-8")
    assert "WIN-G7VO0DD37CE" in text
    assert "Get-SmbShare -Name $ApprovedShareName" in text
    assert "Get-BitLockerVolume -MountPoint $drive" in text
    assert "Get-ItemPropertyValue" in text
    assert "HonghuPgRecovery does not map to the approved backup_package root" in text
    param_block = text.split(")", 1)[0]
    assert "MachineGuid" not in param_block
    assert "VolumeSerial" not in param_block
    assert "Encryption" not in param_block


def test_wrong_share_path_and_collector_file_identity_fail_closed() -> None:
    evidence, observed, _ = _evidence()
    evidence["collector"]["share_local_path"] = r"D:\some-other-folder"  # type: ignore[index]
    _reseal_collector_and_attestation(evidence)
    with pytest.raises(StorageIdentityTransitionError, match="share path"):
        _verify(evidence, observed)

    evidence, observed, _ = _evidence()
    evidence["collector"]["collector_script_sha256"] = "f" * 64  # type: ignore[index]
    _reseal_collector_and_attestation(evidence)
    with pytest.raises(StorageIdentityTransitionError, match="script identity"):
        _verify(evidence, observed)


def test_authorization_reference_is_fail_closed() -> None:
    evidence, observed, _ = _evidence()
    evidence["authorization_reference"] = "some-other-approval"
    _reseal(evidence)
    with pytest.raises(StorageIdentityTransitionError, match="Stage 5 authorization"):
        _verify(evidence, observed)


def test_collector_facts_builder_seals_at_rest_and_transition() -> None:
    _, observed, new = _evidence()
    old = _endpoint("old-endpoint", "10.0.0.8")
    artifacts = [
        {"name": "000000010000000000000001", "size": 4, "sha256": "a" * 64}
    ]
    manifest_core = {
        "schema_version": "honghu.stage5_offvm_wal_manifest.v1",
        "storage_identity": endpoint_identity(old),
        "artifacts": artifacts,
    }
    manifest = {
        **manifest_core,
        "manifest_identity_sha256": sha256_json(manifest_core),
    }
    source_core = {
        "schema_version": SOURCE_HOST_IDENTITY_SCHEMA,
        "verified": True,
        "verification_method": "windows_registry_machineguid_sha256",
        "host_name": "desktop-vgd07j4",
        "machine_guid_sha256": SOURCE_MACHINE,
        "checked_at_utc": (NOW - timedelta(minutes=2)).isoformat(),
    }
    source = {**source_core, "evidence_identity_sha256": sha256_json(source_core)}
    collector_core = dict(_evidence()[0]["collector"])  # type: ignore[arg-type]
    collector_core.pop("collector_identity_sha256")
    facts = {
        "schema_version": COLLECTOR_FACTS_SCHEMA,
        "authorization_reference": STAGE5_EXECUTION_AUTHORIZATION_REFERENCE,
        "approved_at_utc": (NOW - timedelta(seconds=30)).isoformat(),
        "collector": collector_core,
        "source_host_identity_evidence": source,
        "source_machine_guid_sha256": SOURCE_MACHINE,
        "old_endpoint_core": old,
        "new_endpoint_core": new,
        "old_storage_identity": endpoint_identity(old),
        "new_storage_identity": endpoint_identity(new),
        "prior_pointer_sha256": "3" * 64,
        "prior_manifest_identity_sha256": manifest["manifest_identity_sha256"],
        "prior_manifest_file_sha256": "5" * 64,
        "prior_manifest": manifest,
        "prior_artifacts": artifacts,
        # The host collector leaves derived identities for the exact-release
        # sealer to compute; this mirrors the real PowerShell payload.
        "prior_artifacts_identity_sha256": None,
        "prior_artifact_count": 1,
        "initial_boundary_evidence_identity_sha256": "7" * 64,
        "old_at_rest_evidence_identity_sha256": "8" * 64,
        "artifact_anchor_identity_sha256": None,
    }
    facts["collector_signature"] = _signature(collector_signed_facts(facts))
    at_rest, transition = build_transition_from_collector_facts(
        facts,
        public_certificate_path=TEST_CERT_PATH,
        expected_certificate_sha256=TEST_CERT_SHA256,
    )
    assert at_rest["storage_identity"] == observed["derived_storage_identity"]
    assert transition["collector"]["collector_script_sha256"] == collector_script_sha256()
    result = verify_storage_identity_transition(
        transition,
        observed_new_storage=observed,
        observed_source_machine_guid_sha256=SOURCE_MACHINE,
        prior_storage_identity=endpoint_identity(old),
        prior_pointer_sha256="3" * 64,
        prior_manifest_identity_sha256=manifest["manifest_identity_sha256"],
        prior_manifest_file_sha256="5" * 64,
        prior_artifacts_identity_sha256=sha256_json(artifacts),
        prior_artifact_count=1,
        initial_boundary_evidence_identity_sha256="7" * 64,
        old_at_rest_evidence_identity_sha256="8" * 64,
        new_at_rest_evidence_identity_sha256=sha256_json(at_rest),
        now=NOW,
        public_certificate_path=TEST_CERT_PATH,
        expected_certificate_sha256=TEST_CERT_SHA256,
    )
    assert result["new_storage_identity"] == observed["derived_storage_identity"]
