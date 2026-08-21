## MODIFIED Requirements

### Requirement: Visual recording indicator
The system SHALL display a distinct visual indicator on the menu bar icon reflecting the combination of two independent states — whether a recording is in progress, and whether one or more transcriptions are in progress — without displaying a count of transcriptions. When the microphone requires the user's attention during a recording, the icon SHALL blink by alternating between the current indicator and the neutral (idle) indicator at a fixed interval defined by a named constant, without introducing any additional icon asset.

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

#### Scenario: Icon blinks while the microphone needs attention
- **WHEN** the microphone channel has been reported silent, or microphone capture is paused for a device switch, during a recording
- **THEN** the menu bar icon alternates between the indicator for the current state and the neutral indicator until the condition clears

#### Scenario: Blink clears when the microphone recovers
- **WHEN** a microphone channel that triggered the blink is reported as recovered, or microphone capture resumes after a device switch
- **THEN** the icon stops blinking and shows the steady indicator for the current recording and transcription state

#### Scenario: Blink uses the same signal for both microphone conditions
- **WHEN** either microphone condition (sustained silence or a paused switch) is active
- **THEN** the same blinking behavior is used for both, and the specific cause is conveyed through the menu and notification text rather than through a distinct icon

### Requirement: System-audio silence notification
The system SHALL show a native macOS notification when the system-audio channel is detected as silent for a sustained period during a recording started from the menu bar.

#### Scenario: Sustained silence triggers a notification
- **WHEN** a recording started from the menu bar is in progress and the system-audio channel remains silent for the sustained period defined by the capture module
- **THEN** a native macOS notification is shown alongside the existing log warning, and the recording continues uninterrupted

#### Scenario: Notification identifies the affected channel
- **WHEN** a sustained-silence notification is shown for either the microphone channel or the system-audio channel
- **THEN** the notification text identifies which channel is silent and states the corresponding remedy — switching the microphone input device for the microphone channel, or checking the Screen Recording permission for the system-audio channel

## ADDED Requirements

### Requirement: Microphone silence notification
The system SHALL show a native macOS notification when the microphone channel is detected as silent for a sustained period during a recording started from the menu bar, and SHALL clear the associated icon alert state when the capture module reports that the microphone channel has recovered.

#### Scenario: Sustained microphone silence triggers a notification
- **WHEN** a recording started from the menu bar is in progress and the microphone channel remains silent for the sustained period defined by the capture module
- **THEN** a native macOS notification is shown indicating that the microphone appears silent and that the input device can be switched, and the recording continues uninterrupted

#### Scenario: Microphone recovery clears the alert
- **WHEN** the capture module reports that the microphone channel has returned to a non-silent level after a silence notification
- **THEN** the menu bar app clears the microphone alert state and the icon stops blinking

### Requirement: Switch microphone from the menu bar
The system SHALL provide a menu bar action to switch the microphone input device, enabled only while a recording is in progress. Activating it SHALL pause microphone capture, present the user with a selection of the input devices enumerated after the pause, and resume microphone capture against the chosen device. Because the device list is only valid once microphone capture is paused, the selection SHALL be presented as a dialog built at activation time rather than as a statically populated submenu.

#### Scenario: Action availability follows the recording state
- **WHEN** no recording is in progress
- **THEN** the microphone switch action is disabled, and it becomes enabled when a recording starts and disabled again when the recording stops or is discarded

#### Scenario: Switching the microphone from the menu bar
- **WHEN** the user activates the microphone switch action during a recording and selects a device from the presented list
- **THEN** microphone capture resumes on the selected device and the recording continues as a single recording

#### Scenario: Device list is built after capture is paused
- **WHEN** the user activates the microphone switch action during a recording
- **THEN** microphone capture is paused before the input devices are enumerated, and the presented list reflects the devices available at that moment, including devices connected after the recording started

#### Scenario: Icon blinks while the selection dialog is open
- **WHEN** microphone capture is paused awaiting the user's device selection
- **THEN** the menu bar icon blinks for the duration of the pause and returns to its steady indicator once capture resumes

#### Scenario: Cancelling the dialog resumes capture
- **WHEN** the user dismisses the device selection dialog without choosing a device
- **THEN** microphone capture is resumed by the capture module and the recording is not left without microphone capture

#### Scenario: Switch failure is reported without stopping the recording
- **WHEN** resuming microphone capture against the selected device fails
- **THEN** a modal alert describing the failure is shown by marshaling the call to the main thread, and the recording continues with microphone capture resumed against a usable device
