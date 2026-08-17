from __future__ import annotations

"""One-time, auditable rebind of an off-VM storage endpoint identity.

The normal storage identity deliberately includes the UNC server/address.  An
address change therefore produces a different identity even when the share is
served by the same remote machine and volume.  This module does not introduce
an alias allowlist.  It validates one explicit old->new transition against the
old immutable WAL chain, a remote-host attestation, the current source host,
and newly bound at-rest evidence.
"""

import argparse
import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from tools.migration.stage4_recovery_set import sha256_json
from tools.operations.recovery_metrics import RecoveryMetricError, parse_utc

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID


TRANSITION_SCHEMA = "honghu.stage5_storage_identity_transition.v1"
REMOTE_ATTESTATION_SCHEMA = "honghu.stage5_remote_storage_host_attestation.v1"
COLLECTOR_SCHEMA = "honghu.stage5_storage_transition_collector.v1"
COLLECTOR_FACTS_SCHEMA = "honghu.stage5_storage_transition_collector_facts.v1"
SOURCE_HOST_IDENTITY_SCHEMA = "honghu.stage5_source_host_identity.v1"
COLLECTOR_HOST = "win-g7vo0dd37ce"
APPROVED_SHARE_NAME = "honghupgrecovery"
APPROVED_BACKUP_ROOT = r"D:\quant\industry_demo_backup_package\postgresql_recovery"
COLLECTOR_MAX_AGE_SECONDS = 60 * 60
STAGE5_EXECUTION_AUTHORIZATION_REFERENCE = (
    "user-stage5-full-execution-authorization-2026-08-16"
)
COLLECTOR_SIGNATURE_SCHEMA = "honghu.stage5_storage_transition_signature.v1"
COLLECTOR_SIGNED_FACTS_SCHEMA = "honghu.stage5_storage_transition_signed_facts.v1"
TRUSTED_PUBLIC_CERTIFICATE = (
    Path(__file__).resolve().parents[2]
    / "config"
    / "migration"
    / "stage5_storage_attestation_public.cer"
)
PINNED_PUBLIC_CERTIFICATE_SHA256 = (
    "f4dac3e071441e68e860bb05aabec95b39594ca1186171eeb4147a1b265c1dc7"
)
TRANSITION_REASON = "endpoint_address_change_same_physical_storage"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ENDPOINT_FIELDS = (
    "kind",
    "server",
    "share",
    "resolved_addresses",
    "volume_serial",
    "filesystem",
)


class StorageIdentityTransitionError(RuntimeError):
    pass


def collector_script_path() -> Path:
    return Path(__file__).with_name("Collect-StorageIdentityTransitionEvidence.ps1")


def collector_script_sha256() -> str:
    path = collector_script_path()
    if not path.is_file():
        raise StorageIdentityTransitionError("tracked storage-transition collector is absent")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def collector_signed_facts(facts: Mapping[str, Any]) -> dict[str, Any]:
    collector = facts.get("collector")
    artifacts = facts.get("prior_artifacts")
    if not isinstance(collector, Mapping) or not isinstance(artifacts, list):
        raise StorageIdentityTransitionError("collector signed facts are incomplete")
    return {
        "schema_version": COLLECTOR_SIGNED_FACTS_SCHEMA,
        "authorization_reference": facts.get("authorization_reference"),
        "collector": dict(collector),
        "source_host_identity_evidence": facts.get("source_host_identity_evidence"),
        "source_machine_guid_sha256": facts.get("source_machine_guid_sha256"),
        "old_endpoint_core": facts.get("old_endpoint_core"),
        "new_endpoint_core": facts.get("new_endpoint_core"),
        "old_storage_identity": facts.get("old_storage_identity"),
        "new_storage_identity": facts.get("new_storage_identity"),
        "prior_pointer_sha256": facts.get("prior_pointer_sha256"),
        "prior_manifest_identity_sha256": facts.get("prior_manifest_identity_sha256"),
        "prior_manifest_file_sha256": facts.get("prior_manifest_file_sha256"),
        "prior_artifacts": artifacts,
        "prior_artifacts_identity_sha256": facts.get(
            "prior_artifacts_identity_sha256"
        ),
        "prior_artifact_count": facts.get("prior_artifact_count"),
        "initial_boundary_evidence_identity_sha256": facts.get(
            "initial_boundary_evidence_identity_sha256"
        ),
        "old_at_rest_evidence_identity_sha256": facts.get(
            "old_at_rest_evidence_identity_sha256"
        ),
        "artifact_anchor_identity_sha256": facts.get(
            "artifact_anchor_identity_sha256"
        ),
    }


