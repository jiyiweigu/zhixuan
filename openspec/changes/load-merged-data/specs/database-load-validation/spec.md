## ADDED Requirements

### Requirement: Full-load sequence
The system SHALL document and support the sequence of schema migration, staging generation, and importer execution using `ZHIXUAN_DATA_ROOT`.

#### Scenario: Load an empty database
- **WHEN** the operator upgrades an empty database and runs the importer against a valid staging root
- **THEN** the importer completes in dependency order and returns no required-dataset or accounted-row errors.

### Requirement: Exact row reconciliation
The system SHALL reconcile database counts against the merged summary with zero tolerance for the eight supported datasets.

#### Scenario: Count report
- **WHEN** loading completes
- **THEN** the report records the expected and actual count for source=291, pathway=26, pathway_region=91, pathway_eligibility=11, province_exam_rule=7, school=1367, score_segment=11694, and school_major_score=116036.

### Requirement: Semantic smoke checks
The system SHALL provide SQL checks for school tier flags, null identity references, and partner-program inheritance, while preserving documented unmatched rows.

#### Scenario: Data semantics review
- **WHEN** the operator runs the documented SQL checks
- **THEN** Tsinghua and Peking University are marked 985, Zhengzhou University is marked 211, null reference counts are reported, and Zhengzhou University partner rows inherit 211.

### Requirement: Regression safety
The system SHALL require importer and model regression scripts to pass after loading, and SHALL record known differences without deleting or guessing data.

#### Scenario: Regression gate
- **WHEN** `python test_importers.py` and `python test_models.py` are run after migration/load
- **THEN** importer tests remain 28/28 and model idempotency/rollback checks remain green.
