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


WAL_NAME = re.compile(r"^[0-9A-F]{24}$")
MANIFEST_SCHEMA = "honghu.stage5_offvm_wal_manifest.v1"
POINTER_SCHEMA = "honghu.stage5_offvm_wal_pointer.v1"


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
    if not isinstance(value, str) or not value.strip():
        raise WalSyncError(f"{field} must be an ISO-8601 timestamp")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise WalSyncError(f"{field} is not a valid ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WalSyncError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


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


def _verify_manifest_content(
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
    configured_size = int(manifest.get("wal_segment_size_bytes") or 0)
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
        observed_hash = sha256_file(path)
        if observed_size != item.get("size") or observed_hash != item.get("sha256"):
            raise WalSyncError(f"off-VM WAL artifact integrity mismatch: {name}")
        names.append(name)
        verified.append({"name": name, "size": observed_size, "sha256": observed_hash})
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
    return verified


def verify_wal_sync(
    *,
    destination: Path,
    expected_storage_identity: str | None = None,
    max_age_seconds: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    storage = _storage_evidence(destination, expected_storage_identity)
    loaded = _load_latest(destination)
    if loaded is None:
        raise WalSyncError("off-VM WAL manifest pointer is absent")
    pointer, manifest = loaded
    _verify_manifest_content(destination=destination, manifest=manifest, storage=storage)
    observed_now = _utc(now)
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
        "continuous_rpo_measured": False,
        "continuous_rpo_note": "measure against a later failure cutoff using this pre-existing recovery point",
        "pointer": pointer,
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
    now: datetime | None = None,
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
    source = _source_segments(source_archive)
    selected_names = sorted(name for name in source if name <= target_wal_segment)
    if target_wal_segment not in source:
        raise WalSyncError("target WAL segment is not durably present in the source archive")
    _require_contiguous(selected_names, segment_size_bytes=wal_segment_size_bytes)
    with _exclusive_lock(destination):
        prior = _load_latest(destination)
        if prior is not None:
            _verify_manifest_content(
                destination=destination,
                manifest=prior[1],
                storage=storage,
                segment_size_bytes=wal_segment_size_bytes,
            )
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
            finally:
                temporary.unlink(missing_ok=True)
        destination_names = sorted(
            path.name
            for path in (destination / "wal").iterdir()
            if path.is_file() and WAL_NAME.fullmatch(path.name)
        )
        _require_contiguous(destination_names, segment_size_bytes=wal_segment_size_bytes)
        if destination_names[-1] != target_wal_segment:
            raise WalSyncError("off-VM WAL directory contains data beyond or short of the declared target")
        artifacts = [
            {
                "name": name,
                "size": (destination / "wal" / name).stat().st_size,
                "sha256": sha256_file(destination / "wal" / name),
            }
            for name in destination_names
        ]
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
            "at_rest_encryption": encryption,
            "continuous_rpo_measured": False,
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
    return verify_wal_sync(
        destination=destination,
        expected_storage_identity=expected_storage_identity,
        max_age_seconds=(observed_now - target_at).total_seconds() + 0.001,
        now=observed_now,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Synchronize complete archived WAL to verified off-VM storage")
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--recoverable-target-at", required=True)
    parser.add_argument("--target-wal-segment", required=True)
    parser.add_argument("--expected-storage-identity")
    parser.add_argument("--wal-segment-size-bytes", type=int, default=16 * 1024 * 1024)
    args = parser.parse_args(argv)
    result = sync_archived_wal(
        source_archive=args.source_archive,
        destination=args.destination,
        recoverable_target_at=args.recoverable_target_at,
        target_wal_segment=args.target_wal_segment,
        expected_storage_identity=args.expected_storage_identity,
        wal_segment_size_bytes=args.wal_segment_size_bytes,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
