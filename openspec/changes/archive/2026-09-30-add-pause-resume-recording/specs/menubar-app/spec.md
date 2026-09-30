## MODIFIED Requirements

### Requirement: Menu bar recording control
The system SHALL provide a macOS menu bar icon with a submenu containing "Iniciar", "Pausar" or "Retomar", "Parar", "Parar e não transcrever", "Descartar", and "Sair", that starts, pauses, resumes, stops, and discards recordings using the existing capture module, without requiring a terminal. Starting a new recording SHALL be allowed even while a previous recording's transcription is still in progress. Starting, pausing, and resuming SHALL run the corresponding capture-module call on a background thread rather than the menu bar's main thread, so that a slow or unresponsive underlying audio call cannot block the menu bar's UI or event loop. While a start attempt is in flight, "Iniciar" SHALL be disabled so a second click cannot trigger a concurrent start attempt. The pause action SHALL be enabled only during active capture with no microphone switch underway; the resume action SHALL be enabled only while the recording is paused. A stable paused recording SHALL continue to enable the stop, stop-without-transcription, discard, and quit actions. While pause or resume is in flight, all menu actions that can mutate that capture session SHALL be disabled until the transition completes, and stale asynchronous completions SHALL NOT overwrite a newer UI state.

#### Scenario: Starting a recording from the menu bar
- **WHEN** the user clicks "Iniciar" while no recording is in progress
- **THEN** recording starts using the existing capture module, and the "Iniciar" item becomes disabled while "Pausar", "Parar", "Parar e não transcrever", and "Descartar" become enabled once the recording has successfully started

#### Scenario: Pausing a recording from the menu bar
- **WHEN** the user clicks "Pausar" while a recording is actively capturing
- **THEN** the recording enters the paused state, the item label changes to "Retomar", and "Parar", "Parar e não transcrever", and "Descartar" remain enabled

#### Scenario: Resuming a recording from the menu bar
- **WHEN** the user clicks "Retomar" while a recording is paused
- **THEN** the recording resumes capture and the item label changes back to "Pausar"

#### Scenario: Conflicting controls are disabled during pause or resume
- **WHEN** a pause or resume capture call is in flight
- **THEN** "Pausar" or "Retomar", "Parar", "Parar e não transcrever", "Descartar", microphone switching, and "Sair" remain visible but disabled until that transition succeeds or fails

#### Scenario: Pause or resume failure restores a usable state
- **WHEN** a pause or resume capture call fails
- **THEN** the menu returns to the stable state that remains in the capture module, restores the actions applicable to that state, and shows an alert describing the failure

#### Scenario: Microphone fallback completes resume with a warning
- **WHEN** resume succeeds by replacing a disconnected previous microphone with the current default microphone
- **THEN** the menu publishes the active recording state and shows a non-fatal alert identifying that a microphone fallback occurred

#### Scenario: Stopping a recording and transcribing (default)
- **WHEN** the user clicks "Parar" while a recording is active or paused
- **THEN** the recording is stopped and saved using the existing capture module, a background transcription is started for that recording, and "Pausar", "Parar", "Parar e não transcrever", and "Descartar" become disabled while "Iniciar" becomes enabled

#### Scenario: Stopping a recording without transcribing
- **WHEN** the user clicks "Parar e não transcrever" while a recording is active or paused
- **THEN** the recording is stopped and saved using the existing capture module, no transcription is started for that recording, and "Pausar", "Parar", "Parar e não transcrever", and "Descartar" become disabled while "Iniciar" becomes enabled

#### Scenario: Starting a new recording while a previous one is still being transcribed
- **WHEN** the user clicks "Iniciar" while no recording is in progress but a previous recording's transcription is still running in the background
- **THEN** a new recording starts normally, independent of the in-progress transcription

#### Scenario: Inapplicable menu items are disabled, not hidden
- **WHEN** the menu bar app is idle (not recording)
- **THEN** "Pausar", "Parar", "Parar e não transcrever", and "Descartar" are visible but disabled, and "Iniciar" is enabled

#### Scenario: Menu bar stays responsive while a start attempt is slow
- **WHEN** the user clicks "Iniciar" and the underlying capture module's start call takes a long time (or hangs) to return
- **THEN** the menu bar icon and all other menu items (including "Sair") remain responsive to clicks while the start attempt is still pending

#### Scenario: A second click while starting is a no-op
- **WHEN** the user clicks "Iniciar" again while a previous "Iniciar" click's start attempt is still in flight
- **THEN** no second start attempt is made and menu state is unaffected by the extra click

### Requirement: Discard an in-progress recording
The system SHALL provide a "Descartar" menu item, enabled while a recording is actively capturing or paused, that discards the entire in-progress recording after user confirmation: capture stops immediately, no output file is written to the recordings directory, the temporary audio buffers are deleted, and no transcription is started.

#### Scenario: Discarding a recording after confirmation
- **WHEN** the user clicks "Descartar" while a recording is in progress and confirms the discard in the confirmation modal
- **THEN** the recording stops, its temporary mic and system-audio buffers are deleted without producing a saved `.wav` file, no transcription is started, and "Iniciar" becomes enabled while "Pausar", "Parar", "Parar e não transcrever", and "Descartar" become disabled

#### Scenario: Discarding a paused recording after confirmation
- **WHEN** the user clicks "Descartar" while a recording is paused and confirms the discard in the confirmation modal
- **THEN** the paused recording is discarded with the same result as an actively capturing recording

#### Scenario: Declining the discard confirmation
- **WHEN** the user clicks "Descartar" while a recording is in progress and cancels the confirmation modal
- **THEN** the recording continues uninterrupted and no menu item state changes

