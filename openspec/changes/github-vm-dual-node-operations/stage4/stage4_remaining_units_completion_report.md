# Stage 4 Remaining Units Completion Report

## Outcome

As of 2026-08-15, two units are durable S3 and seven units are durable S1.
Stage 4 is not complete because the seven S1 units do not yet have production
application adapters, operation-level writer fencing and unit-specific recovery
evidence sufficient for S2/S3.

## Production authority

| cutover unit | state | formal authority | rows | result |
| --- | --- | --- | ---: | --- |
| `user_content_notes` | S3 | PostgreSQL | governed user-content rows | retained and healthy |
| `shared_identity` | S3 | PostgreSQL | 3,539 | source/target reconciled, SQLite fenced |
| `financial_data` | S1 | SQLite | 53,569 | PostgreSQL non-formal baseline reconciled |
| `research_publication` | S1 | SQLite | 35,012 | PostgreSQL non-formal baseline reconciled |
| `dynamic_intelligence` | S1 | SQLite | 19,091 | PostgreSQL non-formal baseline reconciled |
| `operations_governance` | S1 | SQLite | 38 | PostgreSQL non-formal baseline reconciled |
| `investment_hypotheses` | S1 | SQLite | 37 | PostgreSQL non-formal baseline reconciled |
| `opportunity_lens` | S1 | SQLite | 19,048 | PostgreSQL non-formal baseline reconciled |
| `sentiment_analytics` | S1 | SQLite | 2,113,951 | PostgreSQL non-formal baseline reconciled |

The seven S1 units total 2,240,746 rows.  Every source count equals its target
count and every canonical source content SHA256 equals its target SHA256.
Their evidence explicitly records `formal_business_data=false`,
`production_cutover_authorized=false` and `s2_s3_entered=false`.

## Shared identity S3 and recovery

The S3 authority revision records PostgreSQL as the only backend and
`honghu_writer_shared_identity` as the only writer.  The final SQLite watermark
contains 3,539 rows and is now an audit/migration baseline, not a rollback
target.  The first formal PostgreSQL commit and cutover epoch are durably
recorded in the authority ledger.

An encrypted independent-host recovery set passed artifact hash, WAL target,
sentinel, whole restore, side restore and authority-control restore checks.
Measured recovery was RPO 0.016 seconds and RTO 0.687 seconds for the verified
reopen path.  Retention keeps exactly the latest two verified recovery sets.

## Application validation

The production Viewer reports exact commit
`cf726923b2da3c46196765bcb1178c2d36a8041b`, mode
`production_postgresql`, and S3/PostgreSQL for both active units.  Both SQLite
writer flags are false.  HTTP and TLS listeners are bound to their actual
listener processes, not the Windows venv launcher.  Representative read routes
for research, companies, industry, company, tools and Opportunity Lens returned
HTTP 200 after the S3 transition.

## Remaining blockers

The seven S1 units have 744 audited writer operations across 293 transaction
boundaries.  They cannot safely enter S2/S3 until each unit has an explicit
PostgreSQL adapter, operation-level writer fence, compatible API/read path,
delta catch-up at the final watermark, unit-specific off-VM recovery evidence
and a fail-closed production lifecycle.  Stage 5 task/runner migration remains
outside the current authorization.

Repository production authority also still requires a human governance
decision for company ownership or an approved exception, a second administrator,
2FA/recovery custody and company-controlled deploy credentials.  Until then the
release contract remains: green CI, human approval of an exact SHA, then an
immutable VM deployment.

Raw database, backup, credential and VM evidence is intentionally not tracked.
