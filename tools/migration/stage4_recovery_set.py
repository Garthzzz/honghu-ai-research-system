from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import socket
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any


SCHEMA_VERSION = "honghu.stage4_recovery_set.v2"
MANIFEST_NAME = "recovery_set_manifest.json"


class RecoverySetError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalise_host(value: str) -> str:
    return value.strip().rstrip(".").casefold()


def _resolved_addresses(host: str) -> list[str]:
    try:
        return sorted({item[4][0] for item in socket.getaddrinfo(host, None)})
    except OSError as exc:
        raise RecoverySetError(f"storage endpoint cannot be resolved: {host}") from exc


def _local_addresses() -> set[str]:
    names = {socket.gethostname(), socket.getfqdn(), "localhost"}
    addresses: set[str] = {"127.0.0.1", "::1"}
    for name in names:
        try:
            addresses.update(item[4][0] for item in socket.getaddrinfo(name, None))
        except OSError:
            continue
    return addresses


def _windows_volume_identity(root: str) -> dict[str, Any]:
    if os.name != "nt":
        stat = os.stat(root)
        return {"volume_serial": str(stat.st_dev), "filesystem": None, "volume_label": None}
    volume_name = ctypes.create_unicode_buffer(261)
    filesystem_name = ctypes.create_unicode_buffer(261)
    serial = ctypes.c_uint32()
    maximum_component = ctypes.c_uint32()
    flags = ctypes.c_uint32()
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(root),
        volume_name,
        len(volume_name),
        ctypes.byref(serial),
        ctypes.byref(maximum_component),
        ctypes.byref(flags),
        filesystem_name,
        len(filesystem_name),
    )
    if not ok:
        raise RecoverySetError(f"cannot read storage volume identity: {root}")
    return {
        "volume_serial": f"{serial.value:08x}",
        "filesystem": filesystem_name.value or None,
        "volume_label": volume_name.value or None,
    }


def probe_storage_endpoint(path: Path) -> dict[str, Any]:
    """Derive storage identity from the endpoint itself, never from a caller label.

    A local path is deliberately classified as the local failure domain even when
    it is on another drive.  An off-host Windows target must be a UNC share whose
    server resolves away from every local address and whose share volume can be
    queried through the mounted endpoint.
    """

    raw = str(path)
    if raw.startswith("\\\\"):
        parts = PureWindowsPath(raw).parts
        if not parts:
            raise RecoverySetError("UNC recovery path has no authority")
        anchor = parts[0].rstrip("\\")
        authority = anchor.lstrip("\\")
        authority_parts = authority.split("\\", 1)
        if len(authority_parts) != 2 or not all(authority_parts):
            raise RecoverySetError("UNC recovery path must include server and share")
        server, share = authority_parts
        server_name = _normalise_host(server)
        local_names = {_normalise_host(socket.gethostname()), _normalise_host(socket.getfqdn()), "localhost"}
        remote_addresses = _resolved_addresses(server)
        if server_name in local_names or set(remote_addresses) & _local_addresses():
            raise RecoverySetError("same-host UNC aliases cannot satisfy off-VM recovery")
        volume = _windows_volume_identity(f"\\\\{server}\\{share}\\")
        core = {
            "kind": "windows_unc",
            "server": server_name,
            "share": share.casefold(),
            "resolved_addresses": remote_addresses,
            "volume_serial": volume["volume_serial"],
            "filesystem": volume["filesystem"],
        }
        return {
            **core,
            "volume_label": volume["volume_label"],
            "failure_domain": "remote_host_storage",
            "independent_from_source_host": True,
            "derived_storage_identity": sha256_json(core),
            "identity_source": "endpoint_dns_and_volume_probe",
        }

    resolved = path.resolve()
    anchor = resolved.anchor or str(resolved)
    volume = _windows_volume_identity(anchor)
    core = {
        "kind": "local_filesystem",
        "host": _normalise_host(socket.gethostname()),
        "volume_serial": volume["volume_serial"],
        "filesystem": volume["filesystem"],
    }
    return {
        **core,
        "volume_label": volume["volume_label"],
        "failure_domain": "source_host",
        "independent_from_source_host": False,
        "derived_storage_identity": sha256_json(core),
        "identity_source": "local_host_and_volume_probe",
    }


