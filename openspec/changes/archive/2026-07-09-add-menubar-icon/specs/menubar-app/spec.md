## ADDED Requirements

### Requirement: Menu bar recording control
The system SHALL provide a macOS menu bar icon with a submenu containing exactly three items — "Iniciar", "Parar", and "Sair" — that starts and stops recording using the existing capture module, without requiring a terminal.

#### Scenario: Starting a recording from the menu bar
- **WHEN** the user clicks "Iniciar" while no recording is in progress
- **THEN** recording starts using the existing capture module, and the "Iniciar" item becomes disabled while "Parar" becomes enabled

#### Scenario: Stopping a recording from the menu bar
- **WHEN** the user clicks "Parar" while a recording is in progress
- **THEN** the recording is stopped and saved using the existing capture module, and the "Parar" item becomes disabled while "Iniciar" becomes enabled

#### Scenario: Inapplicable menu items are disabled, not hidden
- **WHEN** the menu bar app is idle (not recording)
- **THEN** the "Parar" item is visible but disabled, and the "Iniciar" item is enabled

### Requirement: Visual recording indicator
The system SHALL display a distinct visual indicator on the menu bar icon while a recording is in progress, and SHALL revert to a neutral icon when not recording.

#### Scenario: Icon reflects recording state
- **WHEN** a recording starts
- **THEN** the menu bar icon shows a red indicator distinguishing it from the idle state

#### Scenario: Icon reverts to neutral after stopping
- **WHEN** a recording stops
- **THEN** the menu bar icon returns to its neutral (non-recording) appearance

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
