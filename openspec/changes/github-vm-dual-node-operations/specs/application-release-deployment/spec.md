## ADDED Requirements

### Requirement: Safe application repository boundary
The system SHALL manage deployable application versions in an explicitly approved application repository and SHALL exclude live databases, WAL/SHM, runtime state, backups, broadcast archives, credentials, personal scratch, temporary cache, and unapproved large materials from Git history. Private visibility remains the normal long-term boundary; a public migration-review exception requires explicit user approval, repeated exposure review, and SHALL NOT grant production authority.

#### Scenario: Bootstrap inventory review
- **WHEN** the first Git index is prepared
- **THEN** a machine-readable tracked inventory and secret/path scan SHALL prove that every staged path is allowed before the bootstrap commit

#### Scenario: Formal project rules survive a clean clone
- **WHEN** a developer creates a clean clone
- **THEN** the clone SHALL contain the team `AGENTS.md`, active OpenSpec, required skills, database migrations, tests, deployment/recovery SOPs, and other formal rules needed for development and review

#### Scenario: Repository is temporarily public for migration review
- **WHEN** the user explicitly keeps the repository public so reviewers can inspect code, Actions, commits, and evidence
- **THEN** every stage SHALL re-run exposure review, prohibited assets SHALL remain blocked, and production authority SHALL remain gated independently

### Requirement: Separate Git, main, and production gates
The system SHALL distinguish the gate for creating a safe initial Git history from the gates for merging to protected `main` and deploying production.

#### Scenario: Known test debt during bootstrap
- **WHEN** the tracked inventory is safe but documented tests still fail
- **THEN** a bootstrap branch MAY be created so fixes occur under version control, but the failing commit SHALL NOT become deployable production `main`

#### Scenario: Protected main merge
- **WHEN** a change is proposed for production `main`
- **THEN** the named compile, active test, contract, secret/path, and deployment-manifest checks SHALL pass and branch protection SHALL prevent force-push and deletion

### Requirement: Production repository authority is company-governed
An application repository owned by a personal account MAY support an approved safe bootstrap and development workflow, but it SHALL NOT become the production code authority until company control and recovery are demonstrable.

#### Scenario: Personal repository is proposed for production deployment
- **WHEN** the repository owner is an individual account
- **THEN** production deployment SHALL remain blocked until company ownership or an approved exception, a second company administrator or handover mechanism, mandatory 2FA, account recovery, branch protection, least privilege, and a company-controlled VM deploy credential are verified

### Requirement: Explicit local authentication
Local repository access SHALL use an approved OS credential store or browser-based credential flow, and credentials SHALL NOT be passed through chat, command-line arguments, project files, environment files, or logs.

#### Scenario: Authenticated remote operation
- **WHEN** a user performs an authenticated fetch or push
- **THEN** no token, password, private key, or credential fragment SHALL appear in project output or repository history

### Requirement: Pull-based immutable VM releases
The VM SHALL fetch an explicit full commit SHA using read-only application-repository credentials, create an immutable `releases/<sha>` directory, attach approved runtime dependencies, run preflight, and atomically switch `current` only after checks pass.

#### Scenario: Successful read-only candidate deployment
- **WHEN** a candidate commit and manifest pass build, preflight, health, and read-only smoke checks
- **THEN** the VM MAY retain only the isolated candidate `current` for the approved scope and SHALL record commit, manifest, verified process identity, Python lock identity, representative smoke, and observed before/after production evidence; a pointer staged after preflight but before process health SHALL be restored on any later failure

#### Scenario: Candidate process is started, replaced, or stopped
- **WHEN** the deployer manages the read-only candidate listener
- **THEN** the listener-owning process SHALL be the recorded process rather than a venv redirector or outer CLI process, its identity SHALL include more than a reusable PID, and stop or cleanup SHALL refuse to terminate a process whose start time, executable, command contract, launch identity, commit, and port do not match

#### Scenario: Candidate startup or smoke fails
- **WHEN** any post-launch health, identity, content, database, or route check fails
- **THEN** every verifiably started candidate process SHALL be reclaimed, the prior candidate pointer SHALL be restored or the candidate SHALL return to no-current state, failure evidence SHALL be retained, and production 8080 and scheduled tasks SHALL remain untouched

