## ADDED Requirements

### Requirement: Production data has an off-VM recovery copy
The production PostgreSQL data SHALL have an encrypted backup outside the Viewer/task VM failure domain, and a backup stored only on that VM SHALL NOT count as disaster recovery.

#### Scenario: VM disk is lost
- **WHEN** the production VM and its local disks are unavailable
- **THEN** the approved recovery process SHALL be able to rebuild the database from an independently stored backup and verified application/migration versions

### Requirement: Restore tests prove recoverability
The system SHALL perform periodic real restore tests into an isolated environment and SHALL record integrity, schema version, critical counts, business invariants, and recovery gaps.

#### Scenario: Backup exists but restore fails
- **WHEN** a backup file is present but cannot pass a real restore and validation
- **THEN** the backup SHALL be reported as non-recoverable and SHALL NOT satisfy the production recovery gate

### Requirement: GitHub is not the live database or sole backup
Live PostgreSQL data and routine database dumps SHALL NOT enter ordinary application Git history, and Git LFS SHALL NOT be the default mechanism for frequently changing database backups.

#### Scenario: Encrypted GitHub disaster copy is proposed
- **WHEN** compliance permits a low-frequency backup in a separate private repository or Release asset
- **THEN** it SHALL be encrypted client-side, the key SHALL be stored separately, and an internal or off-VM backup plus restore test SHALL still be required

### Requirement: Transition SQLite backups remain consistent
Until a domain is cut over to PostgreSQL, its SQLite backup SHALL use a consistency-safe method and SHALL include enough metadata to identify source database, schema state, time, integrity result, and migration purpose.

#### Scenario: SQLite database uses WAL
- **WHEN** a transition backup is created from a WAL-mode database
- **THEN** the process SHALL use the SQLite backup API or another verified consistent method and SHALL NOT copy only the main `.db` file during active writes

### Requirement: Transition SQLite has state-dependent recovery value
An old SQLite copy SHALL NOT be described as a lossless production rollback target after PostgreSQL has accepted new writes that must be preserved.

#### Scenario: Cutover is in the S2 validation fence
- **WHEN** direct restoration of the SQLite writer is considered before a known formal PostgreSQL business write
- **THEN** PostgreSQL writes SHALL first be stopped and the cutover epoch, SQLite final authoritative watermark, PostgreSQL audit, verification-write classification, and human approval SHALL prove that no must-preserve write exists; an unresolved commit response SHALL be treated as S3

#### Scenario: PostgreSQL contains valid post-cutover writes
- **WHEN** recovery is considered after the migrated cutover unit has produced valid new PostgreSQL data
- **THEN** SQLite SHALL be treated as a frozen migration baseline, audit archive, and limited repair source; recovery SHALL use PostgreSQL forward repair, schema-compatible code rollback, side-instance restoration with selective repair, or a separately approved explicit reverse migration

### Requirement: Recovery preserves independent authorities
Application code, PostgreSQL data, user-content revision history, and papers/evidence SHALL be restored from their respective authorities and SHALL NOT be rolled back as one undifferentiated directory image.

#### Scenario: Code rollback is required
- **WHEN** a bad application release is rolled back
- **THEN** live data and user content SHALL remain at their current valid revisions unless a separately approved data recovery is executed

### Requirement: Target and measured recovery objectives are distinct gates
Target recovery-point and recovery-time objectives SHALL be approved by data class before production data cutover, while measured recovery-point and recovery-time results SHALL be obtained from real whole-database, side-domain, and bare-machine recovery exercises before final production migration acceptance.

The migration/cutover authority-control class SHALL separately protect cutover-unit S0-S4 state, authoritative backend and unique writer identity, cutover epoch, source and target watermarks, routing state, verification-write classification, uncertain-commit reconciliation, and its audit ledger. An authority transition SHALL NOT be acknowledged until those records are durable, and production writes SHALL remain fenced until the recovered authority state is independently verified. This stricter class SHALL NOT be replaced by the ordinary dynamic/task-state objective.

