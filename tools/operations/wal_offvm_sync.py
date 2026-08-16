from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

from tools.migration.stage4_recovery_set import (
    RecoverySetError,
    probe_storage_endpoint,
    sha256_file,
    sha256_json,
)
from tools.operations.recovery_metrics import RecoveryMetricError, parse_utc


WAL_NAME = re.compile(r"^[0-9A-F]{24}$")
MANIFEST_SCHEMA = "honghu.stage5_offvm_wal_manifest.v1"
POINTER_SCHEMA = "honghu.stage5_offvm_wal_pointer.v1"
INITIAL_BOUNDARY_SCHEMA = "honghu.stage5_wal_initial_boundary.v1"
MAX_RETAINED_MANIFESTS = 2
INTEGRITY_SCHEMA = "honghu.stage5_wal_integrity_chain.v1"
DEFAULT_MAX_FULL_SCRUB_AGE_SECONDS = 24 * 60 * 60


class WalSyncError(RuntimeError):
    pass


def _utc(value: datetime | None = None) -> datetime:
    observed = value or datetime.now(timezone.utc)
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise WalSyncError("timestamps must include a timezone")
    return observed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _parse_time(value: Any, *, field: str) -> datetime:
    try:
        parsed = parse_utc(value, field=field)
    except RecoveryMetricError as exc:
        raise WalSyncError(f"{field} is not a valid ISO-8601 timestamp") from exc
    return parsed


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def _exclusive_lock(root: Path) -> Iterator[None]:
    lock_path = root / ".wal_offvm_sync.lock"
    try:
        descriptor = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise WalSyncError("another WAL off-VM sync owns the destination lock") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        os.close(descriptor)
        descriptor = -1
        yield
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        lock_path.unlink(missing_ok=True)


def _wal_position(name: str, *, segment_size_bytes: int) -> tuple[int, int]:
    if not WAL_NAME.fullmatch(name):
        raise WalSyncError(f"invalid complete WAL segment name: {name}")
    if segment_size_bytes <= 0 or (1 << 32) % segment_size_bytes != 0:
        raise WalSyncError("WAL segment size must divide 2^32")
    timeline = int(name[:8], 16)
    log = int(name[8:16], 16)
    segment = int(name[16:24], 16)
    segments_per_log = (1 << 32) // segment_size_bytes
    if segment >= segments_per_log:
        raise WalSyncError(f"WAL segment number is invalid for configured size: {name}")
    return timeline, log * segments_per_log + segment


def _require_contiguous(names: Sequence[str], *, segment_size_bytes: int) -> None:
    if not names:
        raise WalSyncError("no complete archived WAL segments were found")
    positions = [_wal_position(name, segment_size_bytes=segment_size_bytes) for name in names]
    for previous, current in zip(positions, positions[1:]):
        if current[0] != previous[0]:
            raise WalSyncError("WAL timeline changed without a separately verified timeline history")
        if current[1] != previous[1] + 1:
            raise WalSyncError("archived WAL sequence contains a gap")


def _source_segments(source_archive: Path) -> dict[str, Path]:
    if not source_archive.is_dir():
        raise WalSyncError("source WAL archive is not a directory")
    result: dict[str, Path] = {}
    for path in source_archive.iterdir():
        if not path.is_file():
            continue
        if WAL_NAME.fullmatch(path.name):
            if path.is_symlink():
                raise WalSyncError(f"source WAL segment is a symlink: {path.name}")
            result[path.name] = path
        elif re.fullmatch(r"[0-9a-fA-F]{24}", path.name):
            raise WalSyncError(f"WAL segment name is not canonical uppercase: {path.name}")
    return result


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WalSyncError(f"cannot read trusted JSON evidence: {path.name}") from exc
    if not isinstance(value, dict):
        raise WalSyncError(f"JSON evidence is not an object: {path.name}")
    return value