def verify_collector_signature(
    signed_facts: Mapping[str, Any],
    signature_evidence: Mapping[str, Any],
    *,
    public_certificate_path: Path = TRUSTED_PUBLIC_CERTIFICATE,
    expected_certificate_sha256: str = PINNED_PUBLIC_CERTIFICATE_SHA256,
    now: datetime | None = None,
) -> dict[str, Any]:
    if signed_facts.get("schema_version") != COLLECTOR_SIGNED_FACTS_SCHEMA:
        raise StorageIdentityTransitionError("collector signed-facts schema is invalid")
    if signature_evidence.get("schema_version") != COLLECTOR_SIGNATURE_SCHEMA:
        raise StorageIdentityTransitionError("collector signature schema is invalid")
    if signature_evidence.get("algorithm") != "rsa-pss-sha256":
        raise StorageIdentityTransitionError("collector signature algorithm is invalid")
    if not public_certificate_path.is_file():
        raise StorageIdentityTransitionError("tracked collector public certificate is absent")
    certificate_bytes = public_certificate_path.read_bytes()
    certificate_sha256 = hashlib.sha256(certificate_bytes).hexdigest()
    if certificate_sha256 != _require_sha(
        expected_certificate_sha256, field="expected collector certificate SHA-256"
    ):
        raise StorageIdentityTransitionError("collector public certificate differs from the pinned trust root")
    if signature_evidence.get("certificate_sha256") != certificate_sha256:
        raise StorageIdentityTransitionError("collector signature uses another certificate")
    try:
        certificate = x509.load_der_x509_certificate(certificate_bytes)
    except ValueError as exc:
        raise StorageIdentityTransitionError("collector public certificate is not DER X.509") from exc
    common_names = certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
    if len(common_names) != 1 or common_names[0].value != "HonghuStage5StorageAttestation":
        raise StorageIdentityTransitionError("collector certificate subject is not approved")
    public_key = certificate.public_key()
    if not isinstance(public_key, rsa.RSAPublicKey) or public_key.key_size < 3072:
        raise StorageIdentityTransitionError("collector certificate is not RSA-3072 or stronger")
    certificate_thumbprint = certificate.fingerprint(hashes.SHA1()).hex()
    if str(signature_evidence.get("certificate_thumbprint") or "").casefold() != certificate_thumbprint:
        raise StorageIdentityTransitionError("collector certificate thumbprint differs")
    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None or observed_now.utcoffset() is None:
        raise StorageIdentityTransitionError("signature verification clock lacks timezone")
    if hasattr(certificate, "not_valid_before_utc"):
        not_before = certificate.not_valid_before_utc
        not_after = certificate.not_valid_after_utc
    else:  # pragma: no cover - compatibility for older cryptography releases
        not_before = certificate.not_valid_before.replace(tzinfo=timezone.utc)
        not_after = certificate.not_valid_after.replace(tzinfo=timezone.utc)
    if not (not_before <= observed_now.astimezone(timezone.utc) <= not_after):
        raise StorageIdentityTransitionError("collector certificate is outside its validity period")
    try:
        payload = base64.b64decode(
            str(signature_evidence.get("signed_payload_base64") or ""), validate=True
        )
    except (ValueError, TypeError) as exc:
        raise StorageIdentityTransitionError("collector signed payload is not valid base64") from exc
    if payload != _canonical_bytes(signed_facts):
        raise StorageIdentityTransitionError("collector signed payload is not canonical or differs from evidence")
    payload_sha = hashlib.sha256(payload).hexdigest()
    if signature_evidence.get("signed_payload_sha256") != payload_sha:
        raise StorageIdentityTransitionError("collector signature payload identity differs")
    try:
        signature = base64.b64decode(
            str(signature_evidence.get("signature_base64") or ""), validate=True
        )
    except (ValueError, TypeError) as exc:
        raise StorageIdentityTransitionError("collector signature is not valid base64") from exc
    try:
        public_key.verify(
            signature,
            payload,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=hashes.SHA256().digest_size,
            ),
            hashes.SHA256(),
        )
    except InvalidSignature as exc:
        raise StorageIdentityTransitionError("collector cryptographic signature is invalid") from exc
    return {
        "schema_version": COLLECTOR_SIGNATURE_SCHEMA,
        "algorithm": "rsa-pss-sha256",
        "certificate_sha256": certificate_sha256,
        "certificate_thumbprint": certificate_thumbprint,
        "signed_payload_sha256": payload_sha,
        "verified": True,
    }


