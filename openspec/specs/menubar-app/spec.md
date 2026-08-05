# menubar-app Specification

## Purpose
TBD - created by archiving change add-menubar-icon. Update Purpose after archive.

## Requirements

### Requirement: Menu bar recording control
The system SHALL provide a macOS menu bar icon with a submenu containing "Iniciar", "Parar", "Parar e não transcrever", "Descartar", and "Sair", that starts, stops, and discards recordings using the existing capture module, without requiring a terminal. Starting a new recording SHALL be allowed even while a previous recording's transcription is still in progress. Starting a recording SHALL run the capture module's start call on a background thread rather than the menu bar's main thread, so that a slow or unresponsive underlying audio call cannot block the menu bar's UI or event loop. While a start attempt is in flight, "Iniciar" SHALL be disabled so a second click cannot trigger a concurrent start attempt.

#### Scenario: Starting a recording from the menu bar
- **WHEN** the user clicks "Iniciar" while no recording is in progress
- **THEN** recording starts using the existing capture module, and the "Iniciar" item becomes disabled while "Parar", "Parar e não transcrever", and "Descartar" become enabled once the recording has successfully started

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

#### Scenario: Menu bar stays responsive while a start attempt is slow
- **WHEN** the user clicks "Iniciar" and the underlying capture module's start call takes a long time (or hangs) to return
- **THEN** the menu bar icon and all other menu items (including "Sair") remain responsive to clicks while the start attempt is still pending

#### Scenario: A second click while starting is a no-op
- **WHEN** the user clicks "Iniciar" again while a previous "Iniciar" click's start attempt is still in flight
- **THEN** no second start attempt is made and menu state is unaffected by the extra click

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
The system SHALL show a modal alert if starting a recording from the menu bar fails, describing the failure, and SHALL leave the menu bar app running afterward. Because the start call runs on a background thread, this alert SHALL be shown by marshaling the call back to the main thread rather than invoking it directly from the background thread.

#### Scenario: Device not found on start
- **WHEN** the user clicks "Iniciar" and the underlying capture module raises an error (e.g. microphone or BlackHole device not found, or output device switch failure)
- **THEN** a modal alert is shown describing the failure, and the menu bar app remains running with "Iniciar" re-enabled

#### Scenario: Start failure re-enables Iniciar
- **WHEN** a background start attempt fails after "Iniciar" was disabled for the attempt
- **THEN** "Iniciar" becomes enabled again once the failure alert is shown, so the user can retry

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
