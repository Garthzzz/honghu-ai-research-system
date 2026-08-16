## ADDED Requirements

### Requirement: Scheduled jobs have a canonical manifest
Every production scheduled or continuous job SHALL be declared in a canonical manifest that identifies its domain, schedule, timezone, weekend policy, command, runtime environment, service identity, lock, checkpoint, retry boundary, and freshness expectation.

#### Scenario: Installed task differs from manifest
- **WHEN** an audit detects an undeclared task or a trigger, account, command, or policy mismatch
- **THEN** the mismatch SHALL block cutover and produce a concrete remediation record

#### Scenario: Task is installed from a mutable or ambiguous runtime
- **WHEN** the installed command is not bound to one approved immutable release, lock environment, absolute interpreter, external runtime roots, and manifest identity
- **THEN** the task SHALL remain disabled and SHALL NOT infer an interpreter, checkout, credential, or data path from `PATH`, an interactive profile, or the current working directory

### Requirement: Production jobs run without interactive login
VM production jobs SHALL use approved least-privilege service identities, fixed runtime paths, and approved credentials without requiring an interactive desktop session.

#### Scenario: Interactive-only task is found
- **WHEN** a production candidate task requires the personal login session
- **THEN** it SHALL remain disabled on the VM until a non-interactive real run succeeds

### Requirement: Each job is single-instance and idempotent
Every job SHALL use a domain-appropriate run lock and idempotency identity so retries, host restarts, and delayed triggers do not duplicate production effects.

#### Scenario: Prior run is active or stale
- **WHEN** a new trigger finds an active or stale run record
- **THEN** the runner SHALL distinguish live execution from abandoned state, avoid blind overlap, and record the resolution

#### Scenario: Process exits zero but business state is not current
- **WHEN** the runner process succeeds while a producer checkpoint, source audit, required segment, or logical window remains incomplete
- **THEN** the task SHALL NOT be reported as fresh solely from the exit code; ledger and health SHALL retain the incomplete, degraded, or catch-up state

### Requirement: VM downtime produces an explicit catch-up decision
The operation layer SHALL record the last successful logical window and, after startup, determine which missed windows are safely recoverable, bounded, unavailable, or already completed.

#### Scenario: VM restarts after missed schedules
- **WHEN** one or more scheduled windows elapsed while the VM was off
- **THEN** the runner SHALL create a catch-up plan from checkpoints, execute only allowed backfills, and record any irrecoverable gap and its data impact

### Requirement: Startup order distinguishes process health from data freshness
After a VM start, PostgreSQL connectivity and migration compatibility SHALL be established before enabling Viewer writes or jobs, and job process startup SHALL NOT by itself mark data as current.

#### Scenario: Services start but catch-up is incomplete
- **WHEN** Viewer and task processes are running while missed windows remain unresolved
- **THEN** health output SHALL report the service as running but data freshness as degraded or catching up

### Requirement: Local and VM production jobs never overlap
Migration SHALL move each job through disabled installation, manual real run, local pause, VM enablement, observation, and local disabled retention; both nodes SHALL NOT run the same production job concurrently.

#### Scenario: VM trial fails
- **WHEN** the disabled/manual VM trial or freshness validation fails
- **THEN** the VM task SHALL remain disabled and the local production task MAY resume from the last verified checkpoint

#### Scenario: Disabled VM installation is ready for a real trial
- **WHEN** a task definition, service principal, credential, release, manifest, authority backend, and checkpoint have all been verified
- **THEN** only that task MAY receive an explicit controlled trial; successful registration or process startup alone SHALL NOT authorize enabling its recurring trigger

### Requirement: Task recovery follows authority and checkpoint validation
After a host or database recovery, production tasks SHALL remain disabled until PostgreSQL authority-control state, application/schema compatibility, installed definition identity, task credentials, and the last durable task/business checkpoints have been verified.

#### Scenario: Database is restored but task checkpoint is uncertain
- **WHEN** PostgreSQL is reachable but the last consumed logical window or an uncertain task attempt cannot be reconciled
- **THEN** the runner SHALL stay fenced, classify the window conservatively, and SHALL NOT replay blindly or fall back to SQLite

### Requirement: Data-backend cutover and runner-host cutover are independent states
Each job SHALL record both its authoritative data backend and its unique execution host. Moving SQLite to PostgreSQL SHALL NOT implicitly move the job to the VM, and moving the job host SHALL NOT change data authority.

#### Scenario: Local runner continues after PostgreSQL cutover
- **WHEN** a cutover plan keeps the local scheduler as the sole runner while the domain uses production PostgreSQL
- **THEN** the local runner SHALL use a task-scoped least-privilege database role, approved network and credential boundaries, continuous checkpoint identity, and a disabled VM counterpart; the transition record SHALL include task identity, temporary owner, start time, unique runner, database role and permissions, network/credential method, checkpoint watermark, reason, exit condition, next human HALT, VM prerequisites, and overdue escalation

#### Scenario: Temporary local runner loses connectivity
- **WHEN** the local runner cannot reach production PostgreSQL
- **THEN** the task SHALL fail, pause, or retry according to its manifest and SHALL NOT switch the authoritative backend or write to SQLite

#### Scenario: Temporary local-runner state does not meet its exit condition
- **WHEN** the migration cannot proceed to the VM as planned
- **THEN** the state SHALL be escalated at the recorded human HALT for an explicit decision and SHALL NOT silently become the long-term production topology

#### Scenario: Local access to production PostgreSQL is not approved
- **WHEN** network, credential, or operational review rejects the intermediate local-runner state
- **THEN** the runner-host switch SHALL be included in the same approved cutover unit so the migrated domain is not left without its required writer

#### Scenario: Runner-host rollback is required after PostgreSQL has new data
- **WHEN** the VM job fails after the data backend is already authoritative PostgreSQL
- **THEN** only the unique runner MAY return to the prior host from the verified checkpoint; the data backend SHALL remain PostgreSQL and SHALL NOT silently return to SQLite

#### Scenario: VM runner is ready to become authoritative
- **WHEN** the approved runner-host cutover is executed
- **THEN** the local runner SHALL first be proven stopped before the VM runner is enabled, and after successful transition any unnecessary local production write role, credential, and network access SHALL be revoked

### Requirement: Jobs migrate independently
The seven current tasks SHALL be evaluated and moved one at a time or by a proven dependency group rather than by a single bulk cutover.

#### Scenario: One job has unresolved historical failures
- **WHEN** its current failure state, checkpoint, or data effect is not understood
- **THEN** that job SHALL remain on the current authority and SHALL NOT be hidden by moving it to the VM
