# Stage 4 Production PostgreSQL Execution Runbook

## Authorization and hard boundary

On 2026-08-12 the user authorized the `honghu-vm` SSH channel for Stage 4
production-readiness infrastructure and S1 preparation.  The verified remote
identity is `DESKTOP-VGD07J4\zhangzzVM`; the existing Viewer health endpoint on
port 8080 was healthy when the channel was admitted.  This authorization allows
installation of PostgreSQL infrastructure, migrations, non-formal staging,
reconciliation, backup/WAL/restore rehearsal and S1 authority preparation.

It does **not** authorize S2/S3, a production reader/writer route switch,
fencing the SQLite writer, formal PostgreSQL business mutations, dual/shadow
writes, silent fallback, changes to the 8080 Viewer, Scheduled Tasks or runner
placement.  Every executable gate must fail closed if the tracked route is not
S0/S1 + `sqlite_transition`.

## Exact execution package

The execution package is built only after the branch commit and required CI are
green.  It contains the exact clean checkout, the reviewed PostgreSQL 17.10
binary archive and a package manifest.  It contains no database, papers,
credentials, browser state, TLS private key, runtime evidence or user content.

The VM entry point is one elevated PowerShell invocation. It must be launched
from the approved principal's interactive VM desktop session: Windows OpenSSH
network logons on the current host cannot access that user's WinVault and are
therefore rejected by an early, reversible Credential Manager capability probe
before archive extraction or dependency installation.

```powershell
& '<PACKAGE>\repo\tools\migration\Stage4-Production-PostgreSQL-Bootstrap.ps1' `
  -CommitSha '<FULL_SHA>' `
  -RepoRoot '<PACKAGE>\repo' `
  -PostgreSQLArchive '<PACKAGE>\postgresql-17.10-windows-x64-binaries.zip' `
  -BootstrapPythonExe 'C:\ProgramData\miniconda3\envs\quant\python.exe' `
  -ProductionRoot 'C:\industry_demo' `
  -InstallRoot 'D:\honghu-postgresql'
```

The bootstrap verifies the archive/config/route/checkout identities, available
capacity and existing 8080 before creating infrastructure.  It uses loopback
ports 55440/55441 and never modifies port 8080.  Secrets are created on the VM
and written only to the invoking Windows principal's Credential Manager.
The keyring bridge is an explicit tracked deployment input, forces the Windows
WinVault backend and receives secrets only through stdin. The broad Git ignore
rule for credential-bearing paths remains unchanged; real credential material
is never placed in Git. Missing bridge files and unavailable WinVault sessions
fail closed with a specific diagnostic instead of running a long installation
and returning a generic credential error.

The Windows service is configured for automatic boot and is tested for normal
stop/start. PostgreSQL 17 `pg_ctl runservice` reports a crashed postmaster as a
cleanly stopped service on this host, so SCM failure actions are not represented
as automatic postmaster recovery. The bootstrap instead proves actual WAL crash
recovery by validating the postmaster/service process family, observing the
stopped service and released listener, explicitly starting the service, and
requiring a new postmaster identity plus a successful database probe. Runtime
monitoring or an operator must trigger that service start; this co-located
topology is not advertised as high availability.

## Failure and retry contract

Each fresh attempt owns an install identity containing launch ID, commit,
configuration and archive hashes.  On failure, automatic removal is permitted
only for the same incomplete launch after service data path, listener, tracked
authority and credential identities pass verification.  Its directory is moved
to a launch-specific quarantine with primary and cleanup evidence.  A foreign,
ambiguous or completed installation is never removed automatically.

Re-running an exact completed install performs read-only production verification
and does not reinstall.  An incomplete installation without a verified cleanup
identity remains fail closed for human inspection.

## S1 meaning

Generic unit staging means a consistent SQLite snapshot was loaded into
PostgreSQL migration tables and reconciled by row count and content identity. It
is `S1 preparation`, not a domain-schema cutover and not production authority.
Only `user_content_notes` has a domain-specific S1 promotion path.  That path
requires a hash-bound user approval for the final mapping and atomically records
S1, mappings, backfill, revision/audit and reconciliation while SQLite remains
the sole formal writer.

The migration role can call only the dedicated `ABSENT->S0` / `S0->S1`
preparation function.  It cannot call the generic production-authority
transition.  S2 remains behind the separately governed controller and a later
explicit authorization.

## Recovery and evidence

The local rehearsal creates a plain base backup, writes a non-business sentinel,
collects the complete required WAL interval using the cluster WAL segment size,
builds a hash manifest and restores only from that recovery set to a side
instance.  Whole-database, side-domain and authority-control recovery are
measured.  This is not off-VM evidence.

An independent failure-domain copy must contain the base backup, exact WAL set,
manifest and storage identity and must itself be used for restore.  A second
drive letter on the VM is not off-VM.  Until this proof exists, the final
readiness verifier remains blocked even if all local recovery checks pass.

Raw VM/database/recovery evidence, backups, credentials, private keys and full
mapping rows remain outside Git.  Git contains only code, tests, schemas,
redacted summaries and artifact identities.
