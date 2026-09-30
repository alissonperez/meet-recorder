## ADDED Requirements

### Requirement: Periodic folder-ingest poller
The system SHALL, when the `folder_ingest` feature is enabled with at
least one configured directory, run a background poller in the menu bar
app that periodically scans and processes folder-sourced transcripts at
the configured poll interval, reflecting in-progress ingestion in the
existing transcribing icon state. When the feature is disabled or no
directory is configured, the poller SHALL NOT run.

#### Scenario: Poller runs when enabled
- **WHEN** the menu bar app starts with `folder_ingest.enabled` true and at
  least one directory configured
- **THEN** a scan executes shortly after startup and then repeats at the
  configured poll interval, each run scanning and processing files in a
  background daemon thread

#### Scenario: Ingestion reflected in the icon
- **WHEN** a background folder-ingest scan is in progress
- **THEN** the menu bar icon shows the transcribing state (combinable with
  the recording state), and returns to its prior state when the run
  completes, whether it succeeded or failed

#### Scenario: Poller inactive when disabled or unconfigured
- **WHEN** the menu bar app starts with the `folder_ingest` feature
  disabled or with no directories configured
- **THEN** no folder-ingest poller is started and menu bar behavior is
  otherwise unchanged

#### Scenario: Repeated poll failures surfaced
- **WHEN** folder-ingest scans fail repeatedly and reach the
  failure-notification threshold
- **THEN** a notification informs the user, mirroring the Meet-ingestion
  poll-failure behavior, without aborting the app
