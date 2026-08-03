## ADDED Requirements

### Requirement: Code, data, artifact, and personal context are classified separately
The system SHALL maintain explicit classifications for application code and formal rules, live structured data, papers/evidence and other large artifacts, runtime material, credentials, and personal working context.

#### Scenario: A new path is proposed for Git
- **WHEN** a path is not already covered by the tracked allowlist
- **THEN** it SHALL remain untracked until its classification, sensitivity, size, deployment need, and retention policy are reviewed

### Requirement: Formal development and review rules are versioned
The application repository SHALL include team-shared rules that materially affect development, research review, database migration, deployment, and recovery.

#### Scenario: Agent or skill rule affects production output
- **WHEN** an `AGENTS.md`, active skill, OpenSpec, migration contract, or test rule is required to reproduce or review production behavior
- **THEN** the formal active version SHALL be tracked, while conversation history, one-time memory, and personal configuration SHALL remain excluded

### Requirement: Deployment closure is manifest-driven
The release builder SHALL compute deployment closure from an approved deployment manifest and referenced artifact manifests rather than from `.gitignore` or the entire working tree.

#### Scenario: Required evidence is not stored in Git
- **WHEN** a release references an approved paper, evidence file, model artifact, or necessary cache outside Git
- **THEN** its stable identity, hash, expected storage class, and availability SHALL be verified before deployment

### Requirement: Papers and evidence remain separate from live structured data
Large research materials SHALL be stored in an approved internal file system, object store, or separately approved Git LFS/Release channel, and SHALL NOT be embedded in PostgreSQL rows or assumed to be present in the application repository.

#### Scenario: Material lacks cloud approval
- **WHEN** a paper, user content export, or evidence file has not been approved for external cloud storage
- **THEN** it SHALL remain in the approved internal storage boundary and only a non-sensitive manifest MAY be versioned

### Requirement: The existing content repository has no implicit production role
The repository currently named with the logical purpose `honghu-ai-research-content` SHALL remain `RESERVED-UNUSED`, SHALL NOT enter application deployment closure, and SHALL NOT be required for startup, publication, backup, or recovery unless a later approved change assigns a specific compliant purpose.

#### Scenario: Content or backup upload is proposed
- **WHEN** a workflow targets the reserved content repository
- **THEN** the upload SHALL be rejected because the repository has no production credential, live-content authority, backup authority, or deployment responsibility; a future backup use SHALL require a separately reviewed repository and compliance boundary

### Requirement: Secrets never enter reusable artifacts
Credentials, cookies, browser profiles, database passwords, encryption keys, and vendor secrets SHALL NOT enter Git, broadcast bundles, application releases, cache audit packages, logs, or research outputs.

#### Scenario: Secret or local absolute path is detected
- **WHEN** a scanner finds a secret pattern, credential path, browser profile, or unapproved machine-specific absolute path
- **THEN** the build, commit, or deployment SHALL fail before the material leaves its approved host

### Requirement: Necessary cache is minimized but complete
Only cache files referenced by active configuration, live database records, research evidence, or active financial models SHALL enter a deployment bundle, and stale or unreferenced cache SHALL NOT be copied by default.

#### Scenario: Required cache reference is missing
- **WHEN** a manifest references a required cache item that is unavailable or has a mismatched hash
- **THEN** deployment SHALL fail rather than silently omitting the artifact
