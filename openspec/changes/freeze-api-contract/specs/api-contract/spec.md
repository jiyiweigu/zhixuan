## ADDED Requirements

### Requirement: Unified response envelope
The system SHALL return every API response in the `{code, message, data, trace_id}` envelope, with `code=0` for success and documented business error codes for failures.

#### Scenario: Successful request
- **WHEN** a client calls a valid endpoint
- **THEN** the response contains `code=0`, a human-readable `message`, endpoint data under `data`, and a non-empty `trace_id`.

### Requirement: Core endpoint contract
The system SHALL define request and response schemas for authentication, user profile, pathway eligibility, pathway catalog, QA, volunteer plans, and school search under the `/api` prefix.

#### Scenario: Frontend starts module development
- **WHEN** a member reads `docs/api-contract.md`
- **THEN** they can identify method, path, auth requirement, request fields, response fields, error codes, and a Mock example for each core endpoint.

### Requirement: Citation metadata
The system SHALL attach `source_name`, `source_url`, and `year` to every factual result, and QA responses SHALL include `citations` and a numeric `confidence` between 0 and 1.

#### Scenario: Result has no citation
- **WHEN** a factual result lacks required citation metadata
- **THEN** the client SHALL treat it as unavailable and SHALL NOT render it as a confirmed conclusion.

### Requirement: Contract change process
The team SHALL update the contract document and Mock examples in the same pull request as any breaking API change.

#### Scenario: Breaking field change
- **WHEN** a member needs to rename, remove, or change the type of a public field
- **THEN** they SHALL update the document, explain migration impact, and notify affected module owners before merge.
