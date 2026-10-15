## ADDED Requirements

### Requirement: Reproducible staging
The system SHALL provide an idempotent script that copies the supported merged JSON files into the importer-expected staging directory structure without changing record content or order.

#### Scenario: Generate staging from merged data
- **WHEN** the operator runs the staging script with a valid merged root and output root
- **THEN** all eight supported datasets are copied to their documented paths and the script reports counts.

### Requirement: Staging validation
The staging script SHALL fail before copying when a required source file is missing, invalid JSON, has an unexpected target table, or its `meta.count` differs from the actual record count.

#### Scenario: Source count mismatch
- **WHEN** a merged file declares a count different from its records length
- **THEN** the script exits non-zero and identifies the file and expected/actual counts.

### Requirement: Position-preserving school data
The staging process SHALL preserve the original order and content of `school.json` because `school_major_score.school_id` is position-coupled to the school table.

#### Scenario: Repeat staging
- **WHEN** the script is run twice with the same inputs
- **THEN** the output bytes and record order are stable and no link or reordering is introduced.
