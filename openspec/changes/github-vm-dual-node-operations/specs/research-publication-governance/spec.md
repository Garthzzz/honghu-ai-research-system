## ADDED Requirements

### Requirement: Draft, review, and published research remain distinct
Research production SHALL preserve explicit staging, review, approval, and published states independent of the underlying database engine.

#### Scenario: Draft content is written
- **WHEN** a producer creates or updates a research artifact
- **THEN** the change SHALL remain non-public until the applicable contract gates and reviewers pass and an authorized publisher acts

### Requirement: Publication is controlled and auditable
The publication transaction SHALL record the research identity, input/output or artifact hashes where applicable, reviewer state, publisher, time, and resulting revision.

#### Scenario: Review state changes after staging
- **WHEN** a staged artifact receives additional reviewer findings or closures
- **THEN** publication SHALL use the latest authoritative review state and SHALL NOT rely on a stale copied manifest

### Requirement: Domain writers preserve existing evidence and financial boundaries
A/B ingest, Opportunity Lens loader/publication, and financial model export SHALL continue using their canonical validation and writer boundaries rather than a generic SQL or cross-machine change-set interface.

#### Scenario: Generic change-set bypass is proposed
- **WHEN** a tool attempts to publish research or financial results without the domain's evidence, calculation, financial, review, or provenance gates
- **THEN** the write SHALL be rejected even if the database transaction is technically valid

### Requirement: Publication is idempotent and revision-aware
Every publication SHALL have a stable publication/release identity. Retries SHALL not duplicate published research, and an update to an existing object SHALL carry an expected revision, base version, or equivalent concurrency condition so stale work cannot silently overwrite newer production state.

#### Scenario: Publisher retries after an uncertain response
- **WHEN** the same approved publication identity is retried
- **THEN** the system SHALL return the existing result or complete the same revision without creating a second logical publication

#### Scenario: Staged work is based on an old production revision
- **WHEN** the production object changed after the producer's base revision
- **THEN** publication SHALL stop with an explicit stale-update conflict and SHALL NOT use silent last-write-wins

### Requirement: A publication dependency cluster commits atomically
The publication transaction SHALL include all objects that must jointly establish one valid business release, or SHALL fail without exposing a partial release.

#### Scenario: A dependent object fails validation or persistence
- **WHEN** a source, claim, entity, review state, model link, or publication ledger entry required by the release cannot commit
- **THEN** the entire publication cluster SHALL remain unpublished and retry SHALL use the same stable release identity and explicit recovery state

### Requirement: Publication transaction ownership is unambiguous during migration
Each publication writer and its indivisible dependency cluster SHALL belong to exactly one owning cutover unit. Other units MAY depend on published identities or read models but SHALL NOT separately claim the same writer or transaction boundary.

#### Scenario: A publication cluster spans identities and research tables
- **WHEN** one valid release requires shared identity, sources, claims, entities, reviews, model links, and ledger state to succeed together
- **THEN** the cutover-unit registry SHALL assign the complete transaction boundary to one owner or block production cutover until the boundary is refactored and reviewed

#### Scenario: Publication ownership overlaps another unit
- **WHEN** two cutover units declare ownership of the same publisher or writable publication object
- **THEN** publication migration SHALL stop and the overlap SHALL be resolved by a human-reviewed registry change rather than by runtime routing

### Requirement: Publication failures have replay and recovery semantics
The publisher SHALL distinguish a safely retryable request, an already committed release, a stale conflict, and a failed uncommitted transaction.

#### Scenario: Response is lost after commit
- **WHEN** the caller cannot tell whether the transaction completed
- **THEN** it SHALL query by stable release identity and resume idempotently rather than issue a new logical publication

### Requirement: Migration preserves publication semantics
Moving a research domain from SQLite to PostgreSQL SHALL validate state transitions, review records, source/claim relationships, public visibility, and publication history in addition to table counts.

#### Scenario: Row counts match but public state differs
- **WHEN** migration validation finds the same number of rows but a draft appears published or a review record is detached
- **THEN** the migration SHALL fail and the production writer SHALL remain on the prior authority

### Requirement: Publication concurrency is domain governance, not generic SQLite synchronization
Expected revision, stable release identity, idempotency, and transaction boundaries SHALL remain after removal of generic cross-machine CAS and change-set protocols.

#### Scenario: Generic CAS retirement is cited
- **WHEN** an implementation proposes removing stale-write detection because PostgreSQL supplies transactions
- **THEN** the proposal SHALL be rejected because database atomicity does not resolve business revision conflicts by itself
