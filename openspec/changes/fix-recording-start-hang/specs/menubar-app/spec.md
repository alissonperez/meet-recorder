## MODIFIED Requirements

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

### Requirement: Start failure alert
The system SHALL show a modal alert if starting a recording from the menu bar fails, describing the failure, and SHALL leave the menu bar app running afterward. Because the start call runs on a background thread, this alert SHALL be shown by marshaling the call back to the main thread rather than invoking it directly from the background thread.

#### Scenario: Device not found on start
- **WHEN** the user clicks "Iniciar" and the underlying capture module raises an error (e.g. microphone or BlackHole device not found, or output device switch failure)
- **THEN** a modal alert is shown describing the failure, and the menu bar app remains running with "Iniciar" re-enabled

#### Scenario: Start failure re-enables Iniciar
- **WHEN** a background start attempt fails after "Iniciar" was disabled for the attempt
- **THEN** "Iniciar" becomes enabled again once the failure alert is shown, so the user can retry
