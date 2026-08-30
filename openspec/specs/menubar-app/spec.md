# menubar-app Specification

## Purpose
TBD - created by archiving change add-menubar-icon. Update Purpose after archive.

## Requirements

### Requirement: Menu bar recording control
The system SHALL provide a macOS menu bar icon with a submenu containing "Iniciar", "Parar", "Parar e não transcrever", "Descartar", and "Sair", that starts, stops, and discards recordings using the existing capture module, without requiring a terminal. Starting a new recording SHALL be allowed even while a previous recording's transcription is still in progress.

#### Scenario: Starting a recording from the menu bar
- **WHEN** the user clicks "Iniciar" while no recording is in progress
- **THEN** recording starts using the existing capture module, and the "Iniciar" item becomes disabled while "Parar", "Parar e não transcrever", and "Descartar" become enabled

#### Scenario: Stopping a recording and transcribing (default)
- **WHEN** the user clicks "Parar" while a recording is in progress
- **THEN** the recording is stopped and saved using the existing capture module, a background transcription is started for that recording, and "Parar", "Parar e não transcrever", and "Descartar" become disabled while "Iniciar" becomes enabled

#### Scenario: Stopping a recording without transcribing
- **WHEN** the user clicks "Parar e não transcrever" while a recording is in progress
- **THEN** the recording is stopped and saved using the existing capture module, no transcription is started for that recording, and "Parar", "Parar e não transcrever", and "Descartar" become disabled while "Iniciar" becomes enabled

#### Scenario: Starting a new recording while a previous one is still being transcribed
- **WHEN** the user clicks "Iniciar" while no recording is in progress but a previous recording's transcription is still running in the background
- **THEN** a new recording starts normally, independent of the in-progress transcription

#### Scenario: Inapplicable menu items are disabled, not hidden
- **WHEN** the menu bar app is idle (not recording)
- **THEN** "Parar", "Parar e não transcrever", and "Descartar" are visible but disabled, and "Iniciar" is enabled

### Requirement: Discard an in-progress recording
The system SHALL provide a "Descartar" menu item, enabled only while a recording is in progress, that discards the entire in-progress recording after user confirmation: capture stops immediately, no output file is written to the recordings directory, the temporary audio buffers are deleted, and no transcription is started.

#### Scenario: Discarding a recording after confirmation
- **WHEN** the user clicks "Descartar" while a recording is in progress and confirms the discard in the confirmation modal
- **THEN** the recording stops, its temporary mic and system-audio buffers are deleted without producing a saved `.wav` file, no transcription is started, and "Iniciar" becomes enabled while "Parar", "Parar e não transcrever", and "Descartar" become disabled

#### Scenario: Declining the discard confirmation
- **WHEN** the user clicks "Descartar" while a recording is in progress and cancels the confirmation modal
- **THEN** the recording continues uninterrupted and no menu item state changes

#### Scenario: Discard unavailable while idle
- **WHEN** the user clicks "Descartar" while no recording is in progress
- **THEN** nothing happens, since the item is disabled in this state

### Requirement: Visual recording indicator
The system SHALL display a distinct visual indicator on the menu bar icon reflecting the combination of two independent states — whether a recording is in progress, and whether one or more transcriptions are in progress — without displaying a count of transcriptions.

#### Scenario: Icon reflects recording only
- **WHEN** a recording is in progress and no transcription is running
- **THEN** the menu bar icon shows the recording indicator

#### Scenario: Icon reflects transcribing only
- **WHEN** no recording is in progress and at least one transcription is running
- **THEN** the menu bar icon shows the transcribing indicator

#### Scenario: Icon reflects both recording and transcribing
- **WHEN** a recording is in progress and at least one transcription is also running
- **THEN** the menu bar icon shows a combined indicator distinct from either state alone

#### Scenario: Icon reverts to neutral
- **WHEN** no recording is in progress and no transcription is running
- **THEN** the menu bar icon returns to its neutral (idle) appearance

### Requirement: Start failure alert
The system SHALL show a modal alert if starting a recording from the menu bar fails, describing the failure, and SHALL leave the menu bar app running afterward.

#### Scenario: Device not found on start
- **WHEN** the user clicks "Iniciar" and the underlying capture module raises an error (e.g. microphone or BlackHole device not found, or output device switch failure)
- **THEN** a modal alert is shown describing the failure, and the menu bar app remains running with "Iniciar" still enabled

### Requirement: System-audio silence notification
The system SHALL show a native macOS notification when the system-audio channel is detected as silent for a sustained period during a recording started from the menu bar.

#### Scenario: Sustained silence triggers a notification
- **WHEN** a recording started from the menu bar is in progress and the system-audio channel remains silent for the sustained period defined by the capture module
- **THEN** a native macOS notification is shown alongside the existing log warning, and the recording continues uninterrupted

### Requirement: Auto-save on quit
The system SHALL automatically stop and save any in-progress recording before the menu bar app exits.

#### Scenario: Quitting while recording
- **WHEN** the user clicks "Sair" while a recording is in progress
- **THEN** the recording is stopped and saved using the existing capture module before the application quits

#### Scenario: Quitting while idle
- **WHEN** the user clicks "Sair" while no recording is in progress
- **THEN** the application quits immediately without attempting to stop or save anything

### Requirement: CLI entrypoint for the menu bar app
The system SHALL expose a CLI command that launches the menu bar application.

#### Scenario: Launching via CLI
- **WHEN** the `menubar` CLI command is invoked
- **THEN** the menu bar icon appears and remains running until the user quits it via the "Sair" menu item

