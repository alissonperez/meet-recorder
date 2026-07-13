## MODIFIED Requirements

### Requirement: Recording file output location
The system SHALL save completed recordings as `.wav` files in the `~/MeetRecordings` directory, named using a timestamp of when the recording started, not when it was stopped or saved.

#### Scenario: Recording saved with timestamped filename
- **WHEN** a recording is stopped and saved
- **THEN** the resulting file is written under `~/MeetRecordings/` with a filename derived from the recording's start timestamp (e.g. `2026-07-09_14-30.wav`)

#### Scenario: Long recording keeps its start-time filename
- **WHEN** a recording runs long enough that the wall-clock time at stop differs from the wall-clock time at start (e.g. by more than an hour, or across midnight)
- **THEN** the saved filename still reflects the moment the recording started, not the moment it was stopped