#### Scenario: VM Python is selected
- **WHEN** a candidate environment is prepared
- **THEN** deployment SHALL require an explicit Python 3.10 executable, create or reuse only a candidate-local environment bound to the approved lockfile, verify exact locked packages, invoke every project-code Python child with isolated import resolution and bytecode writes disabled, launch the listener without inheriting `PYTHONPATH`, `PYTHONHOME`, user site, or unrelated third-party package paths, and SHALL NOT silently select a PATH interpreter or alter the production task environment

#### Scenario: Candidate runtime closure is verified
- **WHEN** immutable code is attached to external data, content, and state roots
- **THEN** relative database content references SHALL resolve against the declared external authority and representative smoke SHALL cover research, sentiment, financial, Opportunity Lens, external document, calculator, and static-asset reads without copying those authorities into the release

#### Scenario: Required and optional external content are distinguished
- **WHEN** candidate preflight evaluates the manifest-declared external content closure
- **THEN** every path SHALL declare its required/optional presence, object kind, and purpose; a missing or wrong-kind required path SHALL fail closed, while a missing optional enhancement SHALL be recorded without being represented as present or weakening the underlying database-backed route

#### Scenario: Database-backed theme has no Markdown enhancement
- **WHEN** a theme exists in `research.db` but the optional `docs/themes` directory or matching Markdown file is absent
- **THEN** the theme route SHALL render the database-backed theme and relations, identify that the optional Markdown analysis is absent, and pass a representative read-only smoke without requiring an empty placeholder directory

#### Scenario: Dirty or mutable release
- **WHEN** the target release differs from its verified manifest or contains an unapproved runtime mutation
- **THEN** exact-file verification SHALL fail without changing `current`; an invalid inactive and non-current release MAY be atomically moved as a whole into an auditable quarantine before a clean rebuild, but a current release or one referenced by a candidate process record SHALL never be overwritten, patched, deleted, or quarantined automatically

#### Scenario: Same commit is retried after a failed attempt
- **WHEN** deployment retries the same full SHA after preflight, startup, smoke, or later candidate validation failed
- **THEN** a still-valid release SHALL be reused exactly, an invalid inactive release SHALL follow the quarantine-and-rebuild contract, prior attempt evidence SHALL be retained under a unique attempt identity, and no implementation SHALL delete only known `.pyc` files or weaken the manifest file-set comparison

#### Scenario: Release remains immutable throughout candidate lifecycle
- **WHEN** build, preflight, activation, listener startup, representative smoke, failure cleanup, or stop imports project code
- **THEN** those operations SHALL leave the release file set and every manifest-declared file unchanged, and lifecycle evidence SHALL bind exact verification results to the build, preflight, activation, launch, smoke, and stop or failure-cleanup stages

### Requirement: Code rollback is independent from data rollback
The VM SHALL support switching to a prior verified application release without automatically changing PostgreSQL, transition SQLite, papers, or user content.

#### Scenario: Viewer failure after release switch
- **WHEN** health or smoke checks fail after switching code
- **THEN** the deployer SHALL restore the previous `current`, verify health, record the failure, and SHALL NOT overwrite or roll back live data implicitly

### Requirement: Schema changes preserve an explicit compatibility window
PostgreSQL schema evolution SHALL use expand, migrate/backfill, application transition, and separately approved contract steps; destructive changes SHALL NOT be bundled into the same irreversible release that first requires them.

#### Scenario: Prior application release is selected
- **WHEN** an operator attempts code-only rollback
- **THEN** rollback SHALL proceed only if the current backend passes that release's declared object-type, required-column, version, and read-probe contract; any full schema fingerprint that is only diagnostic SHALL NOT be presented as exhaustive compatibility proof, and failures SHALL use the migration-specific forward recovery plan

#### Scenario: Migration is forward-only
- **WHEN** a migration cannot be safely reversed
- **THEN** its compatibility, backup, verification, and recovery strategy SHALL be recorded and approved before production execution

### Requirement: Local development remains independent
Developers SHALL be able to pull, modify, test, start the Viewer, inspect pages, commit, and push using an isolated dev/test database without requiring the production VM to be online.

#### Scenario: Production VM is offline
- **WHEN** the production VM or production database is unavailable
- **THEN** local development and page testing SHALL continue against local dev/test data, and tooling SHALL NOT silently fall back to production write credentials
