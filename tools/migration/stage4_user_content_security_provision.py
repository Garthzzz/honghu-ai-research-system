from __future__ import annotations

"""Provision user-content credentials without persisting plaintext secrets.

``generate`` runs on the operator workstation.  It creates fresh old/current
secrets, keeps only the current acceptance passwords in that workstation's
Windows Credential Manager, and writes the secret payload to stdout so it can
be piped directly over SSH.  ``seal`` runs in the VM SSH session and protects
stdin with machine-scope DPAPI.  ``provision`` must then run under the approved
interactive VM token; it decrypts the envelope, updates and verifies the
interactive user's WinVault entries, and removes the envelope only after the
whole operation succeeds.  No command prints a secret or password
hash.
"""

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class SecurityProvisionError(RuntimeError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _winvault():
    if os.name != "nt":
        raise SecurityProvisionError("Windows Credential Manager is required")
    import keyring
    from keyring.backends.Windows import WinVaultKeyring

    keyring.set_keyring(WinVaultKeyring())
    return keyring


def _protect(payload: bytes) -> bytes:
    import win32crypt

    description = "honghu-user-content-cutover"
    flags = getattr(win32crypt, "CRYPTPROTECT_LOCAL_MACHINE", 0x4)
    return win32crypt.CryptProtectData(payload, description, None, None, None, flags)


def _unprotect(payload: bytes) -> bytes:
    import win32crypt

    _description, plaintext = win32crypt.CryptUnprotectData(payload, None, None, None, 0)
    return plaintext


def _settings(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if payload.get("schema_version") != "honghu.user_content_security.v1":
        raise SecurityProvisionError("unsupported security configuration")
    if payload.get("enabled") is not True or payload.get("require_https") is not True:
        raise SecurityProvisionError("production user-content security must require HTTPS")
    principals = payload.get("principals")
    if not isinstance(principals, dict) or len(principals) < 2:
        raise SecurityProvisionError("at least two production principals are required")
    writable = [
        subject
        for subject, permissions in principals.items()
        if "analyst_note:write" in (permissions or [])
    ]
    readonly = [
        subject
        for subject, permissions in principals.items()
        if "analyst_note:read" in (permissions or [])
        and "analyst_note:write" not in (permissions or [])
    ]
    if not writable or not readonly:
        raise SecurityProvisionError("writer and read-only principals are both required")
    for field in (
        "credential_service",
        "session_secret_service",
        "session_secret_account",
    ):
        if not str(payload.get(field) or "").strip():
            raise SecurityProvisionError(f"security configuration is missing {field}")
    return payload


def generate(config: Path, *, acceptance_credential_service: str | None = None) -> int:
    settings = _settings(config)
    keyring = _winvault()
    old_passwords = {subject: secrets.token_urlsafe(36) for subject in settings["principals"]}
    current_passwords = {
        subject: secrets.token_urlsafe(36) for subject in settings["principals"]
    }
    acceptance_service = (
        str(acceptance_credential_service or "").strip()
        or settings["credential_service"]
    )
    for subject, password in current_passwords.items():
        keyring.set_password(acceptance_service, subject, password)
        if keyring.get_password(acceptance_service, subject) != password:
            raise SecurityProvisionError("local acceptance credential round trip failed")
    envelope = {
        "schema_version": "honghu.user_content_security_secret_envelope.v1",
        "security_config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "old_passwords": old_passwords,
        "current_passwords": current_passwords,
        "old_session_secret": secrets.token_urlsafe(64),
        "current_session_secret": secrets.token_urlsafe(64),
        "revoked_principal": "stage4-revoked-probe",
        "revoked_password": secrets.token_urlsafe(36),
    }
    # The sole stdout payload is intended for a direct encrypted SSH pipe.
    # Callers must never capture it in a file, transcript or evidence.
    sys.stdout.write(json.dumps(envelope, ensure_ascii=False, separators=(",", ":")))
    return 0


def seal(envelope: Path) -> int:
    raw = sys.stdin.buffer.read()
    if not raw:
        raise SecurityProvisionError("secret envelope input is empty")
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("schema_version") != "honghu.user_content_security_secret_envelope.v1":
        raise SecurityProvisionError("unsupported secret envelope")
    envelope.parent.mkdir(parents=True, exist_ok=True)
    if envelope.exists():
        raise SecurityProvisionError("secret envelope already exists")
    temporary = envelope.with_suffix(envelope.suffix + ".tmp")
    temporary.write_bytes(_protect(raw))
    os.replace(temporary, envelope)
    print(json.dumps({"ok": True, "sealed": True, "secret_recorded": False}))
    return 0


def provision(config: Path, envelope: Path, output: Path) -> int:
    from werkzeug.security import check_password_hash, generate_password_hash

    settings = _settings(config)
    if not envelope.is_file():
        raise SecurityProvisionError("sealed secret envelope is missing")
    ciphertext = envelope.read_bytes()
    raw = _unprotect(ciphertext)
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("schema_version") != "honghu.user_content_security_secret_envelope.v1":
        raise SecurityProvisionError("unsupported decrypted secret envelope")
    if payload.get("security_config_sha256") != hashlib.sha256(config.read_bytes()).hexdigest():
        raise SecurityProvisionError("secret envelope belongs to another security config")
    old_passwords = payload.get("old_passwords") or {}
    current_passwords = payload.get("current_passwords") or {}
    if set(old_passwords) != set(settings["principals"]) or set(current_passwords) != set(
        settings["principals"]
    ):
        raise SecurityProvisionError("secret principal set differs from security config")
    keyring = _winvault()
    service = settings["credential_service"]
    for subject, password in old_passwords.items():
        encoded = generate_password_hash(password, method="scrypt")
        keyring.set_password(service, subject, encoded)
    for subject, password in current_passwords.items():
        encoded = generate_password_hash(password, method="scrypt")
        keyring.set_password(service, subject, encoded)
        stored = keyring.get_password(service, subject)
        if not stored or not check_password_hash(stored, password):
            raise SecurityProvisionError("rotated principal credential is unusable")
        if check_password_hash(stored, old_passwords[subject]):
            raise SecurityProvisionError("old principal credential remains valid")
    session_service = settings["session_secret_service"]
    session_account = settings["session_secret_account"]
    keyring.set_password(session_service, session_account, payload["old_session_secret"])
    keyring.set_password(session_service, session_account, payload["current_session_secret"])
    if keyring.get_password(session_service, session_account) != payload["current_session_secret"]:
        raise SecurityProvisionError("rotated session credential is unusable")
    revoked = str(payload["revoked_principal"])
    keyring.set_password(service, revoked, generate_password_hash(payload["revoked_password"]))
    keyring.delete_password(service, revoked)
    if keyring.get_password(service, revoked):
        raise SecurityProvisionError("revoked probe credential remains present")
    # Keep the machine-protected envelope throughout provisioning so an
    # interruption can be retried without regenerating or exposing secrets.
    # Removal is the final commit point, after every credential contract has
    # been verified.
    envelope.unlink()
    core = {
        "schema_version": "honghu.user_content_security_provision.v1",
        "status": "pass",
        "provisioned_at_utc": datetime.now(timezone.utc).isoformat(),
        "security_config_sha256": hashlib.sha256(config.read_bytes()).hexdigest(),
        "principal_subjects": sorted(settings["principals"]),
        "credential_service": service,
        "session_secret_identity": f"{session_service}/{session_account}",
        "create_verified": True,
        "rotate_new_accepted": True,
        "rotate_old_rejected": True,
        "revoke_rejected": True,
        "sealed_envelope_removed": not envelope.exists(),
        "secret_values_recorded": False,
        "password_hashes_recorded": False,
    }
    result = {**core, "evidence_sha256": _sha(core)}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--config", type=Path, required=True)
    generate_parser.add_argument("--acceptance-credential-service")
    seal_parser = subparsers.add_parser("seal")
    seal_parser.add_argument("--envelope", type=Path, required=True)
    provision_parser = subparsers.add_parser("provision")
    provision_parser.add_argument("--config", type=Path, required=True)
    provision_parser.add_argument("--envelope", type=Path, required=True)
    provision_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.action == "generate":
        return generate(
            args.config,
            acceptance_credential_service=args.acceptance_credential_service,
        )
    if args.action == "seal":
        return seal(args.envelope)
    return provision(args.config, args.envelope, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