def _storage_evidence(destination: Path, expected_identity: str | None) -> dict[str, Any]:
    try:
        storage = probe_storage_endpoint(destination)
    except RecoverySetError as exc:
        raise WalSyncError(str(exc)) from exc
    if not storage.get("independent_from_source_host"):
        raise WalSyncError("a local path or same-host share cannot satisfy off-VM WAL recovery")
    observed = str(storage.get("derived_storage_identity") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", observed):
        raise WalSyncError("off-VM storage probe did not produce a stable identity")
    if expected_identity is not None and observed != expected_identity:
        raise WalSyncError("off-VM storage identity does not match the approved endpoint")
    return storage


def _encryption_state(
    storage: Mapping[str, Any],
    evidence: Mapping[str, Any] | None,
    *,
    observed_at: datetime,
) -> dict[str, Any]:
    if evidence is None:
        return {
            "status": "unknown",
            "verified": False,
            "evidence_identity_sha256": None,
            "note": "transport security does not prove backup encryption at rest",
        }
    allowed = {
        "schema_version",
        "status",
        "verification_method",
        "storage_identity",
        "checked_at_utc",
        "volume_encryption_enabled",
    }
    core = {key: evidence.get(key) for key in sorted(allowed)}
    if (
        core.get("schema_version") != "honghu.storage_at_rest_encryption.v1"
        or core.get("status") != "verified"
        or core.get("verification_method") not in {"windows_bitlocker_volume_probe", "approved_storage_api_probe"}
        or core.get("storage_identity") != storage.get("derived_storage_identity")
        or core.get("volume_encryption_enabled") is not True
    ):
        raise WalSyncError("at-rest encryption evidence is not bound to the probed storage")
    checked_at = _parse_time(core.get("checked_at_utc"), field="at-rest checked_at_utc")
    if checked_at > observed_at:
        raise WalSyncError("at-rest encryption evidence is dated in the future")
    return {
        "status": "verified",
        "verified": True,
        "evidence_identity_sha256": sha256_json(core),
        "verification_method": core["verification_method"],
        "checked_at_utc": _iso(checked_at),
        "storage_identity": core["storage_identity"],
    }


def _initial_boundary_state(
    storage: Mapping[str, Any],
    evidence: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if evidence is None:
        raise WalSyncError(
            "first off-VM WAL sync requires a verified base-recovery first-required WAL boundary"
        )
    allowed = {
        "schema_version",
        "verified",
        "base_recovery_set_identity_sha256",
        "first_required_wal_segment",
        "storage_identity",
        "verified_at_utc",
    }
    core = {key: evidence.get(key) for key in sorted(allowed)}
    if core.get("schema_version") != INITIAL_BOUNDARY_SCHEMA or core.get("verified") is not True:
        raise WalSyncError("initial WAL boundary evidence is not verified")
    if not re.fullmatch(
        r"[0-9a-f]{64}",
        str(core.get("base_recovery_set_identity_sha256") or ""),
    ):
        raise WalSyncError("initial WAL boundary lacks a base recovery-set identity")
    if not WAL_NAME.fullmatch(str(core.get("first_required_wal_segment") or "")):
        raise WalSyncError("initial WAL boundary has an invalid first-required segment")
    if core.get("storage_identity") != storage.get("derived_storage_identity"):
        raise WalSyncError("initial WAL boundary belongs to another off-VM storage endpoint")
    _parse_time(core.get("verified_at_utc"), field="initial WAL boundary verified_at_utc")
    return {**core, "evidence_identity_sha256": sha256_json(core)}


def _load_latest(destination: Path) -> tuple[dict[str, Any], dict[str, Any]] | None:
    pointer_path = destination / "latest_verified_wal_manifest.json"
    if not pointer_path.exists():
        wal_dir = destination / "wal"
        if wal_dir.exists() and any(WAL_NAME.fullmatch(path.name) for path in wal_dir.iterdir()):
            raise WalSyncError("off-VM WAL files exist without a verified manifest pointer")
        return None
    pointer = _read_json(pointer_path)
    if pointer.get("schema_version") != POINTER_SCHEMA:
        raise WalSyncError("off-VM WAL pointer schema is not supported")
    manifest_name = pointer.get("manifest_path")
    if not isinstance(manifest_name, str) or not re.fullmatch(
        r"manifests/[0-9a-f]{64}\.json",
        manifest_name,
    ):
        raise WalSyncError("off-VM WAL pointer contains an unsafe manifest path")
    manifest = _read_json(destination / Path(manifest_name))
    if manifest.get("manifest_identity_sha256") != pointer.get("manifest_identity_sha256"):
        raise WalSyncError("off-VM WAL pointer and immutable manifest identities differ")
    return pointer, manifest


def _prune_immutable_manifests(
    *,
    destination: Path,
    current_identity: str,
) -> dict[str, Any]:
    manifest_dir = destination / "manifests"
    observed: list[tuple[datetime, str, Path]] = []
    for path in manifest_dir.iterdir():
        if not path.is_file():
            continue
        if not re.fullmatch(r"[0-9a-f]{64}\.json", path.name):
            raise WalSyncError("off-VM manifest directory contains an unexpected file")
        manifest = _read_json(path)
        core = dict(manifest)
        identity = core.pop("manifest_identity_sha256", None)
        if (
            identity != path.stem
            or sha256_json(core) != identity
            or manifest.get("schema_version") != MANIFEST_SCHEMA
        ):
            raise WalSyncError("refusing retention cleanup because an immutable manifest is invalid")
        published = _parse_time(
            manifest.get("published_at_utc"),
            field="retained manifest published_at_utc",
        )
        observed.append((published, str(identity), path))
    identities = {item[1] for item in observed}
    if current_identity not in identities:
        raise WalSyncError("current WAL manifest is absent before retention cleanup")
    newest = sorted(observed, key=lambda item: (item[0], item[1]), reverse=True)
    keep_identities = {current_identity}
    for _, identity, _ in newest:
        if len(keep_identities) >= MAX_RETAINED_MANIFESTS:
            break
        keep_identities.add(identity)
    removed: list[str] = []
    for _, identity, path in observed:
        if identity in keep_identities:
            continue
        path.unlink()
        removed.append(identity)
    remaining = sorted(path.stem for path in manifest_dir.glob("*.json"))
    if current_identity not in remaining or len(remaining) > MAX_RETAINED_MANIFESTS:
        raise WalSyncError("WAL manifest retention did not converge to the approved maximum")
    return {
        "max_retained_manifests": MAX_RETAINED_MANIFESTS,
        "retained_manifest_count": len(remaining),
        "retained_manifest_identities": remaining,
        "removed_manifest_identities": sorted(removed),
        "wal_artifacts_pruned": False,
        "wal_retention_boundary": "oldest_retained_base_backup_managed_separately",
    }


def _verify_manifest_structure(
    *,
    destination: Path,
    manifest: Mapping[str, Any],
    storage: Mapping[str, Any],
    segment_size_bytes: int | None = None,
) -> list[dict[str, Any]]:
    if manifest.get("schema_version") != MANIFEST_SCHEMA:
        raise WalSyncError("off-VM WAL manifest schema is not supported")
    core = dict(manifest)
    identity = core.pop("manifest_identity_sha256", None)
    if not isinstance(identity, str) or sha256_json(core) != identity:
        raise WalSyncError("off-VM WAL manifest identity is invalid")
    if manifest.get("storage_identity") != storage.get("derived_storage_identity"):
        raise WalSyncError("off-VM WAL manifest belongs to another storage endpoint")
    boundary = manifest.get("initial_recovery_boundary")
    if not isinstance(boundary, Mapping):
        raise WalSyncError("off-VM WAL manifest lacks its initial base-recovery boundary")
    normalized_boundary = _initial_boundary_state(storage, boundary)
    if normalized_boundary.get("evidence_identity_sha256") != boundary.get(
        "evidence_identity_sha256"
    ):
        raise WalSyncError("off-VM WAL initial base-recovery boundary identity is invalid")
    try:
        configured_size = int(manifest.get("wal_segment_size_bytes") or 0)
    except (TypeError, ValueError) as exc:
        raise WalSyncError("off-VM WAL manifest has an invalid segment size") from exc
    if segment_size_bytes is not None and configured_size != segment_size_bytes:
        raise WalSyncError("WAL segment size changed across sync attempts")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise WalSyncError("off-VM WAL manifest has no artifacts")
    names: list[str] = []
    verified: list[dict[str, Any]] = []
    for item in artifacts:
        if not isinstance(item, dict):
            raise WalSyncError("off-VM WAL artifact is not an object")
        name = item.get("name")
        if not isinstance(name, str) or not WAL_NAME.fullmatch(name):
            raise WalSyncError("off-VM WAL artifact has an unsafe name")
        path = destination / "wal" / name
        if not path.is_file() or path.is_symlink():
            raise WalSyncError(f"off-VM WAL artifact is missing or unsafe: {name}")
        observed_size = path.stat().st_size
        declared_size = item.get("size")
        declared_hash = item.get("sha256")
        if (
            not isinstance(declared_size, int)
            or declared_size < 0
            or not isinstance(declared_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", declared_hash) is None
        ):
            raise WalSyncError(f"off-VM WAL artifact metadata is invalid: {name}")
        if observed_size != declared_size:
            raise WalSyncError(f"off-VM WAL artifact integrity mismatch: {name}")
        names.append(name)
        verified.append({"name": name, "size": observed_size, "sha256": declared_hash})
    if names != sorted(names) or len(names) != len(set(names)):
        raise WalSyncError("off-VM WAL artifact order or uniqueness is invalid")
    _require_contiguous(names, segment_size_bytes=configured_size)
    extra = {
        path.name
        for path in (destination / "wal").iterdir()
        if path.is_file() and WAL_NAME.fullmatch(path.name)
    } - set(names)
    if extra:
        raise WalSyncError("off-VM WAL directory contains unmanifested complete segments")
    if manifest.get("first_wal_segment") != names[0] or manifest.get("last_wal_segment") != names[-1]:
        raise WalSyncError("off-VM WAL manifest boundary does not match its artifacts")
    if manifest.get("artifact_count") != len(verified):
        raise WalSyncError("off-VM WAL manifest artifact count is invalid")
    return verified


def _verify_manifest_content(
    *,
    destination: Path,
    manifest: Mapping[str, Any],
    storage: Mapping[str, Any],
    segment_size_bytes: int | None = None,
) -> list[dict[str, Any]]:
    declared = _verify_manifest_structure(
        destination=destination,
        manifest=manifest,
        storage=storage,
        segment_size_bytes=segment_size_bytes,
    )
    verified: list[dict[str, Any]] = []
    for item in declared:
        observed_hash = sha256_file(destination / "wal" / item["name"])
        if observed_hash != item["sha256"]:
            raise WalSyncError(f"off-VM WAL artifact integrity mismatch: {item['name']}")
        verified.append({**item, "sha256": observed_hash})
    return verified


def _integrity_state(
    manifest: Mapping[str, Any],
    *,
    observed_now: datetime,
    max_full_scrub_age_seconds: float,
    enforce_scrub_age: bool = True,
) -> dict[str, Any]:
    value = manifest.get("integrity_verification")
    if not isinstance(value, Mapping) or value.get("schema_version") != INTEGRITY_SCHEMA:
        raise WalSyncError("off-VM WAL manifest lacks incremental integrity-chain evidence")
    scrubbed_at = _parse_time(
        value.get("last_full_scrub_at_utc"),
        field="last_full_scrub_at_utc",
    )
    age = (observed_now - scrubbed_at).total_seconds()
    if age < 0:
        raise WalSyncError("off-VM WAL full scrub is dated in the future")
    if max_full_scrub_age_seconds <= 0:
        raise WalSyncError("maximum full WAL scrub age must be positive")
    if enforce_scrub_age and age > max_full_scrub_age_seconds:
        raise WalSyncError("off-VM WAL full content scrub is stale")
    parent = value.get("parent_manifest_identity_sha256")
    if parent is not None and (
        not isinstance(parent, str) or re.fullmatch(r"[0-9a-f]{64}", parent) is None
    ):
        raise WalSyncError("off-VM WAL integrity chain has an invalid parent identity")
    if parent != manifest.get("prior_manifest_identity_sha256"):
        raise WalSyncError("off-VM WAL integrity chain parent does not match the manifest")
    for field in ("reused_artifact_count", "newly_verified_artifact_count"):
        if not isinstance(value.get(field), int) or value[field] < 0:
            raise WalSyncError("off-VM WAL integrity chain has an invalid artifact count")
    if value["reused_artifact_count"] + value["newly_verified_artifact_count"] != manifest.get(
        "artifact_count"
    ):
        raise WalSyncError("off-VM WAL integrity chain does not cover the manifest artifact set")
    if value.get("current_manifest_is_self_contained") is not True:
        raise WalSyncError("off-VM WAL integrity chain is not self-contained")
    return {**dict(value), "last_full_scrub_age_seconds": age}


def verify_wal_sync(
    *,
    destination: Path,
    expected_storage_identity: str | None = None,
    max_age_seconds: float,
    now: datetime | None = None,
    verification_mode: str = "full_content",
    max_full_scrub_age_seconds: float = DEFAULT_MAX_FULL_SCRUB_AGE_SECONDS,
) -> dict[str, Any]:
    storage = _storage_evidence(destination, expected_storage_identity)
    loaded = _load_latest(destination)
    if loaded is None:
        raise WalSyncError("off-VM WAL manifest pointer is absent")
    pointer, manifest = loaded
    observed_now = _utc(now)
    if verification_mode == "full_content":
        _verify_manifest_content(destination=destination, manifest=manifest, storage=storage)
        integrity = manifest.get("integrity_verification")
        if isinstance(integrity, Mapping) and integrity.get("schema_version") == INTEGRITY_SCHEMA:
            integrity_result = _integrity_state(
                manifest,
                observed_now=observed_now,
                max_full_scrub_age_seconds=max_full_scrub_age_seconds,
                enforce_scrub_age=False,
            )
            integrity_result["full_content_verified_at_utc"] = _iso(observed_now)
            integrity_result["full_content_verified_this_call"] = True
        else:
            integrity_result = {
                "schema_version": "honghu.stage5_wal_integrity_legacy_full_verification.v1",
                "verification_mode": "full_content",
                "last_full_scrub_at_utc": _iso(observed_now),
                "last_full_scrub_age_seconds": 0.0,
                "legacy_manifest": True,
            }
    elif verification_mode == "incremental_chain":
        _verify_manifest_structure(destination=destination, manifest=manifest, storage=storage)
        integrity_result = _integrity_state(
            manifest,
            observed_now=observed_now,
            max_full_scrub_age_seconds=max_full_scrub_age_seconds,
        )
    else:
        raise WalSyncError("unsupported WAL verification mode")
    published = _parse_time(manifest.get("published_at_utc"), field="published_at_utc")
    publication_age = (observed_now - published).total_seconds()
    if publication_age < 0:
        raise WalSyncError("off-VM WAL manifest publication is in the future")
    target_at = _parse_time(
        manifest.get("recoverable_target_at_utc"),
        field="recoverable_target_at_utc",
    )
    if target_at > published:
        raise WalSyncError("recoverable target is newer than manifest publication")
    recovery_point_age = (observed_now - target_at).total_seconds()
    if max_age_seconds < 0 or recovery_point_age > max_age_seconds:
        raise WalSyncError("off-VM WAL recovery point is stale")
    manifest_paths = sorted((destination / "manifests").glob("*.json"))
    if not manifest_paths or len(manifest_paths) > MAX_RETAINED_MANIFESTS:
        raise WalSyncError("off-VM WAL immutable manifest retention exceeds the approved maximum")
    if not any(path.stem == manifest["manifest_identity_sha256"] for path in manifest_paths):
        raise WalSyncError("current off-VM WAL manifest is absent from the retained set")
    return {
        "schema_version": "honghu.stage5_offvm_wal_verification.v1",
        "verified": True,
        "manifest_identity_sha256": manifest["manifest_identity_sha256"],
        "manifest_published_at_utc": _iso(published),
        "latest_recoverable_at_utc": _iso(target_at),
        "recovery_point_publication_lag_seconds": (published - target_at).total_seconds(),
        "manifest_publication_age_seconds": publication_age,
        "recovery_point_age_seconds": recovery_point_age,
        "storage": storage,
        "at_rest_encryption": manifest.get("at_rest_encryption"),
        "first_wal_segment": manifest["first_wal_segment"],
        "last_wal_segment": manifest["last_wal_segment"],
        "artifact_count": len(manifest["artifacts"]),
        "verification_mode": verification_mode,
        "full_content_verified_this_call": verification_mode == "full_content",
        "integrity_verification": integrity_result,
        "initial_recovery_boundary": manifest["initial_recovery_boundary"],
        "continuous_rpo_measured": False,
        "continuous_rpo_note": "measure against a later failure cutoff using this pre-existing recovery point",
        "pointer": pointer,
        "retention": {
            "max_retained_manifests": MAX_RETAINED_MANIFESTS,
            "retained_manifest_count": len(manifest_paths),
            "retained_manifest_identities": [path.stem for path in manifest_paths],
            "wal_artifacts_pruned": False,
            "wal_retention_boundary": "oldest_retained_base_backup_managed_separately",
        },
    }


def sync_archived_wal(
    *,
    source_archive: Path,
    destination: Path,
    recoverable_target_at: str | datetime,
    target_wal_segment: str,
    expected_storage_identity: str | None = None,
    wal_segment_size_bytes: int = 16 * 1024 * 1024,
    at_rest_encryption_evidence: Mapping[str, Any] | None = None,
    initial_recovery_boundary: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    max_full_scrub_age_seconds: float = DEFAULT_MAX_FULL_SCRUB_AGE_SECONDS,
) -> dict[str, Any]:
    storage = _storage_evidence(destination, expected_storage_identity)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "wal").mkdir(exist_ok=True)
    (destination / "manifests").mkdir(exist_ok=True)
    observed_now = _utc(now)
    target_at = (
        _utc(recoverable_target_at)
        if isinstance(recoverable_target_at, datetime)
        else _parse_time(recoverable_target_at, field="recoverable_target_at")
    )
    if target_at > observed_now:
        raise WalSyncError("recoverable target cannot be in the future")
    if not WAL_NAME.fullmatch(target_wal_segment):
        raise WalSyncError("target WAL segment name is invalid")
    if max_full_scrub_age_seconds <= 0:
        raise WalSyncError("maximum full WAL scrub age must be positive")
    with _exclusive_lock(destination):
        prior = _load_latest(destination)
        source = _source_segments(source_archive)
        if target_wal_segment not in source:
            raise WalSyncError("target WAL segment is not durably present in the source archive")
        prior_artifacts: list[dict[str, Any]] = []
        full_scrub_performed = prior is None
        last_full_scrub_at = observed_now
        if prior is not None:
            prior_artifacts = _verify_manifest_structure(
                destination=destination,
                manifest=prior[1],
                storage=storage,
                segment_size_bytes=wal_segment_size_bytes,
            )
            prior_integrity = prior[1].get("integrity_verification")
            if isinstance(prior_integrity, Mapping) and prior_integrity.get(
                "schema_version"
            ) == INTEGRITY_SCHEMA:
                validated_integrity = _integrity_state(
                    prior[1],
                    observed_now=observed_now,
                    max_full_scrub_age_seconds=max_full_scrub_age_seconds,
                    enforce_scrub_age=False,
                )
                last_full_scrub_at = _parse_time(
                    validated_integrity["last_full_scrub_at_utc"],
                    field="last_full_scrub_at_utc",
                )
                scrub_age = validated_integrity["last_full_scrub_age_seconds"]
                if scrub_age > max_full_scrub_age_seconds:
                    prior_artifacts = _verify_manifest_content(
                        destination=destination,
                        manifest=prior[1],
                        storage=storage,
                        segment_size_bytes=wal_segment_size_bytes,
                    )
                    full_scrub_performed = True
                    last_full_scrub_at = observed_now
            else:
                # The v1 publisher calculated every destination artifact hash
                # before atomically publishing the manifest.  Its publication
                # time is therefore a valid one-time full-scrub trust anchor for
                # an in-place upgrade; it is not necessary to re-read the whole
                # recovery chain merely to add the incremental lineage fields.
                last_full_scrub_at = _parse_time(
                    prior[1].get("published_at_utc"),
                    field="legacy full scrub published_at_utc",
                )
                legacy_scrub_age = (observed_now - last_full_scrub_at).total_seconds()
                if legacy_scrub_age < 0:
                    raise WalSyncError("legacy off-VM WAL manifest is dated in the future")
                if legacy_scrub_age > max_full_scrub_age_seconds:
                    prior_artifacts = _verify_manifest_content(
                        destination=destination,
                        manifest=prior[1],
                        storage=storage,
                        segment_size_bytes=wal_segment_size_bytes,
                    )
                    full_scrub_performed = True
                    last_full_scrub_at = observed_now
            boundary = prior[1].get("initial_recovery_boundary")
            if not isinstance(boundary, Mapping):
                raise WalSyncError("prior WAL manifest lacks its initial base-recovery boundary")
            if initial_recovery_boundary is not None:
                requested_boundary = _initial_boundary_state(storage, initial_recovery_boundary)
                if requested_boundary["evidence_identity_sha256"] != boundary.get(
                    "evidence_identity_sha256"
                ):
                    raise WalSyncError("initial WAL boundary changed after the chain was published")
            prior_last = str(prior[1].get("last_wal_segment") or "")
            prior_position = _wal_position(prior_last, segment_size_bytes=wal_segment_size_bytes)
            target_position = _wal_position(
                target_wal_segment,
                segment_size_bytes=wal_segment_size_bytes,
            )
            if target_position < prior_position:
                raise WalSyncError("WAL sync target cannot move behind the published recovery point")
            selected_names = sorted(
                name
                for name in source
                if prior_position < _wal_position(name, segment_size_bytes=wal_segment_size_bytes) <= target_position
            )
            if selected_names:
                _require_contiguous(selected_names, segment_size_bytes=wal_segment_size_bytes)
                first_position = _wal_position(
                    selected_names[0],
                    segment_size_bytes=wal_segment_size_bytes,
                )
                if first_position != (prior_position[0], prior_position[1] + 1):
                    raise WalSyncError("new archived WAL does not continue the published off-VM chain")
            elif target_position != prior_position:
                raise WalSyncError("target WAL is newer but no continuing archived segment is available")
        else:
            boundary = _initial_boundary_state(storage, initial_recovery_boundary)
            first_required = str(boundary["first_required_wal_segment"])
            first_position = _wal_position(
                first_required,
                segment_size_bytes=wal_segment_size_bytes,
            )
            target_position = _wal_position(
                target_wal_segment,
                segment_size_bytes=wal_segment_size_bytes,
            )
            if target_position < first_position:
                raise WalSyncError("target WAL precedes the verified base-recovery boundary")
            if first_required not in source:
                raise WalSyncError("first-required WAL segment is absent from the source archive")
            selected_names = sorted(
                name
                for name in source
                if first_position <= _wal_position(name, segment_size_bytes=wal_segment_size_bytes) <= target_position
            )
            _require_contiguous(selected_names, segment_size_bytes=wal_segment_size_bytes)
        new_artifacts: list[dict[str, Any]] = []
        for name in selected_names:
            source_path = source[name]
            destination_path = destination / "wal" / name
            source_size = source_path.stat().st_size
            source_hash = sha256_file(source_path)
            if destination_path.exists():
                if (
                    not destination_path.is_file()
                    or destination_path.is_symlink()
                    or destination_path.stat().st_size != source_size
                    or sha256_file(destination_path) != source_hash
                ):
                    raise WalSyncError(f"refusing to overwrite a different off-VM WAL segment: {name}")
                new_artifacts.append(
                    {"name": name, "size": source_size, "sha256": source_hash}
                )
                continue
            temporary = destination_path.with_name(f".{name}.{os.getpid()}.tmp")
            try:
                with source_path.open("rb") as reader, temporary.open("xb") as writer:
                    shutil.copyfileobj(reader, writer, length=1024 * 1024)
                    writer.flush()
                    os.fsync(writer.fileno())
                if temporary.stat().st_size != source_size or sha256_file(temporary) != source_hash:
                    raise WalSyncError(f"off-VM WAL copy verification failed: {name}")
                if destination_path.exists():
                    if sha256_file(destination_path) != source_hash:
                        raise WalSyncError(f"concurrent WAL copy differs: {name}")
                else:
                    os.replace(temporary, destination_path)
                if sha256_file(destination_path) != source_hash:
                    raise WalSyncError(f"off-VM WAL final copy verification failed: {name}")
            finally:
                temporary.unlink(missing_ok=True)
            new_artifacts.append(
                {"name": name, "size": source_size, "sha256": source_hash}
            )
        destination_names = sorted(
            path.name
            for path in (destination / "wal").iterdir()
            if path.is_file() and WAL_NAME.fullmatch(path.name)
        )
        _require_contiguous(destination_names, segment_size_bytes=wal_segment_size_bytes)
        if destination_names[0] != boundary["first_required_wal_segment"]:
            raise WalSyncError("off-VM WAL chain does not begin at the verified base-recovery boundary")
        if destination_names[-1] != target_wal_segment:
            raise WalSyncError("off-VM WAL directory contains data beyond or short of the declared target")
        artifact_by_name = {
            item["name"]: dict(item) for item in [*prior_artifacts, *new_artifacts]
        }
        if set(artifact_by_name) != set(destination_names):
            raise WalSyncError("incremental WAL artifact chain does not cover the destination")
        artifacts = [artifact_by_name[name] for name in destination_names]
        encryption = _encryption_state(
            storage,
            at_rest_encryption_evidence,
            observed_at=observed_now,
        )
        source_identity = sha256_json(
            {
                "host": socket.gethostname().strip().casefold(),
                "archive_path": str(source_archive.resolve()).casefold(),
            }
        )
        core = {
            "schema_version": MANIFEST_SCHEMA,
            "published_at_utc": _iso(observed_now),
            "recoverable_target_at_utc": _iso(target_at),
            "source_archive_identity_sha256": source_identity,
            "storage_identity": storage["derived_storage_identity"],
            "storage_failure_domain": storage.get("failure_domain"),
            "wal_segment_size_bytes": wal_segment_size_bytes,
            "first_wal_segment": destination_names[0],
            "last_wal_segment": destination_names[-1],
            "artifact_count": len(artifacts),
            "artifacts": artifacts,
            "prior_manifest_identity_sha256": (
                prior[1].get("manifest_identity_sha256") if prior is not None else None
            ),
            "initial_recovery_boundary": dict(boundary),
            "at_rest_encryption": encryption,
            "integrity_verification": {
                "schema_version": INTEGRITY_SCHEMA,
                "verification_mode": (
                    "full_scrub_plus_incremental_copy"
                    if full_scrub_performed
                    else "incremental_manifest_chain"
                ),
                "parent_manifest_identity_sha256": (
                    prior[1].get("manifest_identity_sha256") if prior is not None else None
                ),
                "reused_artifact_count": len(prior_artifacts),
                "newly_verified_artifact_count": len(new_artifacts),
                "last_full_scrub_at_utc": _iso(last_full_scrub_at),
                "max_full_scrub_age_seconds": max_full_scrub_age_seconds,
                "full_scrub_performed_this_cycle": full_scrub_performed,
                "current_manifest_is_self_contained": True,
                "historical_hash_reuse_is_bounded_by_full_scrub": True,
            },
            "continuous_rpo_measured": False,
            "retention_policy": {
                "max_immutable_wal_manifests": MAX_RETAINED_MANIFESTS,
                "full_recovery_sets_managed_separately": True,
                "wal_artifacts_require_oldest_retained_base_boundary": True,
            },
        }
        identity = sha256_json(core)
        manifest = {**core, "manifest_identity_sha256": identity}
        manifest_path = destination / "manifests" / f"{identity}.json"
        if manifest_path.exists():
            if _read_json(manifest_path) != manifest:
                raise WalSyncError("immutable WAL manifest identity collision")
        else:
            _atomic_json(manifest_path, manifest)
        pointer = {
            "schema_version": POINTER_SCHEMA,
            "manifest_path": f"manifests/{identity}.json",
            "manifest_identity_sha256": identity,
            "published_at_utc": _iso(observed_now),
        }
        _atomic_json(destination / "latest_verified_wal_manifest.json", pointer)
        _prune_immutable_manifests(
            destination=destination,
            current_identity=identity,
        )
    return verify_wal_sync(
        destination=destination,
        expected_storage_identity=expected_storage_identity,
        max_age_seconds=(observed_now - target_at).total_seconds() + 0.001,
        now=observed_now,
        verification_mode="incremental_chain",
        max_full_scrub_age_seconds=max_full_scrub_age_seconds,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synchronize complete archived WAL to verified off-VM storage")
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--recoverable-target-at", required=True)
    parser.add_argument("--target-wal-segment", required=True)
    parser.add_argument("--expected-storage-identity")
    parser.add_argument("--at-rest-encryption-evidence", type=Path)
    parser.add_argument("--initial-recovery-boundary", type=Path)
    parser.add_argument("--wal-segment-size-bytes", type=int, default=16 * 1024 * 1024)
    parser.add_argument(
        "--max-full-scrub-age-seconds",
        type=float,
        default=DEFAULT_MAX_FULL_SCRUB_AGE_SECONDS,
    )
    args = parser.parse_args(argv)
    encryption_evidence = (
        _read_json(args.at_rest_encryption_evidence)
        if args.at_rest_encryption_evidence
        else None
    )
    initial_boundary = (
        _read_json(args.initial_recovery_boundary)
        if args.initial_recovery_boundary
        else None
    )
    result = sync_archived_wal(
        source_archive=args.source_archive,
        destination=args.destination,
        recoverable_target_at=args.recoverable_target_at,
        target_wal_segment=args.target_wal_segment,
        expected_storage_identity=args.expected_storage_identity,
        wal_segment_size_bytes=args.wal_segment_size_bytes,
        at_rest_encryption_evidence=encryption_evidence,
        initial_recovery_boundary=initial_boundary,
        max_full_scrub_age_seconds=args.max_full_scrub_age_seconds,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