#### Scenario: Authority-control state is unavailable during recovery
- **WHEN** the system cannot prove the owning cutover unit, authoritative backend, unique writer, cutover epoch, watermarks, or unresolved commit status
- **THEN** production writes SHALL remain fenced, SQLite write authority SHALL NOT be inferred or restored, and the recovery SHALL be reported as missing its authority-control target rather than reconstructed from application defaults

#### Scenario: Production topology is proposed
- **WHEN** PostgreSQL co-location, separation, continuous archiving, PITR, replicas, or backup frequency are evaluated
- **THEN** the proposal SHALL show which data is nearly intolerant of loss, which can be refetched, which cannot be refetched, and which restoration priorities justify the selected controls

#### Scenario: A production cutover unit is proposed
- **WHEN** its data class has no approved target RPO/RTO or no recovery design aligned to those targets
- **THEN** production data cutover SHALL remain blocked

#### Scenario: A first cutover unit is ready to enter S2
- **WHEN** unit-specific off-VM backup, authority-ledger recovery, and isolated restore evidence have not yet been produced
- **THEN** S2 SHALL remain blocked and those controls SHALL NOT be deferred to later system-wide runner migration, bare-machine recovery, or measured-RPO/RTO acceptance work

#### Scenario: A cutover unit contains multiple data classes
- **WHEN** the unit's recovery design is evaluated
- **THEN** it SHALL identify every included or depended-on class and satisfy each applicable target without using a more tolerant class to waive a stricter one; a transition SQLite archive SHALL NOT count as proof that PostgreSQL recovery targets are met

#### Scenario: Final migration acceptance is proposed
- **WHEN** whole-database, isolated single-domain, or bare-machine restore evidence is missing
- **THEN** acceptance SHALL remain blocked until measured recoverable point, elapsed recovery time, unrecovered data, refetch time, and selective-repair time are recorded and compared with the approved targets

### Requirement: Whole-database disaster recovery is distinct from domain logical repair
A logical error limited to one domain SHALL NOT cause an in-place rewind of the entire production database by default.

#### Scenario: One domain contains erroneous writes
- **WHEN** other domains contain valid writes after the affected recovery point
- **THEN** the backup or point-in-time copy SHALL first be restored to an isolated side environment, the affected stable identities SHALL be reconciled, and approved selective repairs SHALL be applied with audit records

### Requirement: Database recovery respects schema compatibility
Backup and recovery evidence SHALL identify the application and migration versions required to read the restored data, including forward-only and expand-contract compatibility boundaries.

#### Scenario: Old code is incompatible with current schema
- **WHEN** an application rollback is requested after a destructive schema contract
- **THEN** code-only rollback SHALL be rejected and the approved database forward-recovery or side-restore strategy SHALL be used

### Requirement: Access and operational security are auditable
Production Viewer writes, publishing, database migrations, backups, and task operations SHALL use authenticated least-privilege identities and produce audit records appropriate to their risk.

#### Scenario: Broad write access is requested
- **WHEN** an account or process requests write access outside its domain
- **THEN** access SHALL be denied until an explicit role review demonstrates the need and scope

### Requirement: Co-located PostgreSQL is an allowed non-HA production topology when objectives are met
PostgreSQL MAY share the Viewer/task VM when approved RPO/RTO, operational skill, workload, and security requirements are met; co-location SHALL NOT be described as highly available or assumed inferior solely because it shares a host.

#### Scenario: Co-located production is approved
- **WHEN** current scale and recovery objectives support co-location
- **THEN** automatic startup, graceful shutdown, crash recovery, resource monitoring, off-VM backup, and bare-machine restore SHALL be verified before the first production data-backend cutover

#### Scenario: Separation is proposed
- **WHEN** independent availability or maintenance, security isolation, sustained resource contention, multiple application nodes, or stronger RPO/RTO cannot be satisfied by co-location
- **THEN** physical separation MAY be required, but its network, identity, certificate, firewall, and recovery costs SHALL be included in the decision
