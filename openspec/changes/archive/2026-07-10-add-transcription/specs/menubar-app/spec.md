## MODIFIED Requirements

### Requirement: Menu bar recording control
The system SHALL provide a macOS menu bar icon with a submenu containing "Iniciar", "Parar", "Parar e não transcrever", and "Sair", that starts and stops recording using the existing capture module, without requiring a terminal. Starting a new recording SHALL be allowed even while a previous recording's transcription is still in progress.

#### Scenario: Starting a recording from the menu bar
- **WHEN** the user clicks "Iniciar" while no recording is in progress
- **THEN** recording starts using the existing capture module, and the "Iniciar" item becomes disabled while "Parar" and "Parar e não transcrever" become enabled

#### Scenario: Stopping a recording and transcribing (default)
- **WHEN** the user clicks "Parar" while a recording is in progress
- **THEN** the recording is stopped and saved using the existing capture module, a background transcription is started for that recording, and the "Parar" item becomes disabled while "Iniciar" becomes enabled

#### Scenario: Stopping a recording without transcribing
- **WHEN** the user clicks "Parar e não transcrever" while a recording is in progress
- **THEN** the recording is stopped and saved using the existing capture module, no transcription is started for that recording, and the "Parar" item becomes disabled while "Iniciar" becomes enabled

#### Scenario: Starting a new recording while a previous one is still being transcribed
- **WHEN** the user clicks "Iniciar" while no recording is in progress but a previous recording's transcription is still running in the background
- **THEN** a new recording starts normally, independent of the in-progress transcription

#### Scenario: Inapplicable menu items are disabled, not hidden
- **WHEN** the menu bar app is idle (not recording)
- **THEN** "Parar" and "Parar e não transcrever" are visible but disabled, and "Iniciar" is enabled

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

## ADDED Requirements

### Requirement: Quit confirmation while transcriptions are in progress
The system SHALL show a confirmation alert before quitting if one or more transcriptions are still in progress, and SHALL only quit if the user confirms.

#### Scenario: Quitting with transcriptions in progress
- **WHEN** the user clicks "Sair" while one or more transcriptions are still running
- **THEN** a confirmation alert is shown describing that transcription is in progress, and the application only quits if the user confirms; declining leaves the application running with the transcription(s) still in progress

#### Scenario: Quitting with no transcriptions in progress
- **WHEN** the user clicks "Sair" while no transcription is running
- **THEN** the application quits without showing a transcription-related confirmation (the existing auto-save-on-quit behavior for an in-progress recording still applies)
