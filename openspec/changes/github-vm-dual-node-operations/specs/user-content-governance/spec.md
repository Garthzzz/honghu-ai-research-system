## ADDED Requirements

### Requirement: User content has revision, soft-delete, and audit history
Comments, theses, hypotheses, Q6 edits, manual events, research requests, confidence changes, and other approved human-authored content SHALL be stored with current state, revision history, soft deletion, authorship, and auditable timestamps in the central database.

#### Scenario: A user edits existing content
- **WHEN** an authorized edit is committed
- **THEN** the new revision and actor SHALL be recorded atomically without destroying the prior revision

#### Scenario: A user deletes content
- **WHEN** an authorized delete is requested
- **THEN** the content SHALL be soft-deleted and remain available to authorized audit and recovery processes

#### Scenario: A backfilled note is the first formal post-cutover deletion
- **WHEN** a valid soft-delete is the first formal mutation while the owning cutover unit is in S2
- **THEN** the soft-delete revision, audit, idempotency result, first-formal watermark, and S2-to-S3 authority revision SHALL commit in one transaction under the same writer fence and expected-revision contract as create and update

#### Scenario: Audit actor reaches the production adapter
- **WHEN** a production user-content mutation is submitted
- **THEN** the audit actor SHALL be derived from a trusted authenticated principal and SHALL NOT trust a client-controlled free-form actor value

### Requirement: User-content updates detect stale revisions
Each durable user-content object SHALL have a stable identity and an expected revision, base version, or equivalent concurrency condition; PostgreSQL transactions SHALL NOT be treated as permission for silent last-write-wins.

#### Scenario: Two clients edit the same thesis
- **WHEN** the second commit is based on a revision that is no longer current
- **THEN** the update SHALL fail with an explicit conflict, preserve both submitted context and the latest revision for reconciliation, and SHALL NOT silently overwrite the newer content

#### Scenario: A retried edit has already committed
- **WHEN** the same idempotency identity is submitted after an uncertain response
- **THEN** the system SHALL return the committed revision or complete the same logical edit without creating a duplicate revision

### Requirement: PostgreSQL is the user-content authority
GitHub SHALL NOT be required as a second real-time content database when PostgreSQL revision, audit, backup, and recovery are available.

#### Scenario: Per-edit Git push fails or is unavailable
- **WHEN** GitHub is unreachable or no content repository is configured
- **THEN** an authorized PostgreSQL user-content transaction SHALL remain valid and recoverable without a Git outbox or replay dependency

### Requirement: The existing content repository remains unused
The existing repository with the logical name `honghu-ai-research-content` SHALL remain `RESERVED-UNUSED` and SHALL NOT receive production credentials, live user content, database dumps, or revision events.

#### Scenario: A future encrypted backup is considered
- **WHEN** low-frequency GitHub disaster storage is proposed
- **THEN** a separately scoped backup repository and compliance decision SHALL be evaluated rather than silently reusing the reserved content repository

### Requirement: User content export is controlled and portable
The system SHALL support a controlled export of user content and revision metadata for portability, audit, or approved disaster recovery without exposing credentials or silently creating a second live authority.

#### Scenario: An export is requested
- **WHEN** an authorized user creates an export
- **THEN** it SHALL carry scope, time, schema/version, integrity metadata, and sensitivity classification and SHALL NOT be automatically committed to application Git

### Requirement: Sensitive content follows material compliance boundaries
Human investment notes, confidence, trade hypotheses, requests, and comments SHALL be assessed for cloud-storage sensitivity at least as strictly as papers and evidence.

#### Scenario: Content-repository use is proposed
- **WHEN** user content would be uploaded to GitHub or another external service
- **THEN** explicit compliance approval and a reason not satisfied by PostgreSQL revision/audit/backup SHALL be required

### Requirement: Empty legacy tables enable clean migration, not skipped governance
An empty or low-row legacy user-content table MAY be replaced by the new governed model without first adding a SQLite event system, but existing non-empty human content SHALL still be inventoried, migrated, and reconciled.

#### Scenario: `analyst_note` is empty but thesis records exist
- **WHEN** the user-content pilot is designed
- **THEN** the empty table MAY use the new model directly, while existing thesis/hypothesis records SHALL receive an explicit preservation and validation plan

### Requirement: User-content references remain fail-closed while shared identity is transitional
User-content writers SHALL reference only verified stable identities or audited legacy mappings and SHALL NOT create, infer, or overwrite shared identity as a side effect of a note mutation.

#### Scenario: A note targets a newly created SQLite-authoritative entity
- **WHEN** shared identity has not yet cut over and the entity is absent from the dependent unit mapping snapshot
- **THEN** the note mutation SHALL fail until a controller records an approved, source-watermarked and audited mapping outside S2; identity ambiguity or mapping collision SHALL remain blocked
