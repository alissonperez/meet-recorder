## MODIFIED Requirements

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
