from __future__ import annotations

"""Transfer only reviewed task-role credentials into a service account vault.

The temporary file is encrypted with Windows DPAPI LocalMachine and must also
be protected by a service-account-only NTFS ACL.  No password is printed or
written in plaintext.  Import deletes the encrypted transfer after a verified
WinVault round trip.
"""

import argparse
import json
from pathlib import Path


TASK_ROLES = {
    "reader",
    "writer_operations_governance",
    "writer_dynamic_intelligence",
    "writer_sentiment_analytics",
    "writer_financial_data",
}
CRYPTPROTECT_LOCAL_MACHINE = 0x4


def _winvault():
    import keyring
    from keyring.backends.Windows import WinVaultKeyring

    keyring.set_keyring(WinVaultKeyring())
    return keyring


def export_transfer(catalog_path: Path, output: Path) -> dict[str, object]:
    from tools.data_platform.postgres_runtime import load_postgres_runtime_catalog
    import win32crypt

    catalog = load_postgres_runtime_catalog(catalog_path)
    keyring = _winvault()
    entries = []
    for name in sorted(TASK_ROLES):
        role = catalog.role(name)
        password = keyring.get_password(role.credential_service, role.credential_account)
        if not password:
            raise RuntimeError(f"task role credential is unavailable: {name}")
        entries.append({
            "role": name,
            "service": role.credential_service,
            "account": role.credential_account,
            "password": password,
        })
    raw = json.dumps({"entries": entries}, separators=(",", ":")).encode("utf-8")
    encrypted = win32crypt.CryptProtectData(
        raw, "honghu-stage5-task-credentials", None, None, None,
        CRYPTPROTECT_LOCAL_MACHINE,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encrypted)
    return {"action": "export", "role_count": len(entries), "encrypted": True}


def import_transfer(source: Path, catalog_path: Path) -> dict[str, object]:
    import win32crypt

    raw = win32crypt.CryptUnprotectData(
        source.read_bytes(), None, None, None, CRYPTPROTECT_LOCAL_MACHINE,
    )[1]
    payload = json.loads(raw.decode("utf-8"))
    entries = list(payload.get("entries") or ())
    roles = {str(item.get("role") or "") for item in entries}
    if roles != TASK_ROLES:
        raise RuntimeError("credential transfer role set is not the reviewed task role set")
    keyring = _winvault()
    for item in entries:
        service = str(item["service"])
        account = str(item["account"])
        password = str(item["password"])
        keyring.set_password(service, account, password)
        if keyring.get_password(service, account) != password:
            raise RuntimeError(f"service account vault verification failed: {item['role']}")
    from tools.data_platform.postgres_runtime import (
        build_catalog_connection_factory,
        load_postgres_runtime_catalog,
    )

    catalog = load_postgres_runtime_catalog(catalog_path)
    for role_name in sorted(TASK_ROLES):
        connection = build_catalog_connection_factory(catalog, role=role_name)()
        try:
            if int(connection.execute("SELECT 1").fetchone()[0]) != 1:
                raise RuntimeError(f"service account PostgreSQL probe failed: {role_name}")
        finally:
            connection.close()
    source.unlink()
    return {
        "action": "import", "role_count": len(entries),
        "verified": True, "postgresql_probes": len(TASK_ROLES),
        "source_deleted": True,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export")
    export.add_argument("--catalog", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    import_ = sub.add_parser("import")
    import_.add_argument("--source", type=Path, required=True)
    import_.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args(argv)
    result = (
        export_transfer(args.catalog, args.output)
        if args.command == "export"
        else import_transfer(args.source, args.catalog)
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