def endpoint_core(storage: Mapping[str, Any]) -> dict[str, Any]:
    core = {field: storage.get(field) for field in _ENDPOINT_FIELDS}
    if core["kind"] != "windows_unc":
        raise StorageIdentityTransitionError("storage transition requires a Windows UNC endpoint")
    if not all(isinstance(core[field], str) and core[field] for field in ("server", "share", "volume_serial", "filesystem")):
        raise StorageIdentityTransitionError("storage endpoint core is incomplete")
    addresses = core["resolved_addresses"]
    if not isinstance(addresses, list) or not addresses or not all(
        isinstance(value, str) and value for value in addresses
    ):
        raise StorageIdentityTransitionError("storage endpoint has no resolved address identity")
    core["resolved_addresses"] = sorted(set(addresses))
    return core


def endpoint_identity(core: Mapping[str, Any]) -> str:
    return sha256_json(endpoint_core(core))


def _require_sha(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise StorageIdentityTransitionError(f"{field} is not a SHA-256 identity")
    return value


def _parse_time(value: Any, *, field: str) -> datetime:
    try:
        return parse_utc(value, field=field)
    except RecoveryMetricError as exc:
        raise StorageIdentityTransitionError(f"{field} is not a valid timestamp") from exc


def local_machine_guid_sha256() -> str:
    """Return a non-reversible identity for the current Windows host."""

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        ) as key:
            value = str(winreg.QueryValueEx(key, "MachineGuid")[0]).strip().casefold()
    except (ImportError, OSError) as exc:
        raise StorageIdentityTransitionError(
            "cannot derive the source host MachineGuid identity"
        ) from exc
    if not value:
        raise StorageIdentityTransitionError("source host MachineGuid is empty")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def artifact_anchor_identity(
    *,
    pointer_sha256: str,
    manifest_identity_sha256: str,
    manifest_file_sha256: str,
    artifacts_identity_sha256: str,
    artifact_count: int,
) -> str:
    return sha256_json(
        {
            "pointer_sha256": _require_sha(pointer_sha256, field="pointer_sha256"),
            "manifest_identity_sha256": _require_sha(
                manifest_identity_sha256, field="manifest_identity_sha256"
            ),
            "manifest_file_sha256": _require_sha(
                manifest_file_sha256, field="manifest_file_sha256"
            ),
            "artifacts_identity_sha256": _require_sha(
                artifacts_identity_sha256, field="artifacts_identity_sha256"
            ),
            "artifact_count": artifact_count,
        }
    )


