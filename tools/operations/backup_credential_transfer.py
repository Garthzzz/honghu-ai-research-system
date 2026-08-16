from __future__ import annotations

"""Move only the PostgreSQL backup-role secret into the backup runner vault."""

import argparse
import json
from pathlib import Path


ROLE = "backup"
CRYPTPROTECT_LOCAL_MACHINE = 0x4


def _winvault():
    import keyring
    from keyring.backends.Windows import WinVaultKeyring

    keyring.set_keyring(WinVaultKeyring())
    return keyring


def export_transfer(catalog_path: Path, output: Path) -> dict[str, object]:
    import win32crypt

    from tools.data_platform.postgres_runtime import load_postgres_runtime_catalog

    role = load_postgres_runtime_catalog(catalog_path).role(ROLE)
    vault = _winvault()
    password = vault.get_password(role.credential_service, role.credential_account)
    if not password:
        raise RuntimeError("backup role credential is unavailable")
    raw = json.dumps(
        {
            "role": ROLE,
            "service": role.credential_service,
            "account": role.credential_account,
            "password": password,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    encrypted = win32crypt.CryptProtectData(
        raw, "honghu-stage5-backup-credential", None, None, None,
        CRYPTPROTECT_LOCAL_MACHINE,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(encrypted)
    return {"action": "export", "role": ROLE, "encrypted": True, "secret_recorded": False}


def import_transfer(source: Path, catalog_path: Path) -> dict[str, object]:
    import win32crypt

    raw = win32crypt.CryptUnprotectData(
        source.read_bytes(), None, None, None, CRYPTPROTECT_LOCAL_MACHINE,
    )[1]
    payload = json.loads(raw.decode("utf-8"))
    if payload.get("role") != ROLE:
        raise RuntimeError("credential transfer is not the reviewed backup role")
    vault = _winvault()
    service = str(payload["service"])
    account = str(payload["account"])
    password = str(payload["password"])
    vault.set_password(service, account, password)
    if vault.get_password(service, account) != password:
        raise RuntimeError("backup service-account vault round trip failed")
    from tools.data_platform.postgres_runtime import (
        build_catalog_connection_factory,
        load_postgres_runtime_catalog,
    )

    catalog = load_postgres_runtime_catalog(catalog_path)
    connection = build_catalog_connection_factory(catalog, role=ROLE)()
    try:
        if int(connection.execute("SELECT 1").fetchone()[0]) != 1:
            raise RuntimeError("backup PostgreSQL connection probe failed")
    finally:
        connection.close()
    source.unlink()
    return {
        "action": "import",
        "role": ROLE,
        "verified": True,
        "source_deleted": True,
        "secret_recorded": False,
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
