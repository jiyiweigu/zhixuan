## ADDED Requirements

### Requirement: First-round handoff
The team SHALL publish a first-round handoff that defines branch workflow, module ownership, API change rules, and the boundary between Mock data and future crawler data.

#### Scenario: Member starts implementation
- **WHEN** a member reads the handoff documents
- **THEN** they can select a module, use the correct branch, run Mock mode, and submit a PR to `develop` without inventing endpoint fields.

### Requirement: Contract smoke checks
The repository SHALL provide smoke checks for health, eligibility, and QA Mock responses, including response envelope and citation constraints.

#### Scenario: Smoke checks run
- **WHEN** the checks are executed in a clean development environment
- **THEN** they fail on missing `code`, `data`, `trace_id`, or required citation metadata and pass for the documented fixtures.