### Requirement: Quit confirmation while transcriptions are in progress
The system SHALL show a confirmation alert before quitting if one or more transcriptions are still in progress, and SHALL only quit if the user confirms.

#### Scenario: Quitting with transcriptions in progress
- **WHEN** the user clicks "Sair" while one or more transcriptions are still running
- **THEN** a confirmation alert is shown describing that transcription is in progress, and the application only quits if the user confirms; declining leaves the application running with the transcription(s) still in progress

#### Scenario: Quitting with no transcriptions in progress
- **WHEN** the user clicks "Sair" while no transcription is running
- **THEN** the application quits without showing a transcription-related confirmation (the existing auto-save-on-quit behavior for an in-progress recording still applies)

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

### Requirement: Deferred retry for failed menu bar transcriptions
The system SHALL, when a transcription started by the menu bar app fails after its immediate per-request retries are exhausted or bypassed as non-retryable, record that recording's `.wav` path in a persistent deferred-retry ledger rather than treating the failure as terminal, and SHALL later retry the full transcription pipeline (preprocessing through output-file writing) for that file on a fixed one-hour retry interval. Deferral SHALL apply identically to transcriptions started from the normal stop-recording flow and from the crash-recovery process action.

#### Scenario: Transcription deferred after a failed attempt
- **WHEN** a menu-bar-initiated transcription run fails after immediate retries are exhausted, or because the failure was non-retryable
- **THEN** the recording's `.wav` path is recorded in the persistent deferred-retry ledger with its attempt count incremented, and no user-facing failure notification is shown yet

#### Scenario: Deferred retry survives an application restart
- **WHEN** the menu bar application is quit and relaunched (or the machine restarts) while a transcription is still deferred and not yet due for its next retry
- **THEN** the deferred entry is still present after relaunch and is retried once its one-hour interval has elapsed

#### Scenario: Deferred retry succeeds
- **WHEN** a deferred transcription is retried and the full pipeline (preprocessing through output-file writing) completes successfully
- **THEN** the transcript and summary output files are written as usual, and the deferred-retry entry is marked done so it is not retried again

#### Scenario: Crash-recovered transcriptions use the same deferred-retry flow
- **WHEN** a transcription started from the crash-recovery "Processar" action fails after immediate retries are exhausted or bypassed
- **THEN** it is deferred and later retried the same way as a transcription started from the normal "Parar" flow, rather than immediately notifying the user

#### Scenario: A deleted recording ends its retry loop
- **WHEN** a deferred entry's `.wav` file no longer exists on disk at the time of a scan
- **THEN** the entry is dropped from the ledger without being retried or counted as a further failed attempt

### Requirement: Periodic deferred-transcription retry scan
The system SHALL run a background timer in the menu bar app that periodically scans the deferred-retry ledger for entries whose one-hour retry interval has elapsed and retries each of them in a background thread, reflecting an in-progress retry in the existing transcribing icon state. The system SHALL keep an in-memory record of the recordings currently being transcribed and SHALL skip any due entry already in progress, so the same `.wav` is never transcribed concurrently by two attempts. Because each retry runs a full transcription pipeline, the system SHALL start at most a fixed number of retries per scan, taking the oldest deferrals first and leaving the remaining due entries for a later scan.

#### Scenario: Scan retries a due deferred transcription
- **WHEN** the periodic scan runs and a deferred transcription's retry interval has elapsed
- **THEN** the full transcription pipeline is retried for that recording in a background thread, with the menu bar icon showing the transcribing state for the duration of the attempt

#### Scenario: Scan skips deferred transcriptions not yet due
- **WHEN** the periodic scan runs and a deferred transcription's retry interval has not yet elapsed
- **THEN** that transcription is left untouched until a later scan

#### Scenario: Scan skips a retry that is still running
- **WHEN** the periodic scan runs and a due entry's recording is already being transcribed (by an earlier scan's retry, or by the original stop-recording or crash-recovery attempt that has not finished unwinding)
- **THEN** no second attempt is started for that recording, and it remains eligible for a later scan once the in-progress attempt finishes

#### Scenario: Scan bounds how many retries it starts at once
- **WHEN** the periodic scan finds more due entries than the per-scan limit
- **THEN** only that many retries are started, oldest deferral first, and the remaining due entries are left for the next scan

### Requirement: Bounded transcription retries and failure notification
The system SHALL bound deferred transcription retries by a configurable maximum number of attempts (`transcription_max_retries`, default 72, which at the fixed one-hour interval spans roughly three days), SHALL abandon a deferred transcription once that count is reached, and SHALL show the transcription-failure notification exactly once, at abandonment, without notifying on any earlier failed attempt.

#### Scenario: Deferred retries continue silently within the attempt budget
- **WHEN** a deferred transcription fails again and its attempt count is still below the configured maximum
- **THEN** the entry remains deferred with an updated attempt count and next-retry time, and no notification is shown

#### Scenario: Deferred retries abandoned once the attempt budget is spent
- **WHEN** a deferred transcription fails on the attempt that reaches the configured maximum
- **THEN** the entry is marked abandoned, no further automatic retries occur for it, and the transcription-failure notification is shown to the user once

#### Scenario: Maximum retry count is configurable
- **WHEN** `config.yaml` sets a value for `transcription_max_retries`
- **THEN** that value is used, within its supported bounds, instead of the default of 72 when determining abandonment for deferred transcriptions

#### Scenario: Source recording survives abandonment
- **WHEN** a deferred transcription is abandoned after exhausting its attempt budget
- **THEN** the source `.wav` file is still present and unmodified at its original path and can be reprocessed manually via the `transcribe` CLI command
