## ADDED Requirements

### Requirement: PostgreSQL is the long-term structured production authority
After a domain completes cutover, the central PostgreSQL platform SHALL be its sole production system of record, and Git, local dev databases, transition SQLite files, exports, and backups SHALL NOT compete as current live authorities.

#### Scenario: A migrated domain receives a write
- **WHEN** a production writer updates a migrated domain
- **THEN** it SHALL write through the approved PostgreSQL role and domain transaction boundary, while the prior SQLite copy remains read-only

### Requirement: Logical domains precede physical database split
The platform SHALL prefer one primary business database with logical domains, shared identity, role separation, and controlled writers unless measured capacity, legal, permission, failure-domain, or lifecycle requirements justify physical separation.

#### Scenario: A four-database PostgreSQL mapping is proposed
- **WHEN** the only rationale is that the current system has four SQLite files
- **THEN** the proposal SHALL be rejected until it demonstrates why logical schema and role boundaries are insufficient and how cross-database identity and transactions will be handled

### Requirement: Shared entity identity is authoritative
Company, security, market, and industry identities used across research, opportunity, financial, sentiment, and user content SHALL have a single authoritative definition and SHALL NOT be independently recreated by each domain.

#### Scenario: A domain references a listed company
- **WHEN** a domain creates or links a company-specific record
- **THEN** it SHALL resolve the canonical shared identity or stop for explicit disambiguation rather than create a silent duplicate

### Requirement: Cross-domain objects have stable identity or explicit legacy mapping
Cross-environment, published, audited, or cross-domain objects SHALL have a stable business identity or a verified source-to-target mapping that does not depend solely on one SQLite auto-increment value; PostgreSQL MAY still use internal surrogate keys and the system SHALL NOT require UUID for every row.

#### Scenario: A legacy SQLite row is migrated
- **WHEN** the row is referenced by another domain, artifact, publication, checkpoint, or public URI
- **THEN** the migration SHALL preserve a verifiable mapping from source database/table/id through the stable identity to the PostgreSQL target object

### Requirement: Data access is separated from SQLite file semantics
Business code SHALL access structured data through testable connection, transaction, and domain writer boundaries, and new production code SHALL NOT add direct SQLite file dependencies during migration.

#### Scenario: SQLite-specific behavior is migrated
- **WHEN** code depends on `ATTACH`, PRAGMA, `BEGIN IMMEDIATE`, rowid, SQLite conflict syntax, or file paths
- **THEN** its business invariant and transaction semantics SHALL be identified and tested on PostgreSQL rather than translated by unreviewed string replacement

### Requirement: SQLite dependency inventory is machine-readable and maintained
Before production sequencing, the system SHALL inventory direct SQLite dependencies with file path, domain, read/write property, SQLite-specific semantics, `ATTACH` dependencies, affected pages/APIs/jobs/publishers, candidate cutover unit, authoritative backend, and migration state.

#### Scenario: Migration scope is proposed
- **WHEN** a file, schema, or table is selected for cutover
- **THEN** the maintained inventory and domain/transaction dependency graphs SHALL show whether it can move independently or must join a larger business cutover unit

### Requirement: Development and production databases are isolated
Local development and CI SHALL use independent dev/test PostgreSQL environments or approved sanitized restores, while production access SHALL be explicitly read-only or separately authorized.

#### Scenario: Local development starts without VM connectivity
- **WHEN** the production VM or database is unavailable
- **THEN** local tests and Viewer development SHALL use local dev/test data and SHALL NOT require a production connection

### Requirement: Migration proceeds by auditable business cutover unit
Migration SHALL use a cutover unit that preserves complete transaction and business semantics rather than assume a SQLite file, PostgreSQL schema, or table is independently movable. Each unit SHALL have a dependency graph, rehearsal, source/target validation, authoritative-backend record, unique-writer cutover, observation period, and state-appropriate recovery decision.

For audit and ownership purposes, a writer SHALL mean a domain mutation path, write endpoint, writer operation, or transaction contract rather than an entire process. Process or runner identity, database role, writer operation, transaction boundary, and owning cutover unit SHALL remain distinct dimensions.

#### Scenario: One process contains multiple mutation paths
- **WHEN** a Viewer process or scheduled-task process contains writer operations with separable transaction and domain ownership
- **THEN** each operation SHALL be inventoried independently and MAY belong to a different owning cutover unit; shared process identity alone SHALL NOT force an oversized unit

#### Scenario: Cutover is requested
- **WHEN** source counts, relationships, business invariants, permissions, backup restore, critical reads/writes, or rollback have unresolved failures
- **THEN** the cutover unit SHALL remain on its prior authority and the cutover SHALL stop

### Requirement: Cutover-unit ownership is unique and versioned
Every writable object, production writer, and indivisible transaction boundary SHALL have exactly one owning cutover unit. Other units MAY declare dependencies but SHALL NOT duplicate ownership. The system SHALL maintain a versioned unit registry with included and dependent objects, current S0-S4 state, accountable owner, boundary history, and overlap/conflict results.

#### Scenario: Shared identity is used by multiple domains
- **WHEN** company, security, or industry identity participates in multiple domain operations
- **THEN** dependency and transaction analysis SHALL assign it to one foundational or larger joint unit, while every other unit records a dependency rather than a second ownership claim

#### Scenario: Two units claim the same writable object or transaction boundary
- **WHEN** the registry or authoritative-backend matrix detects overlapping ownership
- **THEN** production sequencing SHALL stop until a human-reviewed boundary revision produces one owner; migration tooling SHALL NOT silently move the object between units