def verify_storage_identity_transition(
    evidence: Mapping[str, Any],
    *,
    observed_new_storage: Mapping[str, Any],
    observed_source_machine_guid_sha256: str,
    prior_storage_identity: str,
    prior_pointer_sha256: str,
    prior_manifest_identity_sha256: str,
    prior_manifest_file_sha256: str,
    prior_artifacts_identity_sha256: str,
    prior_artifact_count: int,
    initial_boundary_evidence_identity_sha256: str,
    old_at_rest_evidence_identity_sha256: str,
    new_at_rest_evidence_identity_sha256: str,
    now: datetime | None = None,
    enforce_collector_freshness: bool = True,
    public_certificate_path: Path = TRUSTED_PUBLIC_CERTIFICATE,
    expected_certificate_sha256: str = PINNED_PUBLIC_CERTIFICATE_SHA256,
) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise StorageIdentityTransitionError("storage transition evidence must be an object")
    core = dict(evidence)
    declared_identity = core.pop("transition_identity_sha256", None)
    if evidence.get("schema_version") != TRANSITION_SCHEMA or evidence.get("approved") is not True:
        raise StorageIdentityTransitionError("storage transition evidence is not explicitly approved")
    if evidence.get("reason") != TRANSITION_REASON:
        raise StorageIdentityTransitionError("storage transition reason is not supported")
    if _require_sha(declared_identity, field="transition_identity_sha256") != sha256_json(core):
        raise StorageIdentityTransitionError("storage transition identity is invalid")

    signed_facts = evidence.get("collector_signed_facts")
    signature_evidence = evidence.get("collector_signature")
    if not isinstance(signed_facts, Mapping) or not isinstance(signature_evidence, Mapping):
        raise StorageIdentityTransitionError("cryptographic collector attestation is absent")
    verified_signature = verify_collector_signature(
        signed_facts,
        signature_evidence,
        public_certificate_path=public_certificate_path,
        expected_certificate_sha256=expected_certificate_sha256,
        now=now,
    )

    collector = evidence.get("collector")
    if not isinstance(collector, Mapping):
        raise StorageIdentityTransitionError("storage transition collector evidence is absent")
    collector_core = dict(collector)
    collector_identity = collector_core.pop("collector_identity_sha256", None)
    if collector.get("schema_version") != COLLECTOR_SCHEMA:
        raise StorageIdentityTransitionError("storage transition collector schema is invalid")
    if str(collector.get("host_name") or "").casefold() != COLLECTOR_HOST:
        raise StorageIdentityTransitionError("storage transition collector ran on an unapproved host")
    if collector.get("collector_script_sha256") != collector_script_sha256():
        raise StorageIdentityTransitionError("storage transition collector script identity differs")
    if _require_sha(
        collector_identity, field="collector_identity_sha256"
    ) != sha256_json(collector_core):
        raise StorageIdentityTransitionError("storage transition collector identity is invalid")
    if collector.get("share_local_path_verified") is not True:
        raise StorageIdentityTransitionError("collector did not verify the approved share path")
    if str(collector.get("share_name") or "").casefold() != APPROVED_SHARE_NAME:
        raise StorageIdentityTransitionError("collector used an unapproved SMB share")
    if str(collector.get("share_local_path") or "").rstrip("\\").casefold() != APPROVED_BACKUP_ROOT.casefold():
        raise StorageIdentityTransitionError("collector share path differs from the approved backup_package root")
    if str(collector.get("approved_backup_root") or "").rstrip("\\").casefold() != APPROVED_BACKUP_ROOT.casefold():
        raise StorageIdentityTransitionError("collector approved backup root differs")
    if collector.get("smb_endpoint_tcp_445_verified") is not True:
        raise StorageIdentityTransitionError("collector did not verify the live SMB endpoint")
    if collector.get("artifact_hashes_verified") is not True:
        raise StorageIdentityTransitionError("collector did not verify all prior artifacts")
    bitlocker = collector.get("bitlocker")
    if not isinstance(bitlocker, Mapping) or not (
        bitlocker.get("protection_status") == "On"
        and bitlocker.get("volume_status") == "FullyEncrypted"
        and bitlocker.get("encryption_percentage") == 100.0
        and bitlocker.get("verified") is True
    ):
        raise StorageIdentityTransitionError("collector BitLocker evidence is not fully protected")
    collector_machine = _require_sha(
        collector.get("machine_guid_sha256"), field="collector machine_guid_sha256"
    )
    signed_collector = signed_facts.get("collector")
    if not isinstance(signed_collector, Mapping) or dict(signed_collector) != collector_core:
        raise StorageIdentityTransitionError("collector summary differs from signed facts")

    old_core = endpoint_core(evidence.get("old_endpoint_core") or {})
    new_core = endpoint_core(evidence.get("new_endpoint_core") or {})
    observed_core = endpoint_core(observed_new_storage)
    old_identity = endpoint_identity(old_core)
    new_identity = endpoint_identity(new_core)
    if old_identity == new_identity:
        raise StorageIdentityTransitionError("storage transition does not change endpoint identity")
    if new_core != observed_core:
        raise StorageIdentityTransitionError("new endpoint core does not match the live storage probe")
    if new_identity != observed_new_storage.get("derived_storage_identity"):
        raise StorageIdentityTransitionError("new endpoint identity does not match the live storage probe")
    expected_unc = rf"\\{new_core['server']}\{new_core['share']}".casefold()
    if str(collector.get("unc_live_probe_path") or "").rstrip("\\").casefold() != expected_unc:
        raise StorageIdentityTransitionError("collector UNC probe does not match the new endpoint")
    if old_identity != _require_sha(
        prior_storage_identity, field="prior_storage_identity"
    ):
        raise StorageIdentityTransitionError("old endpoint identity does not match the prior manifest")
    for field in ("share", "volume_serial", "filesystem"):
        if old_core[field] != new_core[field]:
            raise StorageIdentityTransitionError(
                f"storage transition changed the physical {field} boundary"
            )
    if old_core["server"] == new_core["server"] and old_core["resolved_addresses"] == new_core["resolved_addresses"]:
        raise StorageIdentityTransitionError("storage transition did not change its endpoint address")

    source_machine = _require_sha(
        evidence.get("source_machine_guid_sha256"),
        field="source_machine_guid_sha256",
    )
    if source_machine != _require_sha(
        observed_source_machine_guid_sha256,
        field="observed_source_machine_guid_sha256",
    ):
        raise StorageIdentityTransitionError("transition belongs to another source host")

    attestation = evidence.get("remote_host_attestation")
    if not isinstance(attestation, Mapping):
        raise StorageIdentityTransitionError("remote storage host attestation is absent")
    attestation_core = dict(attestation)
    attestation_identity = attestation_core.pop("attestation_identity_sha256", None)
    if attestation.get("schema_version") != REMOTE_ATTESTATION_SCHEMA:
        raise StorageIdentityTransitionError("remote storage host attestation schema is invalid")
    if _require_sha(attestation_identity, field="attestation_identity_sha256") != sha256_json(attestation_core):
        raise StorageIdentityTransitionError("remote storage host attestation identity is invalid")
    remote_machine = _require_sha(
        attestation.get("machine_guid_sha256"), field="remote machine_guid_sha256"
    )
    if remote_machine != collector_machine:
        raise StorageIdentityTransitionError("remote MachineGuid differs from collector evidence")
    if remote_machine == source_machine:
        raise StorageIdentityTransitionError("remote storage MachineGuid equals the source host")
    for field in ("share", "volume_serial", "filesystem"):
        if attestation.get(field) != new_core[field]:
            raise StorageIdentityTransitionError(
                f"remote host attestation does not match the {field} boundary"
            )
    addresses = attestation.get("current_addresses")
    if not isinstance(addresses, list) or not set(new_core["resolved_addresses"]).issubset(
        set(addresses)
    ):
        raise StorageIdentityTransitionError("remote host attestation does not cover the new address")

    actual_anchor = artifact_anchor_identity(
        pointer_sha256=prior_pointer_sha256,
        manifest_identity_sha256=prior_manifest_identity_sha256,
        manifest_file_sha256=prior_manifest_file_sha256,
        artifacts_identity_sha256=prior_artifacts_identity_sha256,
        artifact_count=prior_artifact_count,
    )
    if attestation.get("artifact_anchor_identity_sha256") != actual_anchor:
        raise StorageIdentityTransitionError("remote host attestation is not bound to the prior artifacts")
    if attestation.get("collector_identity_sha256") != collector_identity:
        raise StorageIdentityTransitionError("remote host attestation is not bound to the collector")

    checks = {
        "old_storage_identity": old_identity,
        "new_storage_identity": new_identity,
        "prior_pointer_sha256": prior_pointer_sha256,
        "prior_manifest_identity_sha256": prior_manifest_identity_sha256,
        "prior_manifest_file_sha256": prior_manifest_file_sha256,
        "prior_artifacts_identity_sha256": prior_artifacts_identity_sha256,
        "prior_artifact_count": prior_artifact_count,
        "initial_boundary_evidence_identity_sha256": initial_boundary_evidence_identity_sha256,
        "old_at_rest_evidence_identity_sha256": old_at_rest_evidence_identity_sha256,
        "new_at_rest_evidence_identity_sha256": new_at_rest_evidence_identity_sha256,
        "artifact_anchor_identity_sha256": actual_anchor,
    }
    for field, observed in checks.items():
        if evidence.get(field) != observed:
            raise StorageIdentityTransitionError(f"storage transition {field} does not match")
        if signed_facts.get(field) not in (None, observed):
            raise StorageIdentityTransitionError(
                f"signed collector facts {field} does not match"
            )
    signed_artifacts = signed_facts.get("prior_artifacts")
    if not isinstance(signed_artifacts, list) or sha256_json(signed_artifacts) != prior_artifacts_identity_sha256:
        raise StorageIdentityTransitionError("signed collector artifacts do not match the verified prior chain")
    for field, observed in (
        ("old_endpoint_core", old_core),
        ("new_endpoint_core", new_core),
        ("source_machine_guid_sha256", source_machine),
        ("authorization_reference", STAGE5_EXECUTION_AUTHORIZATION_REFERENCE),
    ):
        if signed_facts.get(field) != observed:
            raise StorageIdentityTransitionError(f"signed collector facts {field} does not match")
    for field in (
        "old_storage_identity",
        "new_storage_identity",
        "prior_pointer_sha256",
        "prior_manifest_identity_sha256",
        "prior_manifest_file_sha256",
        "prior_artifacts_identity_sha256",
        "initial_boundary_evidence_identity_sha256",
        "old_at_rest_evidence_identity_sha256",
        "new_at_rest_evidence_identity_sha256",
        "artifact_anchor_identity_sha256",
    ):
        _require_sha(evidence.get(field), field=field)
    if not isinstance(prior_artifact_count, int) or prior_artifact_count <= 0:
        raise StorageIdentityTransitionError("prior artifact count is invalid")

    if evidence.get("authorization_reference") != STAGE5_EXECUTION_AUTHORIZATION_REFERENCE:
        raise StorageIdentityTransitionError("storage transition lacks the approved Stage 5 authorization")
    approved_at = _parse_time(evidence.get("approved_at_utc"), field="approved_at_utc")
    attested_at = _parse_time(
        attestation.get("checked_at_utc"), field="remote host attestation checked_at_utc"
    )
    collected_at = _parse_time(
        collector.get("checked_at_utc"), field="collector checked_at_utc"
    )
    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None or observed_now.utcoffset() is None:
        raise StorageIdentityTransitionError("transition verification clock lacks a timezone")
    if approved_at > observed_now.astimezone(timezone.utc):
        raise StorageIdentityTransitionError("storage transition approval is dated in the future")
    if attested_at != collected_at:
        raise StorageIdentityTransitionError("attestation timestamp differs from collector evidence")
    if approved_at < collected_at:
        raise StorageIdentityTransitionError("storage transition approval predates collection")
    collector_age = (observed_now.astimezone(timezone.utc) - collected_at).total_seconds()
    if collector_age < 0 or (
        enforce_collector_freshness and collector_age > COLLECTOR_MAX_AGE_SECONDS
    ):
        raise StorageIdentityTransitionError("storage transition collector evidence is stale")

    return {
        "schema_version": TRANSITION_SCHEMA,
        "transition_identity_sha256": declared_identity,
        "approved_at_utc": approved_at.astimezone(timezone.utc).isoformat(),
        "reason": TRANSITION_REASON,
        "old_storage_identity": old_identity,
        "new_storage_identity": new_identity,
        "remote_machine_guid_sha256": remote_machine,
        "source_machine_guid_sha256": source_machine,
        "remote_host_attestation_identity_sha256": attestation_identity,
        "collector_identity_sha256": collector_identity,
        "collector_script_sha256": collector_script_sha256(),
        "authorization_reference": STAGE5_EXECUTION_AUTHORIZATION_REFERENCE,
        "collector_signature": verified_signature,
        "prior_pointer_sha256": prior_pointer_sha256,
        "prior_manifest_identity_sha256": prior_manifest_identity_sha256,
        "prior_manifest_file_sha256": prior_manifest_file_sha256,
        "prior_artifacts_identity_sha256": prior_artifacts_identity_sha256,
        "prior_artifact_count": prior_artifact_count,
        "artifact_anchor_identity_sha256": actual_anchor,
        "initial_boundary_evidence_identity_sha256": initial_boundary_evidence_identity_sha256,
        "old_at_rest_evidence_identity_sha256": old_at_rest_evidence_identity_sha256,
        "new_at_rest_evidence_identity_sha256": new_at_rest_evidence_identity_sha256,
        "single_explicit_transition": True,
    }


