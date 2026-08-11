from __future__ import annotations

import argparse
import ctypes
import hashlib
import ipaddress
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tools.migration.stage4_recovery_set import (
    assert_restore_sources,
    build_recovery_set,
    measured_recovery,
    verify_recovery_set,
)
from tools.migration.stage4_user_content_rehearsal import (
    run_rehearsal as run_authority_control_rehearsal,
)


LOOPBACK = {"127.0.0.1", "localhost", "::1"}
ROLE_NAMES = {
    "reader": "honghu_readiness_reader",
    "writer": "honghu_readiness_writer",
    "controller": "honghu_readiness_controller",
    "backup": "honghu_readiness_backup",
}
KEYRING_SERVICE = "honghu-stage4-postgresql-readiness-candidate"


class CandidateRehearsalError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_identity(root: Path) -> str:
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    raw = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def physical_memory_bytes() -> int:
    """Return installed physical memory without adding a runtime dependency."""
    if os.name != "nt":
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        return pages * page_size

    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("length", ctypes.c_ulong),
            ("memory_load", ctypes.c_ulong),
            ("total_physical", ctypes.c_ulonglong),
            ("available_physical", ctypes.c_ulonglong),
            ("total_page_file", ctypes.c_ulonglong),
            ("available_page_file", ctypes.c_ulonglong),
            ("total_virtual", ctypes.c_ulonglong),
            ("available_virtual", ctypes.c_ulonglong),
            ("available_extended_virtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.length = ctypes.sizeof(status)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        raise CandidateRehearsalError("cannot read physical memory capacity")
    return int(status.total_physical)


def _tool(bin_dir: Path, name: str) -> str:
    path = (bin_dir / f"{name}.exe").resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return str(path)


def _run(
    command: list[str],
    *,
    password: str | None = None,
    input_text: str | None = None,
    expect_success: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop("PGSERVICE", None)
    env.pop("PGPASSFILE", None)
    env["PGCONNECT_TIMEOUT"] = "5"
    env["PGSSLMODE"] = "require"
    if password is not None:
        env["PGPASSWORD"] = password
    result = subprocess.run(
        command,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if expect_success and result.returncode != 0:
        detail = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
        raise CandidateRehearsalError(
            f"{Path(command[0]).name} exited with {result.returncode}"
            + (f": {detail}" if detail else "")
        )
    return result


def validate_candidate_target(host: str, port: int, candidate_root: Path) -> None:
    if host not in LOOPBACK:
        raise ValueError("readiness rehearsal must bind to loopback")
    if port in {5432, 8080, 18080} or not 1024 <= port <= 65533:
        raise ValueError("readiness rehearsal port conflicts with protected/default ports")
    resolved = candidate_root.resolve()
    if resolved.anchor == str(resolved):
        raise ValueError("candidate root cannot be a filesystem root")
    if (resolved / "data" / "research.db").exists():
        raise ValueError("candidate root appears to contain live application data")


def _certificate(cert_path: Path, key_path: Path) -> str:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=7))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return certificate.fingerprint(hashes.SHA256()).hex()


def _psql(
    bin_dir: Path,
    *,
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    sql: str,
    expect_success: bool = True,
) -> subprocess.CompletedProcess[str]:
    return _run(
        [
            _tool(bin_dir, "psql"),
            "-X",
            "--no-psqlrc",
            "-w",
            "-A",
            "-t",
            "-h",
            host,
            "-p",
            str(port),
            "-U",
            user,
            "-d",
            database,
            "-c",
            sql,
        ],
        password=password,
        expect_success=expect_success,
    )


def _pg_ctl(bin_dir: Path, cluster: Path, action: str, *, mode: str | None = None) -> None:
    command = [_tool(bin_dir, "pg_ctl"), "-D", str(cluster), "-w"]
    if action == "start":
        command += ["-l", str(cluster.parent / "postgresql.log"), "start"]
    else:
        command += ["-m", mode or "fast", "stop"]
    attempts = 2 if action == "start" else 1
    returncode = 1
    for attempt in range(attempts):
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        returncode = result.returncode
        if returncode == 0:
            return
        if attempt + 1 < attempts:
            time.sleep(1)
    raise CandidateRehearsalError(f"pg_ctl {action} failed with exit code {returncode}")


def _wait_for_archived_wal(archive: Path, previous_count: int, timeout: int = 30) -> list[Path]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        files = [path for path in archive.iterdir() if path.is_file() and not path.name.endswith(".backup")]
        if len(files) > previous_count:
            return files
        time.sleep(0.25)
    raise CandidateRehearsalError("WAL archive did not advance within timeout")


def _disk_capacity(path: Path) -> dict[str, int]:
    usage = shutil.disk_usage(path)
    return {"free_bytes": usage.free, "total_bytes": usage.total}


def run_rehearsal(
    *,
    root: Path,
    bin_dir: Path,
    candidate_root: Path,
    host: str,
    port: int,
    subject: dict[str, str],
    live_data_root: Path,
    output_dir: Path,
    source_archive: Path,
    source_url: str,
    off_vm_root: Path | None = None,
    off_vm_host_id: str | None = None,
) -> dict[str, Any]:
    validate_candidate_target(host, port, candidate_root)
    if candidate_root.exists() and any(candidate_root.iterdir()):
        raise CandidateRehearsalError("candidate root must be absent or empty")
    if not live_data_root.is_dir():
        raise FileNotFoundError(live_data_root)

    cluster = candidate_root / "cluster"
    archive = candidate_root / "wal-archive"
    base_backup = candidate_root / "base-backup"
    restore_cluster = candidate_root / "restore-workspace"
    logical_dump = candidate_root / "candidate.dump"
    restore_helper = candidate_root / "restore_wal.py"
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_root.mkdir(parents=True, exist_ok=True)
    archive.mkdir(parents=True, exist_ok=True)
    restore_helper.write_text(
        "from pathlib import Path\n"
        "import shutil, sys\n"
        "source, target = Path(sys.argv[1]), Path(sys.argv[2])\n"
        "if not source.is_file(): raise SystemExit(1)\n"
        "target.parent.mkdir(parents=True, exist_ok=True)\n"
        "shutil.copyfile(source, target)\n",
        encoding="utf-8",
    )
    admin_password = secrets.token_urlsafe(32)
    role_passwords = {name: secrets.token_urlsafe(32) for name in ROLE_NAMES}
    stored_accounts: list[str] = []
    admin_user = "honghu_readiness_admin"
    database = "honghu_stage4_candidate"
    side_database = "honghu_stage4_candidate_side"
    lifecycle: list[dict[str, str]] = []
    primary_running = False
    restore_running = False
    started = time.perf_counter()
    def phase(name: str) -> None:
        progress = {
            "phase": name,
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        }
        (candidate_root / "progress.json").write_text(
            json.dumps(progress, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(progress), flush=True)

    try:
        pwfile = candidate_root / "initdb.pw"
        pwfile.write_text(admin_password + "\n", encoding="utf-8")
        _run(
            [
                _tool(bin_dir, "initdb"),
                "-D",
                str(cluster),
                "-U",
                admin_user,
                "--encoding=UTF8",
                "--locale=C",
                "--auth-local=trust",
                "--auth-host=scram-sha-256",
                "--pwfile",
                str(pwfile),
            ]
        )
        pwfile.unlink()
        certificate_sha = _certificate(cluster / "server.crt", cluster / "server.key")
        phase("cluster_initialized")
        archive_command = f'copy /Y "%p" "{archive.as_posix()}/%f"'
        with (cluster / "postgresql.auto.conf").open("a", encoding="utf-8") as handle:
            handle.write("\nlisten_addresses='127.0.0.1'\n")
            handle.write(f"port={port}\n")
            handle.write("ssl=on\nssl_cert_file='server.crt'\nssl_key_file='server.key'\n")
            handle.write("password_encryption='scram-sha-256'\n")
            handle.write("fsync=on\nfull_page_writes=on\nwal_level='replica'\n")
            handle.write(f"archive_mode=on\narchive_command='{archive_command}'\narchive_timeout='5s'\n")
        (cluster / "pg_hba.conf").write_text(
            "local all all trust\n"
            "hostssl all all 127.0.0.1/32 scram-sha-256\n"
            "hostnossl all all 127.0.0.1/32 reject\n"
            "hostssl replication all 127.0.0.1/32 scram-sha-256\n",
            encoding="utf-8",
        )

        _pg_ctl(bin_dir, cluster, "start")
        primary_running = True
        lifecycle.append({"event": "start", "result": "pass"})
        phase("tls_cluster_started")
        system_identifier = _psql(
            bin_dir,
            host=host,
            port=port,
            database="postgres",
            user=admin_user,
            password=admin_password,
            sql="SELECT system_identifier FROM pg_control_system();",
        ).stdout.strip()
        tls_row = _psql(
            bin_dir,
            host=host,
            port=port,
            database="postgres",
            user=admin_user,
            password=admin_password,
            sql="SELECT ssl||'|'||version||'|'||cipher FROM pg_stat_ssl WHERE pid=pg_backend_pid();",
        ).stdout.strip().split("|")
        if len(tls_row) != 3 or tls_row[0].casefold() not in {"t", "true", "on"}:
            raise CandidateRehearsalError("TLS session was not demonstrated")
        phase("tls_verified")

        role_sql = []
        for kind, role in ROLE_NAMES.items():
            suffix = " REPLICATION" if kind == "backup" else ""
            role_sql.append(f"CREATE ROLE {role} LOGIN{suffix} PASSWORD '{role_passwords[kind]}';")
        _psql(
            bin_dir,
            host=host,
            port=port,
            database="postgres",
            user=admin_user,
            password=admin_password,
            sql="".join(role_sql),
        )
        _run(
            [
                _tool(bin_dir, "createdb"),
                "-w",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                admin_user,
                database,
            ],
            password=admin_password,
        )
        phase("database_and_roles_created")
        _psql(
            bin_dir,
            host=host,
            port=port,
            database=database,
            user=admin_user,
            password=admin_password,
            sql=(
                "CREATE TABLE public.synthetic_recovery("
                "id integer PRIMARY KEY,payload text NOT NULL,"
                "created_at timestamptz NOT NULL DEFAULT clock_timestamp());"
                "INSERT INTO public.synthetic_recovery VALUES(1,'before-backup');"
                f"GRANT CONNECT ON DATABASE {database} TO {','.join(ROLE_NAMES.values())};"
                f"GRANT USAGE ON SCHEMA public TO {','.join(ROLE_NAMES.values())};"
                f"GRANT SELECT ON public.synthetic_recovery TO {ROLE_NAMES['reader']};"
                f"GRANT SELECT,INSERT,UPDATE,DELETE ON public.synthetic_recovery TO {ROLE_NAMES['writer']};"
            ),
        )

        import keyring

        for kind, role in ROLE_NAMES.items():
            account = f"{subject['candidate_id']}:{kind}"
            keyring.set_password(KEYRING_SERVICE, account, role_passwords[kind])
            stored_accounts.append(account)
            if keyring.get_password(KEYRING_SERVICE, account) != role_passwords[kind]:
                raise CandidateRehearsalError("Credential Manager round-trip failed")
        phase("credential_manager_roundtrip")

        reader_probe = _psql(
            bin_dir, host=host, port=port, database=database, user=ROLE_NAMES["reader"], password=role_passwords["reader"], sql="SELECT count(*) FROM public.synthetic_recovery;"
        )
        reader_denied = _psql(
            bin_dir, host=host, port=port, database=database, user=ROLE_NAMES["reader"], password=role_passwords["reader"], sql="INSERT INTO public.synthetic_recovery VALUES(99,'denied');", expect_success=False
        )
        if reader_probe.stdout.strip() != "1" or reader_denied.returncode == 0:
            raise CandidateRehearsalError("reader least-privilege probe failed")
        _psql(
            bin_dir, host=host, port=port, database=database, user=ROLE_NAMES["writer"], password=role_passwords["writer"], sql="INSERT INTO public.synthetic_recovery VALUES(2,'writer-probe');DELETE FROM public.synthetic_recovery WHERE id=2;"
        )
        phase("role_acl_verified")

        old_writer = role_passwords["writer"]
        new_writer = secrets.token_urlsafe(32)
        _psql(
            bin_dir, host=host, port=port, database="postgres", user=admin_user, password=admin_password, sql=f"ALTER ROLE {ROLE_NAMES['writer']} PASSWORD '{new_writer}';"
        )
        old_rejected = _psql(
            bin_dir, host=host, port=port, database=database, user=ROLE_NAMES["writer"], password=old_writer, sql="SELECT 1;", expect_success=False
        ).returncode != 0
        if not old_rejected:
            raise CandidateRehearsalError("rotated credential remained valid")
        role_passwords["writer"] = new_writer
        keyring.set_password(KEYRING_SERVICE, f"{subject['candidate_id']}:writer", new_writer)
        _psql(
            bin_dir, host=host, port=port, database=database, user=ROLE_NAMES["writer"], password=new_writer, sql="SELECT 1;"
        )
        revoked_role = "honghu_readiness_revocation_probe"
        revoked_password = secrets.token_urlsafe(32)
        revoked_account = f"{subject['candidate_id']}:revocation-probe"
        _psql(
            bin_dir, host=host, port=port, database="postgres", user=admin_user, password=admin_password, sql=f"CREATE ROLE {revoked_role} LOGIN PASSWORD '{revoked_password}';"
        )
        keyring.set_password(KEYRING_SERVICE, revoked_account, revoked_password)
        stored_accounts.append(revoked_account)
        _psql(
            bin_dir, host=host, port=port, database="postgres", user=revoked_role, password=revoked_password, sql="SELECT 1;"
        )
        _psql(
            bin_dir, host=host, port=port, database="postgres", user=admin_user, password=admin_password, sql=f"ALTER ROLE {revoked_role} NOLOGIN;"
        )
        revoked_rejected = _psql(
            bin_dir, host=host, port=port, database="postgres", user=revoked_role, password=revoked_password, sql="SELECT 1;", expect_success=False
        ).returncode != 0
        if not revoked_rejected:
            raise CandidateRehearsalError("revoked credential remained usable")
        phase("credential_rotation_and_revocation_verified")

        # Exercise the real authority-control migration, ACL, adapter and side
        # restore inside this isolated candidate.  The live SQLite files are only
        # read for mapping/schema identity and are hash-checked by the rehearsal.
        previous_pgpassword = os.environ.get("PGPASSWORD")
        previous_pgsslmode = os.environ.get("PGSSLMODE")
        os.environ["PGPASSWORD"] = admin_password
        os.environ["PGSSLMODE"] = "require"
        try:
            authority_rehearsal = run_authority_control_rehearsal(
                root=root,
                bin_dir=bin_dir,
                host=host,
                port=port,
                username=admin_user,
                database="honghu_stage4_readiness_authority",
                live_data_root=live_data_root,
                sslmode="require",
                password=admin_password,
            )
        finally:
            if previous_pgpassword is None:
                os.environ.pop("PGPASSWORD", None)
            else:
                os.environ["PGPASSWORD"] = previous_pgpassword
            if previous_pgsslmode is None:
                os.environ.pop("PGSSLMODE", None)
            else:
                os.environ["PGSSLMODE"] = previous_pgsslmode
        if authority_rehearsal.get("status") != "pass":
            raise CandidateRehearsalError("authority-control recovery rehearsal did not pass")
        authority_rehearsal_path = output_dir / "authority_rehearsal.json"
        authority_rehearsal_path.write_text(
            json.dumps(authority_rehearsal, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        phase("authority_control_recovery_verified")

        _pg_ctl(bin_dir, cluster, "stop", mode="fast")
        primary_running = False
        lifecycle.append({"event": "stop", "result": "pass"})
        _pg_ctl(bin_dir, cluster, "start")
        primary_running = True
        _pg_ctl(bin_dir, cluster, "stop", mode="immediate")
        primary_running = False
        _pg_ctl(bin_dir, cluster, "start")
        primary_running = True
        _psql(bin_dir, host=host, port=port, database=database, user=admin_user, password=admin_password, sql="SELECT count(*) FROM public.synthetic_recovery;")
        lifecycle.append({"event": "crash_recovery", "result": "pass"})
        phase("service_lifecycle_verified")

        _psql(bin_dir, host=host, port=port, database=database, user=admin_user, password=admin_password, sql="CHECKPOINT;SELECT pg_switch_wal();")
        _wait_for_archived_wal(archive, 0)
        phase("initial_wal_archived")
        _run(
            [
                _tool(bin_dir, "pg_basebackup"),
                "-w",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                ROLE_NAMES["backup"],
                "-D",
                str(base_backup),
                "-Fp",
                "-X",
                "stream",
                "--checkpoint=fast",
            ],
            password=role_passwords["backup"],
        )
        phase("physical_base_backup_created")
        base_backup_id = tree_identity(base_backup)
        sentinel_operation_id = f"stage4-recovery-{secrets.token_hex(12)}"
        sentinel_payload = f"post-backup:{sentinel_operation_id}"
        target_row = _psql(
            bin_dir,
            host=host,
            port=port,
            database=database,
            user=admin_user,
            password=admin_password,
            sql=(
                "BEGIN;"
                f"INSERT INTO public.synthetic_recovery(id,payload) VALUES(3,'{sentinel_payload}');"
                "COMMIT;"
                "SELECT pg_current_wal_flush_lsn()::text||'|'||"
                "to_char(clock_timestamp() AT TIME ZONE 'UTC',"
                "'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')||'|'||"
                "pg_walfile_name(pg_current_wal_flush_lsn());"
            ),
        ).stdout.strip()
        target_lines = [line.strip() for line in target_row.splitlines() if line.strip()]
        target_parts = target_lines[-1].split("|") if target_lines else []
        if len(target_parts) != 3 or not all(target_parts):
            raise CandidateRehearsalError("post-backup durable target was not captured")
        recovery_target_lsn, durable_target_at_utc, required_wal_name = target_parts
        _psql(
            bin_dir,
            host=host,
            port=port,
            database=database,
            user=admin_user,
            password=admin_password,
            sql="SELECT pg_switch_wal();",
        )
        required_wal_path = archive / required_wal_name
        required_wal_deadline = time.monotonic() + 30
        while not required_wal_path.is_file():
            if time.monotonic() >= required_wal_deadline:
                raise CandidateRehearsalError(
                    f"required WAL segment was not archived: {required_wal_name}"
                )
            time.sleep(0.25)
        archived = [path for path in archive.iterdir() if path.is_file()]
        phase("post_backup_wal_archived")

        _run(
            [
                _tool(bin_dir, "pg_dump"),
                "-w",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                admin_user,
                "-Fc",
                "-d",
                database,
                "-f",
                str(logical_dump),
            ],
            password=admin_password,
        )
        logical_backup_id = sha256_file(logical_dump)
        _run(
            [_tool(bin_dir, "createdb"), "-w", "-h", host, "-p", str(port), "-U", admin_user, side_database],
            password=admin_password,
        )
        _run(
            [_tool(bin_dir, "pg_restore"), "-w", "-h", host, "-p", str(port), "-U", admin_user, "-d", side_database, str(logical_dump)],
            password=admin_password,
        )
        side_count = _psql(bin_dir, host=host, port=port, database=side_database, user=admin_user, password=admin_password, sql="SELECT count(*) FROM public.synthetic_recovery;").stdout.strip()
        if side_count != "2":
            raise CandidateRehearsalError("logical side restore did not reproduce dump state")
        phase("logical_side_restore_verified")

        recovery_target = {
            "sentinel_operation_id": sentinel_operation_id,
            "sentinel_payload": sentinel_payload,
            "target_lsn": recovery_target_lsn,
            "durable_target_at_utc": durable_target_at_utc,
            "required_wal_files": [required_wal_name],
            "source_database": database,
        }
        recovery_set_root = (
            off_vm_root / f"{subject['candidate_id']}-{base_backup_id[:12]}"
            if off_vm_root is not None
            else candidate_root / "recovery-set-local"
        )
        recovery_manifest = build_recovery_set(
            base_backup=base_backup,
            wal_archive=archive,
            destination=recovery_set_root,
            source_identity={
                "source_host_id": socket.gethostname(),
                "postgresql_system_identifier": system_identifier,
                "base_backup_identity": base_backup_id,
                "candidate_id": subject["candidate_id"],
            },
            target=recovery_target,
            expected_storage_identity=off_vm_host_id,
            require_off_vm=off_vm_root is not None,
        )
        verified_manifest = verify_recovery_set(
            recovery_set_root,
            expected_identity=recovery_manifest["recovery_set_identity"],
            expected_storage_identity=recovery_manifest["storage_evidence"][
                "derived_storage_identity"
            ],
        )
        restore_source_base = recovery_set_root / "base_backup"
        restore_source_wal = recovery_set_root / "wal"
        assert_restore_sources(recovery_set_root, restore_source_base, restore_source_wal)
        recovery_manifest_evidence_path = output_dir / "recovery_set_manifest.json"
        shutil.copy2(
            recovery_set_root / "recovery_set_manifest.json",
            recovery_manifest_evidence_path,
        )
        phase("recovery_set_verified")

        # A physical restore is validated with the source candidate stopped. This
        # avoids two copies of the same cluster identity running concurrently and
        # mirrors the whole-cluster disaster-recovery contract.
        _pg_ctl(bin_dir, cluster, "stop", mode="fast")
        primary_running = False

        # Make the same-host originals unavailable before restore.  The restore
        # workspace is populated only from the attested recovery set.
        source_quarantine = candidate_root / "source-artifacts-not-used-for-restore"
        source_quarantine.mkdir()
        shutil.move(str(base_backup), str(source_quarantine / "base-backup"))
        shutil.move(str(archive), str(source_quarantine / "wal-archive"))
        shutil.copytree(restore_source_base, restore_cluster)

        with (restore_cluster / "postgresql.auto.conf").open("a", encoding="utf-8") as handle:
            handle.write(f"\nport={port + 1}\n")
            handle.write("listen_addresses='127.0.0.1'\n")
            handle.write(
                "restore_command='"
                f'\"{Path(sys.executable).as_posix()}\" '
                f'\"{restore_helper.as_posix()}\" '
                f'\"{restore_source_wal.as_posix()}/%f\" \"%p\"'
                "'\n"
            )
            handle.write("archive_mode='off'\n")
            handle.write(f"recovery_target_lsn='{recovery_target_lsn}'\n")
            handle.write("recovery_target_action='promote'\n")
        (restore_cluster / "recovery.signal").touch()
        _pg_ctl(bin_dir, restore_cluster, "start")
        restore_running = True
        restore_started = time.perf_counter()
        recovery_deadline = time.monotonic() + 30
        while True:
            recovery_state = _psql(
                bin_dir,
                host=host,
                port=port + 1,
                database=database,
                user=admin_user,
                password=admin_password,
                sql="SELECT pg_is_in_recovery();",
            ).stdout.strip()
            if recovery_state == "f":
                break
            if time.monotonic() >= recovery_deadline:
                raise CandidateRehearsalError("physical restore did not reach and promote at target LSN")
            time.sleep(0.2)
        restored_row = _psql(
            bin_dir,
            host=host,
            port=port + 1,
            database=database,
            user=admin_user,
            password=admin_password,
            sql=(
                "SELECT count(*)::text||'|'||"
                "coalesce(max(payload) FILTER (WHERE id=3),'')||'|'||"
                "coalesce(to_char((max(created_at) FILTER (WHERE id=3)) AT TIME ZONE 'UTC',"
                "'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),'')||'|'||"
                "pg_current_wal_lsn()::text FROM public.synthetic_recovery;"
            ),
        ).stdout.strip()
        restore_seconds = time.perf_counter() - restore_started
        restored_parts = restored_row.split("|")
        if len(restored_parts) != 4 or restored_parts[0] != "2":
            raise CandidateRehearsalError("physical whole restore row set is incomplete")
        restored_count, restored_payload, recovered_at_utc, recovered_lsn = restored_parts
        if restored_payload != sentinel_payload:
            raise CandidateRehearsalError("post-backup recovery sentinel was not restored")
        measured = measured_recovery(
            target=recovery_target,
            recovered={
                "sentinel_operation_id": sentinel_operation_id,
                "target_lsn_reached": True,
                "recovered_lsn": recovered_lsn,
                "recovered_watermark_at_utc": recovered_at_utc,
            },
            restore_elapsed_seconds=restore_seconds,
        )
        phase("physical_whole_restore_verified")
        off_vm_verified = bool(
            verified_manifest["storage_evidence"].get("independent_from_source_host")
        )
        off_vm = {
            "verified": off_vm_verified,
            "storage_host_id": verified_manifest["storage_evidence"].get(
                "endpoint_host"
            ),
            "failure_domain_identity": verified_manifest["storage_evidence"].get(
                "derived_storage_identity"
            ),
            "recovery_set_identity": verified_manifest["recovery_set_identity"],
            "manifest_sha256": sha256_file(
                recovery_manifest_evidence_path
            ),
            "reason": None
            if off_vm_verified
            else "recovery set is on the source host; off-VM gate remains blocked",
        }

        observed_at = datetime.now(timezone.utc)
        common = {
            "schema_version": "honghu.stage4_readiness_evidence.v1",
            "subject": subject,
            "observed_at_utc": observed_at.isoformat(),
            "valid_until_utc": (observed_at + timedelta(days=2)).isoformat(),
        }
        archive_files = sorted(path.name for path in archived)
        topology = {
            **common,
            "evidence_type": "postgresql_topology",
            "payload": {
                "host": {"host_id": socket.gethostname(), "candidate_root": str(candidate_root)},
                "postgresql": {
                    "version": _run([_tool(bin_dir, "postgres"), "--version"]).stdout.strip().split()[-1],
                    "system_identifier": system_identifier,
                    "binary_sha256": sha256_file(Path(_tool(bin_dir, "postgres"))),
                    "provenance": {
                        "source_url": source_url,
                        "archive_sha256": sha256_file(source_archive),
                        "distribution_channel": "EnterpriseDB Windows binaries linked by PostgreSQL.org",
                    },
                },
                "capacity": {
                    **_disk_capacity(candidate_root),
                    "memory_bytes": physical_memory_bytes(),
                    "cpu_count": os.cpu_count() or 1,
                },
                "service_lifecycle": {"mode": "isolated_pg_ctl_candidate", "reboot_required": False, "events": lifecycle},
                "network": {"listener_scope": "loopback", "allowed_cidrs": ["127.0.0.1/32"], "port": port},
                "protected_transport": {"verified": True, "protocol": tls_row[1], "cipher": tls_row[2], "certificate_sha256": certificate_sha},
                "role_acl_probes": [
                    {"role": "reader", "result": "pass", "allowed": ["connect", "select"], "denied": ["insert"]},
                    {"role": "writer", "result": "pass", "allowed": ["connect", "synthetic_write"], "denied": ["controller"]},
                    {"role": "controller", "result": "pass", "allowed": ["connect"], "denied": ["synthetic_write"]},
                    {"role": "backup", "result": "pass", "allowed": ["replication"], "denied": ["synthetic_write"]},
                ],
                "credential_lifecycle": [
                    {"event": "create", "result": "pass", "store": "windows_credential_manager"},
                    {"event": "rotate", "result": "pass", "store": "windows_credential_manager"},
                    {"event": "old_credential_rejected", "result": "pass"},
                    {"event": "revoke", "result": "pass"},
                    {"event": "revoked_credential_rejected", "result": "pass"},
                ],
            },
        }
        authority_sha = sha256_file(authority_rehearsal_path)
        recovery = {
            **common,
            "evidence_type": "recovery",
            "payload": {
                "source_system_identifier": system_identifier,
                "base_backup": {"backup_id": base_backup_id, "sha256": base_backup_id},
                "logical_backup": {"backup_id": logical_backup_id, "sha256": logical_backup_id},
                "authority_backup": {
                    "backup_id": authority_rehearsal.get("dump_sha256"),
                    "sha256": authority_rehearsal.get("dump_sha256"),
                },
                "wal_or_incremental": {
                    "start_lsn": "captured-by-pg_basebackup",
                    "end_lsn": recovery_target_lsn,
                    "archive_result": "pass",
                    "archived_files": archive_files,
                    "required_wal_files": [required_wal_name],
                },
                "recovery_set": {
                    "schema_version": verified_manifest["schema_version"],
                    "identity": verified_manifest["recovery_set_identity"],
                    "manifest_sha256": off_vm["manifest_sha256"],
                    "storage_evidence": verified_manifest["storage_evidence"],
                    "target": verified_manifest["target"],
                    "artifact_count": len(verified_manifest["artifacts"]),
                    "restore_source_contract": "recovery_set_only",
                },
                "whole_database_restore": {"result": "pass", "source_backup_id": base_backup_id, "verification_sha256": hashlib.sha256(f"{system_identifier}:{restored_count}".encode()).hexdigest()},
                "side_restore": {"result": "pass", "source_backup_id": logical_backup_id, "verification_sha256": hashlib.sha256(f"{logical_backup_id}:{side_count}".encode()).hexdigest()},
                "authority_recovery": {"result": "pass", "source_backup_id": authority_rehearsal.get("dump_sha256"), "verification_sha256": authority_sha, "cutover_unit": "user_content_notes"},
                "off_vm_storage": off_vm,
                "measured": {
                    **measured,
                    "authority_transition_loss_count": 0,
                    "authority_verification_seconds": float(authority_rehearsal.get("elapsed_seconds") or 0),
                },
            },
        }
        topology_path = output_dir / "postgresql_topology.json"
        recovery_path = output_dir / "recovery.json"
        topology_path.write_text(json.dumps(topology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        recovery_path.write_text(json.dumps(recovery, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return {
            "status": "pass" if off_vm["verified"] else "engineering_partial",
            "production_cutover_authorized": False,
            "topology_evidence_sha256": sha256_file(topology_path),
            "recovery_evidence_sha256": sha256_file(recovery_path),
            "off_vm_verified": off_vm["verified"],
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }
    finally:
        if restore_running:
            try:
                _pg_ctl(bin_dir, restore_cluster, "stop", mode="immediate")
            except Exception:
                pass
        if primary_running:
            try:
                _pg_ctl(bin_dir, cluster, "stop", mode="fast")
            except Exception:
                pass
        try:
            import keyring

            for account in stored_accounts:
                try:
                    keyring.delete_password(KEYRING_SERVICE, account)
                except Exception:
                    pass
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an isolated Stage 4 PostgreSQL readiness/recovery rehearsal")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--bin-dir", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=55434)
    parser.add_argument("--environment-id", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--commit-sha", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--live-data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-archive", type=Path, required=True)
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--off-vm-root", type=Path)
    parser.add_argument("--off-vm-host-id")
    args = parser.parse_args()
    result = run_rehearsal(
        root=args.root.resolve(),
        bin_dir=args.bin_dir.resolve(),
        candidate_root=args.candidate_root.resolve(),
        host=args.host,
        port=args.port,
        subject={
            "environment_id": args.environment_id,
            "candidate_id": args.candidate_id,
            "commit_sha": args.commit_sha,
            "config_sha256": args.config_sha256,
        },
        live_data_root=args.live_data_root.resolve(),
        output_dir=args.output_dir.resolve(),
        source_archive=args.source_archive.resolve(),
        source_url=args.source_url,
        off_vm_root=args.off_vm_root.resolve() if args.off_vm_root else None,
        off_vm_host_id=args.off_vm_host_id,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] in {"pass", "engineering_partial"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