#### Scenario: Object authority is queried during mixed migration
- **WHEN** an operator, application, or audit resolves a writable object
- **THEN** the authoritative-backend matrix SHALL return one owning unit, one current state, one backend, and one production writer

#### Scenario: Authority state advances to stable operation
- **WHEN** a controller requests S3 to S4
- **THEN** database constraints and the transition contract SHALL require PostgreSQL authority, preserve the S3 writer, cutover epoch, source final watermark and first formal commit, require expected revision, actor, reason and a non-empty S4 approval reference distinct from the current S3 approval, and SHALL reject any attempt to restore a SQLite backend, reuse the prior approval, or rewrite those authority identifiers

### Requirement: Mixed migration has one explicit authoritative backend per cutover unit
During mixed SQLite/PostgreSQL operation, every cutover unit SHALL declare its authoritative reader/writer backend and SHALL have exactly one production writer.

#### Scenario: PostgreSQL write fails
- **WHEN** a migrated writer cannot commit to PostgreSQL
- **THEN** the operation SHALL fail visibly and SHALL NOT silently write to SQLite

#### Scenario: One business operation spans both stores
- **WHEN** its required effects cannot commit atomically in one authoritative backend
- **THEN** the operation SHALL be blocked or its entire dependency group SHALL be migrated together; independent commits to both stores SHALL NOT be represented as one atomic transaction

### Requirement: Long-term dual-write is prohibited by default
The migration SHALL NOT rely on indefinite SQLite/PostgreSQL dual-write or bidirectional synchronization.

#### Scenario: Temporary shadow write is proposed
- **WHEN** a domain cannot be migrated with copy, bounded catch-up, maintenance cutover, and shadow reads
- **THEN** temporary dual-write SHALL require separate approval, explicit idempotency and failure semantics, an expiry condition, and proof that it will be removed

### Requirement: Transition SQLite role changes after PostgreSQL writes
SQLite backups, consistency checks, and migration manifests SHALL be retained as migration baselines and audit material, but direct production fallback SHALL depend on whether PostgreSQL has created new writes that must be preserved.

#### Scenario: Writer is enabled but no durable new business write exists
- **WHEN** an audited cutover failure occurs before any must-preserve PostgreSQL write
- **THEN** the prior SQLite writer MAY be restored only after PostgreSQL writes are stopped and the cutover epoch, source final business watermark, target audit, and human approval jointly prove the no-new-write condition

#### Scenario: Cutover enters the S2 validation fence
- **WHEN** PostgreSQL routing, role, and connection can accept writes but ordinary production traffic remains fenced
- **THEN** PostgreSQL SHALL be the sole designated writer backend, the SQLite writer SHALL be stopped and frozen, only distinguishable non-business PostgreSQL verification writes MAY occur, and the ledger SHALL record the cutover epoch, SQLite final authoritative business watermark, PostgreSQL first formal business-commit watermark, routing state, verification writes, uncertain responses, actor, time, and evidence

#### Scenario: First must-preserve business write commits
- **WHEN** the first formal PostgreSQL business write is durably committed
- **THEN** the cutover unit SHALL transition immediately from S2 to S3 and record the transition in the audit ledger

#### Scenario: The first formal mutation is a delete
- **WHEN** a valid create, update, or soft-delete is the first must-preserve business mutation after a non-empty backfill
- **THEN** that mutation, its revision/audit/idempotency records, the first-formal watermark, and the S2-to-S3 authority revision SHALL commit atomically; a missing object or stale revision SHALL fail without advancing authority

#### Scenario: Commit response is uncertain
- **WHEN** PostgreSQL may have committed but the caller did not receive a conclusive response
- **THEN** the system SHALL resolve the result through stable business identity, idempotency identity, or ledger; until non-commit is proven, the unit SHALL be treated as S3 and SHALL NOT restore the SQLite writer

#### Scenario: S2 remains open as an ordinary operating state
- **WHEN** a plan attempts to keep S2 as hours- or days-long production operation without a bounded exit decision
- **THEN** the plan SHALL be rejected because S2 is a short controlled cutover fence, not a steady production state

#### Scenario: PostgreSQL has must-preserve new writes
- **WHEN** a cutover unit has accepted valid post-cutover data
- **THEN** the old SQLite SHALL NOT become the production writer by simple configuration rollback and SHALL serve only as baseline, audit, or limited repair input unless a separately approved reverse migration reconciles all newer data

#### Scenario: A new shared-identity object appears before shared identity cutover
- **WHEN** a migrated dependent unit receives a mutation for a company, industry, theme, or other identity that was created while shared identity remains SQLite-authoritative
- **THEN** the mutation SHALL fail closed until a unit-specific controller records a non-conflicting mapping with the expected authority revision, read-only source watermark, stable identity, evidence identity, actor, approval and audit; S2 SHALL prohibit mapping changes, and the mapping bridge SHALL NOT become a second identity authority

#### Scenario: Stability window ends
- **WHEN** a migrated domain passes its approved stability and restore criteria
- **THEN** application write paths to its SQLite source SHALL be removed and any longer retention SHALL be governed as archive, not live synchronization

### Requirement: PostgreSQL schema evolution uses expand and contract
Schema migrations SHALL add compatible structures before reader/writer transition, backfill and verify data, and remove or tighten legacy structures only in a later separately approved contract release.

#### Scenario: Destructive change is proposed
- **WHEN** a migration would drop, rename, narrow, or tighten an object needed by the prior application release
- **THEN** the destructive contract SHALL be deferred until the compatibility window is complete and its forward-only recovery plan is approved