#### Scenario: Discard unavailable while idle
- **WHEN** the user clicks "Descartar" while no recording is in progress
- **THEN** nothing happens, since the item is disabled in this state

### Requirement: Visual recording indicator
The system SHALL display a distinct visual indicator on the menu bar icon reflecting one mutually exclusive capture-session state — idle, actively capturing, or paused — combined with whether one or more transcriptions are in progress, without displaying a count of transcriptions. When the microphone requires the user's attention during active recording, the icon SHALL blink by alternating between the current indicator and the neutral (idle) indicator at a fixed interval defined by a named constant, without introducing any additional icon asset.

#### Scenario: Icon reflects recording only
- **WHEN** a recording is actively capturing and no transcription is running
- **THEN** the menu bar icon shows the recording indicator

#### Scenario: Icon reflects paused recording
- **WHEN** a recording is paused and no transcription is running
- **THEN** the menu bar icon shows an indicator distinct from both active recording and idle

#### Scenario: Icon reflects transcribing only
- **WHEN** no recording is in progress and at least one transcription is running
- **THEN** the menu bar icon shows the transcribing indicator

#### Scenario: Icon reflects both recording and transcribing
- **WHEN** a recording is actively capturing and at least one transcription is also running
- **THEN** the menu bar icon shows a combined indicator distinct from either state alone

#### Scenario: Icon reflects paused recording and transcribing
- **WHEN** a recording is paused and at least one transcription is also running
- **THEN** the menu bar icon shows a combined paused-and-transcribing indicator distinct from the active-recording-and-transcribing indicator

#### Scenario: Icon reverts to neutral
- **WHEN** no recording is in progress and no transcription is running
- **THEN** the menu bar icon returns to its neutral (idle) appearance

#### Scenario: Icon blinks while the microphone needs attention
- **WHEN** the microphone channel has been reported silent, or microphone capture is paused for a device switch, during active recording
- **THEN** the menu bar icon alternates between the indicator for the current state and the neutral indicator until the condition clears

#### Scenario: Blink clears when the microphone recovers
- **WHEN** a microphone channel that triggered the blink is reported as recovered, or microphone capture resumes after a device switch
- **THEN** the icon stops blinking and shows the steady indicator for the current recording and transcription state

#### Scenario: Blink uses the same signal for both microphone conditions
- **WHEN** either microphone condition (sustained silence or a paused switch) is active
- **THEN** the same blinking behavior is used for both, and the specific cause is conveyed through the menu and notification text rather than through a distinct icon

### Requirement: Switch microphone from the menu bar
The system SHALL provide a menu bar action to switch the microphone input device, enabled only while a recording is actively capturing and no whole-recording transition is underway. Activating it SHALL pause microphone capture, present the user with a selection of the input devices enumerated after the pause, and resume microphone capture against the chosen device. Because the device list is only valid once microphone capture is paused, the selection SHALL be presented as a dialog built at activation time rather than as a statically populated submenu. While this microphone-only switch is underway, whole-recording pause SHALL be disabled. A delayed completion from the microphone-switch flow SHALL NOT change capture or menu state after the session has been finalized.

#### Scenario: Action availability follows the recording state
- **WHEN** the app is idle, the recording is globally paused, or whole-recording pause or resume is in flight
- **THEN** the microphone switch action is disabled, and it is enabled only while the recording is actively capturing without another transition underway

#### Scenario: Switching the microphone from the menu bar
- **WHEN** the user activates the microphone switch action during active capture and selects a device from the presented list
- **THEN** microphone capture resumes on the selected device and the recording continues as a single recording

#### Scenario: Device list is built after capture is paused
- **WHEN** the user activates the microphone switch action during active capture
- **THEN** microphone capture is paused before the input devices are enumerated, and the presented list reflects the devices available at that moment, including devices connected after the recording started

#### Scenario: Whole-recording pause is unavailable during microphone selection
- **WHEN** microphone capture is paused awaiting the user's device selection
- **THEN** the whole-recording pause action is disabled until microphone capture resumes or the recording is finalized

#### Scenario: Icon blinks while the selection dialog is open
- **WHEN** microphone capture is paused awaiting the user's device selection
- **THEN** the menu bar icon blinks for the duration of the pause and returns to its steady indicator once capture resumes

#### Scenario: Cancelling the dialog resumes capture
- **WHEN** the user dismisses the device selection dialog without choosing a device
- **THEN** microphone capture is resumed by the capture module and the recording is not left without microphone capture

#### Scenario: Switch failure is reported without stopping the recording
- **WHEN** resuming microphone capture against the selected device fails
- **THEN** a modal alert describing the failure is shown by marshaling the call to the main thread, and the recording continues with microphone capture resumed against a usable device

#### Scenario: Late microphone-switch completion cannot replace idle state
- **WHEN** the recording is saved or discarded while a microphone-switch operation still has an asynchronous completion pending
- **THEN** the pending completion does not reopen microphone capture, change the idle menu state, or publish a recording icon

### Requirement: Auto-save on quit
The system SHALL automatically stop and save any actively capturing or paused recording before the menu bar app exits.

#### Scenario: Quitting while recording
- **WHEN** the user clicks "Sair" while a recording is actively capturing
- **THEN** the recording is stopped and saved using the existing capture module before the application quits

#### Scenario: Quitting while paused
- **WHEN** the user clicks "Sair" while a recording is paused
- **THEN** the paused recording is stopped and saved using the existing capture module before the application quits

#### Scenario: Quitting while idle
- **WHEN** the user clicks "Sair" while no recording is in progress
- **THEN** the application quits immediately without attempting to stop or save anything
