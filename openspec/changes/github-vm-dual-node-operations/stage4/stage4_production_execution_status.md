# Stage 4 Production Execution Status

This file is a tracked, redacted status summary.  It is not authority evidence.
The final evidence bundle remains Git-excluded and is verified by hash.

## Current independent evidence

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

## Human/external gates deliberately not self-approved

- final cutover-level approval of the identity mapping exceptions;
- repository production-authority governance or an approved exception;
- operator/approver separation and maintenance window;
- future application service-principal credential provisioning;
- independent off-VM recovery copy and restore proof;
- explicit authorization to enter S2.

No item above may be converted to `pass` by a Boolean declaration or a fabricated
hash.  PostgreSQL installation and the final unit states are updated only from
the VM execution evidence after the exact commit is deployed.
