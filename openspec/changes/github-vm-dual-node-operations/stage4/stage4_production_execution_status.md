# Stage 4 Production Execution Status

This file is a tracked, redacted status summary.  It is not authority evidence.
The final evidence bundle remains Git-excluded and is verified by hash.

## Pre-bootstrap evidence retained as history

The observations in this section describe the pre-install/readiness snapshot
and are superseded for current runtime status by the 2026-08-13 section below.

- SSH channel `honghu-vm` was read-only verified as
  `DESKTOP-VGD07J4\zhangzzVM`; port 8080 health returned true.
- The VM execution principal has an elevated token, Python 3.10.20 is present,
  the approved PostgreSQL ports were unused, no `HonghuPostgreSQL17` service
  existed and more than the configured capacity envelope was free.
- Live SQLite schemas still match the frozen Stage 3 boundary.  Ordinary row
  growth is treated as a data watermark change, not schema/writer drift.
- All nine cutover units produced read-only manifests.  The largest unit,
  `sentiment_analytics`, contained 2,306,265 source rows at the observed
  snapshot.
- An isolated PostgreSQL 17.10 rehearsal proved exact load/reconciliation for
  user content, shared identity, operations governance and investment
  hypotheses.  A second investment snapshot detected one changed row through
  the temporary catch-up ledger.
- A non-production one-row user-content fixture proved mapping registration,
  backfill, revision/audit and S0-to-S1 atomicity.  The final state remained
  `S1/sqlite_transition` with no writer identity, epoch or formal commit.
- A least-privilege rehearsal proved the migration principal can prepare S0/S1
  but receives SQLSTATE 42501 for both its S2 attempt and the generic transition
  function.
- The admitted SSH channel is suitable for package transfer, identity checks,
  service observation and non-secret evidence collection.  A real VM probe
  proved that its non-interactive Windows logon cannot access the invoking
  user's WinVault (`WinError 1312`; native `cmdkey` also fails).  The exact
  bootstrap therefore performs this capability check before long installation
  work and requires one interactive VM launch for final credential injection.
- A clean-checkout failure also proved that the former keyring helper filename
  was excluded by the broad credential-path ignore rule.  The bridge is now a
  tracked deployment input, the bootstrap checks its presence explicitly and
  clean-checkout tests guard the closure.  No credential value or raw failure
  evidence is tracked.

## Human/external gates deliberately not self-approved

- final cutover-level approval of the identity mapping exceptions;
- repository production-authority governance or an approved exception;
- operator/approver separation and maintenance window;
- future application service-principal credential provisioning;
- independent off-VM recovery copy and restore proof;
- explicit authorization to enter S2.
- one interactive VM execution of the exact bootstrap under the approved
  credential-owner principal; SSH alone cannot satisfy this Windows boundary.

No item above may be converted to `pass` by a Boolean declaration or a fabricated
hash.  PostgreSQL installation and the final unit states are updated only from
the VM execution evidence after the exact commit is deployed.

## Durable production S0/S1 preparation on 2026-08-13

The earlier report-only success was invalid: a guard `SELECT` opened an outer
psycopg transaction, so the per-unit transaction blocks were savepoints and
closing the connection rolled every snapshot back.  Exact commit
`af510bce455a59c47a0007cfc54928951303b48b` corrected this by giving every unit
one top-level commit and then reopening a fresh database session for durable
verification.  Its push and pull-request required checks were green before the
VM run.

The approved interactive VM principal executed the exact package once against
the existing PostgreSQL 17.10 service.  The task completed successfully in
about eleven minutes.  All nine non-formal migration snapshots are now visible
from a fresh session with `lifecycle_state=reconciled` and matching source and
target identities:

| cutover unit | durable staging rows |
| --- | ---: |
| `user_content_notes` | 0 |
| `shared_identity` | 3,539 |
| `financial_data` | 53,569 |
| `research_publication` | 35,012 |
| `dynamic_intelligence` | 19,091 |
| `operations_governance` | 38 |
| `investment_hypotheses` | 37 |
| `opportunity_lens` | 19,048 |
| `sentiment_analytics` | 2,113,951 |

The Git-excluded result has evidence identity
`1904d3bb0f5304647ad933d49805f762fae0a1192c23f22e5c54a04ff0bcd698`;
the evidence file SHA-256 is
`4a62976ca0d5f386d4efe7defefe1f593aa4264fd6ba0b87775e0ab99174b7dc`.
The authority set was empty before and after the run, the tracked route remained
`S0/sqlite_transition`, no formal PostgreSQL business mutation was written, and
the production Viewer on port 8080 remained healthy.  This proves durable
S0/S1 staging preparation; it does **not** claim that any unit has entered an
authority state beyond S0.

The temporary interactive task was removed after success.  Obsolete exact
execution directories and incoming packages were removed while the validated
`af510...` package, automation history, diagnostics, PostgreSQL data, WAL,
backup and recovery evidence were retained.  The remaining blockers are final
user approval of the mapping bundle (including four manual items), independent
off-VM recovery, repository production-authority governance,
operator/approver/maintenance-window decisions and explicit S2 authorization.

## Durable authority and S1 state on 2026-08-15

Production main commit `cf726923b2da3c46196765bcb1178c2d36a8041b`
established the next durable boundary:

- `user_content_notes` remains S3/PostgreSQL-authoritative;
- `shared_identity` is S3/PostgreSQL-authoritative with 3,539 formal rows,
  SQLite writer fencing and no SQLite fallback;
- `financial_data` (53,569), `research_publication` (35,012),
  `dynamic_intelligence` (19,091), `operations_governance` (38),
  `investment_hypotheses` (37), `opportunity_lens` (19,048) and
  `sentiment_analytics` (2,113,951) are durable S1/sqlite-transition.

For the seven S1 units, all 2,240,746 source and target rows reconcile by count
and canonical content SHA256.  Their PostgreSQL rows remain non-formal migration
material, so SQLite is still their only production authority/writer.  This is
not permission to enter S2.

The `shared_identity` recovery set was copied to the approved independent host,
restored solely from that set, and verified for whole-database, side and
authority-control recovery.  At final retention exactly two validated recovery
sets remained.  Raw database, credential and recovery evidence stays outside
Git; this tracked summary records only identities and conclusions.

The production Viewer now reads both S3 units from PostgreSQL, refuses SQLite
fallback and passed health plus representative `/research`, `/companies`,
`/industry/1`, `/company/1`, `/tools` and `/opportunity-lens` reads.  A Windows
venv launcher/listener PID mismatch and an undersized first-cache health timeout
were corrected in the lifecycle contract; process identity is now bound to the
actual listener PID.