def _artifact_inventory(root: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file() and item.name != MANIFEST_NAME):
        if path.is_symlink():
            raise RecoverySetError(f"recovery set cannot contain symlink: {path}")
        relative = path.relative_to(root).as_posix()
        role = "base_backup" if relative.startswith("base_backup/") else "wal" if relative.startswith("wal/") else "metadata"
        artifacts.append(
            {
                "path": relative,
                "role": role,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return artifacts


def build_recovery_set(
    *,
    base_backup: Path,
    wal_archive: Path,
    destination: Path,
    source_identity: dict[str, Any],
    target: dict[str, Any],
    expected_storage_identity: str | None = None,
    require_off_vm: bool,
) -> dict[str, Any]:
    if destination.exists():
        raise RecoverySetError("recovery-set destination already exists")
    required_wal = [str(item) for item in target.get("required_wal_files") or []]
    if not required_wal:
        raise RecoverySetError("target recovery watermark has no required WAL files")
    for name in required_wal:
        if Path(name).name != name or not (wal_archive / name).is_file():
            raise RecoverySetError(f"required WAL is missing before copy: {name}")

    destination.mkdir(parents=True)
    shutil.copytree(base_backup, destination / "base_backup")
    (destination / "wal").mkdir()
    for name in sorted(required_wal):
        shutil.copy2(wal_archive / name, destination / "wal" / name)
    (destination / "target.json").write_text(
        json.dumps(target, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    storage = probe_storage_endpoint(destination)
    if require_off_vm and not storage.get("independent_from_source_host"):
        raise RecoverySetError("same-host storage cannot satisfy off-VM recovery")
    if expected_storage_identity and storage.get("derived_storage_identity") != expected_storage_identity:
        raise RecoverySetError("probed storage identity does not match approved expectation")

    artifacts = _artifact_inventory(destination)
    copied_wal = {item["path"].split("/", 1)[1] for item in artifacts if item["role"] == "wal"}
    missing = sorted(set(required_wal) - copied_wal)
    if missing:
        raise RecoverySetError(f"recovery set is missing required WAL: {missing}")
    manifest_core = {
        "schema_version": SCHEMA_VERSION,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_identity": source_identity,
        "storage_evidence": storage,
        "target": target,
        "artifacts": artifacts,
    }
    manifest = {**manifest_core, "recovery_set_identity": sha256_json(manifest_core)}
    (destination / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    verify_recovery_set(
        destination,
        expected_identity=manifest["recovery_set_identity"],
        expected_storage_identity=storage["derived_storage_identity"],
        verify_storage_location=True,
    )
    return manifest


def verify_recovery_set(
    root: Path,
    *,
    expected_identity: str | None = None,
    expected_storage_identity: str | None = None,
    verify_storage_location: bool = True,
) -> dict[str, Any]:
    manifest_path = root / MANIFEST_NAME
    if not manifest_path.is_file():
        raise RecoverySetError("recovery-set manifest is missing")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoverySetError("recovery-set manifest is unreadable") from exc
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise RecoverySetError("unsupported recovery-set schema")
    core = {key: value for key, value in manifest.items() if key != "recovery_set_identity"}
    actual_identity = sha256_json(core)
    if manifest.get("recovery_set_identity") != actual_identity:
        raise RecoverySetError("recovery-set manifest identity mismatch")
    if expected_identity and actual_identity != expected_identity:
        raise RecoverySetError("recovery-set copy identity mismatch")

    declared = {str(item.get("path")): item for item in manifest.get("artifacts") or []}
    actual_paths = {
        item.relative_to(root).as_posix()
        for item in root.rglob("*")
        if item.is_file() and item.name != MANIFEST_NAME
    }
    if set(declared) != actual_paths:
        raise RecoverySetError("recovery-set exact file set mismatch")
    for relative, item in declared.items():
        path = (root / relative).resolve()
        if root.resolve() not in path.parents or not path.is_file() or path.is_symlink():
            raise RecoverySetError(f"invalid recovery-set artifact: {relative}")
        if path.stat().st_size != item.get("size") or sha256_file(path) != item.get("sha256"):
            raise RecoverySetError(f"recovery-set artifact hash mismatch: {relative}")

    target = manifest.get("target") or {}
    required_wal = set(target.get("required_wal_files") or [])
    available_wal = {
        relative.split("/", 1)[1]
        for relative, item in declared.items()
        if item.get("role") == "wal" and relative.startswith("wal/")
    }
    if not required_wal or not required_wal <= available_wal:
        raise RecoverySetError("recovery-set WAL is insufficient for target watermark")
    if not str(target.get("sentinel_operation_id") or "").strip():
        raise RecoverySetError("recovery target sentinel identity is missing")
    if not str(target.get("target_lsn") or "").strip() or not str(target.get("durable_target_at_utc") or "").strip():
        raise RecoverySetError("recovery target watermark is incomplete")

    storage = manifest.get("storage_evidence") or {}
    if expected_storage_identity and storage.get("derived_storage_identity") != expected_storage_identity:
        raise RecoverySetError("recovery-set storage identity mismatch")
    if verify_storage_location:
        observed = probe_storage_endpoint(root)
        if observed.get("derived_storage_identity") != storage.get("derived_storage_identity"):
            raise RecoverySetError("recovery set is no longer on the attested storage endpoint")
    return manifest


def enforce_validated_recovery_retention(
    root: Path,
    *,
    current: Path,
    keep: int = 2,
    current_verified_manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Retain only the newest fully verified recovery sets.

    The new set is verified before any prior set is removed.  Directories
    without a valid manifest are reported as unvalidated and deliberately left
    for the separately audited failed-artifact cleanup; they never count as a
    recovery copy.  This prevents an interrupted copy from evicting a usable
    backup while keeping validated-set retention deterministic.
    """

    if keep < 1:
        raise RecoverySetError("validated recovery retention must keep at least one set")
    root = root.resolve()
    current = current.resolve()
    if current.parent != root or current.is_symlink():
        raise RecoverySetError("current recovery set is outside the retention root")
    if current_verified_manifest is None:
        current_manifest = verify_recovery_set(
            current, verify_storage_location=True
        )
    else:
        # The caller may pass the manifest returned by build_recovery_set(),
        # which is only returned after a complete exact-file/hash and storage
        # verification.  Reuse that proof for the current set after a restore
        # has actually consumed it; do not read the same multi-gigabyte set two
        # more times merely to apply retention.  The identity/path checks below
        # prevent a manifest from another set being substituted.
        current_manifest = current_verified_manifest
        manifest_path = current / MANIFEST_NAME
        if not manifest_path.is_file():
            raise RecoverySetError("current verified recovery-set manifest is missing")
        observed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            observed_manifest.get("recovery_set_identity")
            != current_manifest.get("recovery_set_identity")
            or sha256_json(
                {
                    key: value
                    for key, value in observed_manifest.items()
                    if key != "recovery_set_identity"
                }
            )
            != current_manifest.get("recovery_set_identity")
        ):
            raise RecoverySetError("current verified recovery-set identity changed")

    validated: list[tuple[datetime, Path, dict[str, Any]]] = []
    unvalidated: list[str] = []
    for candidate in sorted(path for path in root.iterdir() if path.is_dir()):
        if candidate.is_symlink() or candidate.resolve().parent != root:
            unvalidated.append(candidate.name)
            continue
        try:
            manifest = (
                current_manifest
                if candidate.resolve() == current
                else verify_recovery_set(candidate, verify_storage_location=True)
            )
            created = datetime.fromisoformat(
                str(manifest["created_at_utc"]).replace("Z", "+00:00")
            )
            if created.tzinfo is None:
                raise ValueError("created_at_utc has no timezone")
        except (KeyError, ValueError, RecoverySetError):
            unvalidated.append(candidate.name)
            continue
        validated.append((created.astimezone(timezone.utc), candidate.resolve(), manifest))

    if not any(path == current for _, path, _ in validated):
        raise RecoverySetError("current recovery set disappeared during retention audit")
    validated.sort(key=lambda item: (item[0], item[1].name), reverse=True)
    retained = validated[:keep]
    to_delete = validated[keep:]
    if current not in {path for _, path, _ in retained}:
        raise RecoverySetError("newly validated recovery set is not within retention window")

    deleted: list[str] = []
    for _, candidate, _ in to_delete:
        if candidate == current or candidate.parent != root or candidate.is_symlink():
            raise RecoverySetError("retention refused an unsafe recovery-set deletion")
        shutil.rmtree(candidate)
        deleted.append(candidate.name)

    return {
        "policy": "newest_validated_sets_only",
        "keep": keep,
        "current_recovery_set_identity": current_manifest["recovery_set_identity"],
        "retained": [path.name for _, path, _ in retained],
        "deleted": deleted,
        "unvalidated_not_counted_or_deleted": sorted(unvalidated),
    }


def assert_restore_sources(recovery_set_root: Path, base_source: Path, wal_source: Path) -> None:
    root = recovery_set_root.resolve()
    expected_base = (root / "base_backup").resolve()
    expected_wal = (root / "wal").resolve()
    if base_source.resolve() != expected_base or wal_source.resolve() != expected_wal:
        raise RecoverySetError("restore attempted to use artifacts outside the recovery set")


def measured_recovery(
    *, target: dict[str, Any], recovered: dict[str, Any], restore_elapsed_seconds: float
) -> dict[str, Any]:
    if recovered.get("sentinel_operation_id") != target.get("sentinel_operation_id"):
        raise RecoverySetError("target recovery sentinel was not restored")
    if recovered.get("target_lsn_reached") is not True:
        raise RecoverySetError("recovery did not reach the target LSN")
    target_time = datetime.fromisoformat(str(target["durable_target_at_utc"]).replace("Z", "+00:00"))
    recovered_time = datetime.fromisoformat(str(recovered["recovered_watermark_at_utc"]).replace("Z", "+00:00"))
    if target_time.tzinfo is None or recovered_time.tzinfo is None:
        raise RecoverySetError("recovery watermark timestamps must include timezone")
    rpo_seconds = max(0.0, (target_time - recovered_time).total_seconds())
    return {
        "rpo_seconds": round(rpo_seconds, 3),
        "rto_seconds": round(float(restore_elapsed_seconds), 3),
        "durable_target_at_utc": target_time.astimezone(timezone.utc).isoformat(),
        "recovered_watermark_at_utc": recovered_time.astimezone(timezone.utc).isoformat(),
        "target_lsn": target.get("target_lsn"),
        "recovered_lsn": recovered.get("recovered_lsn"),
        "sentinel_operation_id": target.get("sentinel_operation_id"),
        "measurement_contract": "durable_target_minus_recovered_watermark",
    }
