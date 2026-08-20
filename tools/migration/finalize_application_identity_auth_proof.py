from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from tools.data_platform.postgres_runtime import (
    build_catalog_connection_factory,
    credential_manager_password,
    load_postgres_runtime_catalog,
)


def finalize(
    runtime_path: Path,
    security_config_path: Path,
    *,
    reason: str = "controlled application-identity deployment",
) -> None:
    security = json.loads(security_config_path.read_text(encoding="utf-8-sig"))
    if security.get("authentication_proof_secret_version") != 1:
        raise RuntimeError("authentication-proof secret version is unsupported")
    proof = credential_manager_password(
        str(security.get("authentication_proof_secret_service") or ""),
        str(security.get("authentication_proof_secret_account") or ""),
    )
    if not proof or len(proof) < 32:
        raise RuntimeError("authentication-proof secret is unavailable")
    proof_sha = hashlib.sha256(proof.encode("utf-8")).hexdigest()
    factory = build_catalog_connection_factory(
        load_postgres_runtime_catalog(runtime_path), role="migration"
    )
    with factory() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT application_identity.local_set_authentication_proof_v1(%s,%s,%s)",
                (proof_sha, reason, 1),
            )
            row = cursor.fetchone()
            if row is None or row[0] is not True:
                raise RuntimeError("authentication-proof finalization failed")
    print("application authentication proof finalized; no secret value was printed")


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize the VM-local application login proof")
    parser.add_argument("--runtime", required=True, type=Path)
    parser.add_argument("--security-config", required=True, type=Path)
    parser.add_argument(
        "--reason", default="controlled application-identity deployment"
    )
    args = parser.parse_args()
    finalize(
        args.runtime.resolve(),
        args.security_config.resolve(),
        reason=str(args.reason),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
