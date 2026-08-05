## ADDED Requirements

### Requirement: Microphone device list refreshed before capture starts
The system SHALL refresh the underlying audio library's device list immediately before selecting and opening the default microphone input device for a recording, rather than relying on a device list cached since process/library startup, to reduce the chance of opening the input stream against a stale device reference.

#### Scenario: Device list refreshed on every recording start
- **WHEN** a recording is started (via the CLI or the menu bar app)
- **THEN** the audio library's device list is refreshed before the default microphone device index is read and the input stream is opened

#### Scenario: Refresh does not change behavior when the device list is already current
- **WHEN** a recording is started and the system's audio devices have not changed since the last refresh
- **THEN** the same default microphone device is selected and the recording starts normally, identical to behavior without the refresh
