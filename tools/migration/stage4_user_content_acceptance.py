from __future__ import annotations

"""Multi-client acceptance for the first production user-content cutover.

Credentials are loaded from Windows Credential Manager and are never accepted
on the command line or written to evidence.  ``first-mutation`` performs the
single browser/API mutation that advances S2 to S3.  ``stress`` runs only after
the S3 route has been reconciled and the exact release restarted.
"""

import argparse
import concurrent.futures
import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AcceptanceError(RuntimeError):
    pass


def _sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _credential(service: str, account: str) -> str:
    import keyring

    value = keyring.get_password(service, account)
    if not value:
        raise AcceptanceError("acceptance credential is unavailable")
    return value


def _login(client: Any, *, base_url: str, principal: str, password: str) -> str:
    session = client.get(f"{base_url}/api/user-content/session")
    session.raise_for_status()
    initial = session.json()
    if not initial.get("security_ready"):
        raise AcceptanceError("user-content security is not ready")
    response = client.post(
        f"{base_url}/api/user-content/login",
        json={"subject": principal, "password": password},
        headers={"X-CSRF-Token": str(initial["csrf_token"])},
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("principal") != principal:
        raise AcceptanceError("authenticated principal mismatch")
    return str(payload["csrf_token"])


def _put(
    client: Any,
    *,
    base_url: str,
    csrf: str,
    note_key: str,
    operation_id: str,
    content: str,
    expected_revision: int,
) -> dict[str, Any]:
    response = client.post(
        f"{base_url}/api/analyst_note",
        json={
            "note_key": note_key,
            "entity_type": "company",
            "entity_id": "330",
            "note_type": "stage4_acceptance",
            "title": "Stage 4 production acceptance",
            "content": content,
            "expected_revision": expected_revision,
        },
        headers={"X-CSRF-Token": csrf, "X-Idempotency-Key": operation_id},
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok"):
        raise AcceptanceError("analyst-note mutation did not succeed")
    return payload["note"]


def _delete(
    client: Any,
    *,
    base_url: str,
    csrf: str,
    note_key: str,
    operation_id: str,
    expected_revision: int,
) -> dict[str, Any]:
    response = client.request(
        "DELETE",
        f"{base_url}/api/analyst_note/key/{note_key}",
        json={"expected_revision": expected_revision},
        headers={"X-CSRF-Token": csrf, "X-Idempotency-Key": operation_id},
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("ok") or payload["note"].get("deleted") is not True:
        raise AcceptanceError("analyst-note soft delete did not succeed")
    return payload["note"]


def _health(client: Any, base_url: str, expected_commit: str, state: str) -> dict:
    response = client.get(f"{base_url}/api/health")
    response.raise_for_status()
    payload = response.json()
    user_content = payload.get("user_content") or {}
    if (
        not payload.get("ok")
        or payload.get("viewer_mode") != "production_postgresql"
        or user_content.get("authority_state") != state
        or user_content.get("backend") != "postgresql_production"
        or user_content.get("sqlite_writer_enabled") is not False
        or user_content.get("security_ready") is not True
    ):
        raise AcceptanceError("Viewer health is not bound to PostgreSQL authority")
    release_commit = ((payload.get("release") or {}).get("commit_sha")) or __import__("os").environ.get(
        "HONGHU_RELEASE_COMMIT"
    )
    # Older health schemas may not echo the release object.  The caller still
    # binds the tested launcher to the exact commit; if health exposes a commit,
    # it must agree.
    if release_commit and str(release_commit).lower() != expected_commit.lower():
        raise AcceptanceError("Viewer health commit mismatch")
    return payload


def first_mutation(args: argparse.Namespace) -> dict[str, Any]:
    import httpx

    password = _credential(args.credential_service, args.credential_account)
    note_key = f"stage4-acceptance:first:{uuid.uuid4().hex}"
    operation_id = f"stage4-first:{uuid.uuid4().hex}"
    with httpx.Client(verify=str(args.ca_certificate), timeout=15) as client:
        _health(client, args.base_url, args.expected_commit, "S2")
        csrf = _login(
            client,
            base_url=args.base_url,
            principal=args.principal,
            password=password,
        )
        note = _put(
            client,
            base_url=args.base_url,
            csrf=csrf,
            note_key=note_key,
            operation_id=operation_id,
            content="Stage 4 first formal PostgreSQL acceptance mutation",
            expected_revision=0,
        )
        replay = _put(
            client,
            base_url=args.base_url,
            csrf=csrf,
            note_key=note_key,
            operation_id=operation_id,
            content="Stage 4 first formal PostgreSQL acceptance mutation",
            expected_revision=0,
        )
    if note.get("revision") != replay.get("revision"):
        raise AcceptanceError("uncertain-response replay was not idempotent")
    core = {
        "schema_version": "honghu.user_content_first_mutation_acceptance.v1",
        "status": "pass",
        "tested_at_utc": datetime.now(timezone.utc).isoformat(),
        "client_identity": args.client_identity,
        "expected_commit": args.expected_commit,
        "note_key": note_key,
        "operation_id": operation_id,
        "revision": int(note["revision"]),
        "idempotent_replay": True,
        "credential_recorded": False,
    }
    return {**core, "evidence_sha256": _sha(core)}


def stress(args: argparse.Namespace) -> dict[str, Any]:
    import httpx

    password = _credential(args.credential_service, args.credential_account)
    started = time.monotonic()
    with httpx.Client(verify=str(args.ca_certificate), timeout=20) as control:
        _health(control, args.base_url, args.expected_commit, "S3")
        csrf = _login(
            control,
            base_url=args.base_url,
            principal=args.principal,
            password=password,
        )
        plain = control.post(
            args.http_base_url + "/api/analyst_note",
            json={},
            headers={"X-CSRF-Token": csrf, "X-Idempotency-Key": "must-not-write"},
        )
        if plain.status_code != 403:
            raise AcceptanceError("plaintext 8080 mutation was not rejected")

    prefix = f"stage4-acceptance:stress:{uuid.uuid4().hex}"

    def create(index: int) -> tuple[str, int]:
        key = f"{prefix}:{index}"
        op = f"{prefix}:create:{index}"
        with httpx.Client(verify=str(args.ca_certificate), timeout=20) as client:
            token = _login(
                client, base_url=args.base_url, principal=args.principal, password=password
            )
            note = _put(
                client,
                base_url=args.base_url,
                csrf=token,
                note_key=key,
                operation_id=op,
                content=f"concurrent acceptance note {index}",
                expected_revision=0,
            )
            return key, int(note["revision"])

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        created = list(pool.map(create, range(args.mutation_count)))

    with httpx.Client(verify=str(args.ca_certificate), timeout=20) as client:
        token = _login(
            client, base_url=args.base_url, principal=args.principal, password=password
        )
        listed = client.get(f"{args.base_url}/api/analyst_note/company/330")
        listed.raise_for_status()
        listed_keys = {item["note_key"] for item in listed.json().get("notes", [])}
        if any(key not in listed_keys for key, _ in created):
            raise AcceptanceError("concurrent writes are missing from list read")
        for index, (key, revision) in enumerate(created):
            _delete(
                client,
                base_url=args.base_url,
                csrf=token,
                note_key=key,
                operation_id=f"{prefix}:delete:{index}",
                expected_revision=revision,
            )
    elapsed = time.monotonic() - started
    core = {
        "schema_version": "honghu.user_content_multi_client_stress.v1",
        "status": "pass",
        "tested_at_utc": datetime.now(timezone.utc).isoformat(),
        "client_identity": args.client_identity,
        "expected_commit": args.expected_commit,
        "concurrency": args.concurrency,
        "created_count": len(created),
        "soft_deleted_count": len(created),
        "elapsed_seconds": round(elapsed, 6),
        "plaintext_mutation_rejected": True,
        "credential_recorded": False,
    }
    return {**core, "evidence_sha256": _sha(core)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("first-mutation", "stress"))
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--http-base-url", required=True)
    parser.add_argument("--ca-certificate", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--principal", required=True)
    parser.add_argument("--credential-service", required=True)
    parser.add_argument("--credential-account", required=True)
    parser.add_argument("--client-identity", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--mutation-count", type=int, default=32)
    args = parser.parse_args(argv)
    if not args.ca_certificate.is_file():
        raise AcceptanceError("Viewer CA certificate is missing")
    if not 1 <= args.concurrency <= 32 or not 1 <= args.mutation_count <= 200:
        raise AcceptanceError("stress bounds are outside the approved range")
    result = first_mutation(args) if args.mode == "first-mutation" else stress(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
