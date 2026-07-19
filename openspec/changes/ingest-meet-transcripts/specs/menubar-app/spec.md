## ADDED Requirements

### Requirement: Periodic Meet-transcript ingestion poller
The system SHALL, when the `meet_transcripts` feature is enabled and at least one calendar account is configured, run a background poller in the menu bar app that periodically ingests Meet transcripts from past calendar events, at the configured poll interval, reflecting in-progress ingestion in the existing transcribing icon state. When the feature is disabled or no calendar is configured, the poller SHALL NOT run.

#### Scenario: Poller runs when enabled
- **WHEN** the menu bar app starts with `meet_transcripts.enabled` true and calendars configured
- **THEN** an ingestion run executes shortly after startup and then repeats at the configured poll interval, each run performing ingestion in a background daemon thread

#### Scenario: Ingestion reflected in the icon
- **WHEN** a background ingestion run is in progress
- **THEN** the menu bar icon shows the transcribing state (combinable with the recording state), and returns to its prior state when the run completes, whether it succeeded or failed

#### Scenario: Poller inactive when disabled or unconfigured
- **WHEN** the menu bar app starts with the `meet_transcripts` feature disabled or with no calendars configured
- **THEN** no ingestion poller is started and menu bar behavior is otherwise unchanged

#### Scenario: Repeated poll failures surfaced
- **WHEN** ingestion polls fail repeatedly and reach the failure-notification threshold
- **THEN** a notification informs the user, mirroring the auto-record poll-failure behavior, without aborting the app