def build_transition_from_collector_facts(
    facts: Mapping[str, Any],
    *,
    public_certificate_path: Path = TRUSTED_PUBLIC_CERTIFICATE,
    expected_certificate_sha256: str = PINNED_PUBLIC_CERTIFICATE_SHA256,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Seal facts gathered by the tracked, host-bound PowerShell collector.

    This helper does not probe the host.  The collector performs every local
    Windows/SMB/BitLocker probe and passes its own exact-file identity.  The
    normal verifier later rebinds the result to the live VM source identity,
    the live UNC endpoint, and the immutable prior WAL chain.
    """

    if facts.get("schema_version") != COLLECTOR_FACTS_SCHEMA:
        raise StorageIdentityTransitionError("collector facts schema is invalid")
    collector = facts.get("collector")
    if not isinstance(collector, Mapping):
        raise StorageIdentityTransitionError("collector facts lack collector evidence")
    collector_core = dict(collector)
    if collector_core.get("schema_version") != COLLECTOR_SCHEMA:
        raise StorageIdentityTransitionError("collector facts use an invalid collector schema")
    if str(collector_core.get("host_name") or "").casefold() != COLLECTOR_HOST:
        raise StorageIdentityTransitionError("collector facts belong to an unapproved host")
    if collector_core.get("collector_script_sha256") != collector_script_sha256():
        raise StorageIdentityTransitionError("collector facts use another collector script")
    signed_facts = collector_signed_facts(facts)
    signature_evidence = facts.get("collector_signature")
    if not isinstance(signature_evidence, Mapping):
        raise StorageIdentityTransitionError("collector facts lack cryptographic signature")
    verify_collector_signature(
        signed_facts,
        signature_evidence,
        public_certificate_path=public_certificate_path,
        expected_certificate_sha256=expected_certificate_sha256,
        now=_parse_time(collector_core.get("checked_at_utc"), field="collector checked_at_utc"),
    )
    collector_identity = sha256_json(collector_core)
    collector_evidence = {
        **collector_core,
        "collector_identity_sha256": collector_identity,
    }
    old_core = endpoint_core(facts.get("old_endpoint_core") or {})
    new_core = endpoint_core(facts.get("new_endpoint_core") or {})
    old_identity = endpoint_identity(old_core)
    new_identity = endpoint_identity(new_core)
    if facts.get("old_storage_identity") not in (None, old_identity):
        raise StorageIdentityTransitionError("collector facts do not reproduce prior storage identity")
    if facts.get("new_storage_identity") not in (None, new_identity):
        raise StorageIdentityTransitionError("collector facts do not reproduce new storage identity")
    checked_at = _parse_time(collector_core.get("checked_at_utc"), field="collector checked_at_utc")
    approved_at = _parse_time(facts.get("approved_at_utc"), field="approved_at_utc")
    if approved_at < checked_at:
        raise StorageIdentityTransitionError("collector facts approval predates collection")
    if facts.get("authorization_reference") != STAGE5_EXECUTION_AUTHORIZATION_REFERENCE:
        raise StorageIdentityTransitionError("collector facts lack Stage 5 authorization")
    source_evidence = facts.get("source_host_identity_evidence")
    if not isinstance(source_evidence, Mapping):
        raise StorageIdentityTransitionError("collector facts lack source-host identity evidence")
    source_core = dict(source_evidence)
    source_evidence_identity = source_core.pop("evidence_identity_sha256", None)
    if (
        source_evidence.get("schema_version") != SOURCE_HOST_IDENTITY_SCHEMA
        or source_evidence.get("verified") is not True
        or source_evidence.get("verification_method")
        != "windows_registry_machineguid_sha256"
        or str(source_evidence.get("host_name") or "").casefold()
        != "desktop-vgd07j4"
        or _require_sha(
            source_evidence_identity, field="source-host evidence identity"
        )
        != sha256_json(source_core)
    ):
        raise StorageIdentityTransitionError("source-host identity evidence is invalid")
    source_machine_guid_sha256 = _require_sha(
        source_evidence.get("machine_guid_sha256"),
        field="source-host machine_guid_sha256",
    )
    if facts.get("source_machine_guid_sha256") != source_machine_guid_sha256:
        raise StorageIdentityTransitionError("source-host MachineGuid facts differ")

    at_rest_core = {
        "schema_version": "honghu.storage_at_rest_encryption.v1",
        "status": "verified",
        "verification_method": "windows_bitlocker_volume_probe",
        "storage_identity": new_identity,
        "checked_at_utc": checked_at.astimezone(timezone.utc).isoformat(),
        "volume_encryption_enabled": True,
    }
    new_at_rest_identity = sha256_json(at_rest_core)
    prior_artifacts = facts.get("prior_artifacts")
    if not isinstance(prior_artifacts, list) or not prior_artifacts:
        raise StorageIdentityTransitionError("collector facts lack verified prior artifacts")
    if len(prior_artifacts) != int(facts.get("prior_artifact_count") or 0):
        raise StorageIdentityTransitionError("collector artifact count is inconsistent")
    prior_artifacts_identity = sha256_json(prior_artifacts)
    if facts.get("prior_artifacts_identity_sha256") not in (None, prior_artifacts_identity):
        raise StorageIdentityTransitionError("collector artifact inventory identity is invalid")
    prior_manifest = facts.get("prior_manifest")
    if not isinstance(prior_manifest, Mapping):
        raise StorageIdentityTransitionError("collector facts lack the prior manifest")
    manifest_core = dict(prior_manifest)
    manifest_identity = manifest_core.pop("manifest_identity_sha256", None)
    if (
        _require_sha(manifest_identity, field="prior manifest identity")
        != sha256_json(manifest_core)
        or manifest_identity != facts.get("prior_manifest_identity_sha256")
    ):
        raise StorageIdentityTransitionError("collector prior manifest identity is invalid")
    if prior_manifest.get("storage_identity") != old_identity:
        raise StorageIdentityTransitionError("collector old endpoint does not reproduce prior manifest storage")
    anchor = artifact_anchor_identity(
        pointer_sha256=str(facts.get("prior_pointer_sha256") or ""),
        manifest_identity_sha256=str(facts.get("prior_manifest_identity_sha256") or ""),
        manifest_file_sha256=str(facts.get("prior_manifest_file_sha256") or ""),
        artifacts_identity_sha256=prior_artifacts_identity,
        artifact_count=int(facts.get("prior_artifact_count") or 0),
    )
    if facts.get("artifact_anchor_identity_sha256") not in (None, anchor):
        raise StorageIdentityTransitionError("collector facts artifact anchor is invalid")
    attestation_core = {
        "schema_version": REMOTE_ATTESTATION_SCHEMA,
        "machine_guid_sha256": _require_sha(
            collector_core.get("machine_guid_sha256"), field="collector machine_guid_sha256"
        ),
        "share": new_core["share"],
        "volume_serial": new_core["volume_serial"],
        "filesystem": new_core["filesystem"],
        "current_addresses": list(new_core["resolved_addresses"]),
        "checked_at_utc": checked_at.astimezone(timezone.utc).isoformat(),
        "artifact_anchor_identity_sha256": anchor,
        "collector_identity_sha256": collector_identity,
    }
    attestation = {
        **attestation_core,
        "attestation_identity_sha256": sha256_json(attestation_core),
    }
    transition_core = {
        "schema_version": TRANSITION_SCHEMA,
        "approved": True,
        "approved_at_utc": approved_at.astimezone(timezone.utc).isoformat(),
        "authorization_reference": STAGE5_EXECUTION_AUTHORIZATION_REFERENCE,
        "reason": TRANSITION_REASON,
        "collector_signed_facts": signed_facts,
        "collector_signature": dict(signature_evidence),
        "collector": collector_evidence,
        "old_endpoint_core": old_core,
        "new_endpoint_core": new_core,
        "source_machine_guid_sha256": source_machine_guid_sha256,
        "source_host_identity_evidence_identity_sha256": source_evidence_identity,
        "remote_host_attestation": attestation,
        "old_storage_identity": old_identity,
        "new_storage_identity": new_identity,
        "prior_pointer_sha256": _require_sha(
            facts.get("prior_pointer_sha256"), field="prior_pointer_sha256"
        ),
        "prior_manifest_identity_sha256": _require_sha(
            facts.get("prior_manifest_identity_sha256"),
            field="prior_manifest_identity_sha256",
        ),
        "prior_manifest_file_sha256": _require_sha(
            facts.get("prior_manifest_file_sha256"), field="prior_manifest_file_sha256"
        ),
        "prior_artifacts_identity_sha256": _require_sha(
            prior_artifacts_identity,
            field="prior_artifacts_identity_sha256",
        ),
        "prior_artifact_count": int(facts.get("prior_artifact_count") or 0),
        "initial_boundary_evidence_identity_sha256": _require_sha(
            facts.get("initial_boundary_evidence_identity_sha256"),
            field="initial_boundary_evidence_identity_sha256",
        ),
        "old_at_rest_evidence_identity_sha256": _require_sha(
            facts.get("old_at_rest_evidence_identity_sha256"),
            field="old_at_rest_evidence_identity_sha256",
        ),
        "new_at_rest_evidence_identity_sha256": new_at_rest_identity,
        "artifact_anchor_identity_sha256": anchor,
    }
    transition = {
        **transition_core,
        "transition_identity_sha256": sha256_json(transition_core),
    }
    return at_rest_core, transition


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StorageIdentityTransitionError(f"cannot read collector facts: {path}") from exc
    if not isinstance(value, dict):
        raise StorageIdentityTransitionError("collector facts must be an object")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seal host-collected storage transition evidence")
    parser.add_argument("--collector-facts", type=Path, required=True)
    parser.add_argument("--canonical-payload-output", type=Path)
    parser.add_argument("--at-rest-output", type=Path)
    parser.add_argument("--transition-output", type=Path)
    args = parser.parse_args(argv)
    facts = _read_json(args.collector_facts)
    if args.canonical_payload_output:
        payload = _canonical_bytes(collector_signed_facts(facts))
        args.canonical_payload_output.parent.mkdir(parents=True, exist_ok=True)
        args.canonical_payload_output.write_bytes(payload)
        print(json.dumps({"signed_payload_sha256": hashlib.sha256(payload).hexdigest()}))
        return 0
    if args.at_rest_output is None or args.transition_output is None:
        parser.error("--at-rest-output and --transition-output are required when sealing")
    at_rest, transition = build_transition_from_collector_facts(facts)
    _write_json(args.at_rest_output, at_rest)
    _write_json(args.transition_output, transition)
    print(
        json.dumps(
            {
                "collector_identity_sha256": transition["collector"][
                    "collector_identity_sha256"
                ],
                "new_at_rest_evidence_identity_sha256": transition[
                    "new_at_rest_evidence_identity_sha256"
                ],
                "transition_identity_sha256": transition[
                    "transition_identity_sha256"
                ],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
