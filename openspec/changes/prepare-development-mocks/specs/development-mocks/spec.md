## ADDED Requirements

### Requirement: Module mock coverage
The system SHALL provide local Mock fixtures for auth, profile, eligibility, QA, plans, and schools, with fields matching the API contract.

#### Scenario: Member develops a module offline
- **WHEN** `VITE_USE_MOCK=true`
- **THEN** the member can render the module using local fixtures without starting the backend or crawler.

### Requirement: State coverage
The system SHALL provide success, empty, and error states for every core module; QA SHALL also provide low-confidence data and eligibility SHALL provide eligible, pending, and ineligible cases.

#### Scenario: Frontend tests an empty state
- **WHEN** a member selects an empty fixture
- **THEN** the API wrapper returns the same response envelope with an empty data collection and no runtime shape error.

### Requirement: Mock provenance
The system SHALL clearly mark Mock provenance as demonstration data and SHALL NOT represent it as an official factual conclusion.

#### Scenario: Mock result is displayed
- **WHEN** a UI renders a factual-looking Mock result
- **THEN** it shows the demonstration-data label and preserves citation fields required by the contract.

### Requirement: Team readiness documentation
The repository SHALL include a development guide, module ownership table, Mock usage guide, and a minimal acceptance checklist for new members.

#### Scenario: New member joins
- **WHEN** a member follows the development guide
- **THEN** they can install dependencies, enable Mock, locate the API contract, identify their feature branch, and run the basic checks.
