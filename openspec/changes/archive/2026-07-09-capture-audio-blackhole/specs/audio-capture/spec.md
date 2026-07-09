## ADDED Requirements

### Requirement: Dual-source stereo recording
The system SHALL simultaneously capture audio from the system's default microphone input and from the BlackHole 2ch input, and SHALL write them to a single stereo WAV file where channel 0 contains the microphone signal and channel 1 contains the system-audio signal, without mixing or summing the two signals.

#### Scenario: Recording captures both sources into one file
- **WHEN** a recording is started and later stopped after audio has played through the system and the user has spoken into the microphone
- **THEN** a single `.wav` file is produced with 2 channels, where channel 0 contains the microphone audio and channel 1 contains the system audio

#### Scenario: Recording quality
- **WHEN** a recording is started
- **THEN** audio is captured at a 44.1kHz sample rate

### Requirement: Automatic output device switching
The system SHALL automatically switch the macOS default audio output device to the Multi-Output Device when a recording starts, and SHALL restore the audio output device that was active immediately before the recording started when the recording stops.

#### Scenario: Output switched on record start
- **WHEN** a recording is started while the system output is set to some device D
- **THEN** the system output is switched to the Multi-Output Device before capture begins

#### Scenario: Output restored on record stop
- **WHEN** a recording that switched the output from device D to the Multi-Output Device is stopped
- **THEN** the system output is switched back to device D

### Requirement: System-audio silence warning
The system SHALL monitor the RMS signal level of the system-audio (BlackHole) channel while recording, and SHALL emit a warning log if that channel remains silent (RMS at or near zero) for a sustained period, without stopping the recording.

#### Scenario: Sustained silence on system channel triggers a warning
- **WHEN** a recording is in progress and the system-audio channel has RMS at or near zero for a sustained period
- **THEN** a warning is logged indicating the system audio appears silent, and the recording continues uninterrupted

#### Scenario: Active system audio does not trigger a warning
- **WHEN** a recording is in progress and the system-audio channel has non-trivial RMS
- **THEN** no silence warning is logged

### Requirement: Recording file output location
The system SHALL save completed recordings as `.wav` files in the `~/MeetRecordings` directory, named using a timestamp of when the recording was made.

#### Scenario: Recording saved with timestamped filename
- **WHEN** a recording is stopped and saved
- **THEN** the resulting file is written under `~/MeetRecordings/` with a filename derived from the recording's timestamp (e.g. `2026-07-09_14-30.wav`)

### Requirement: CLI test entrypoint for recording
The system SHALL expose a CLI command that records for a caller-specified duration and saves the result, for manual end-to-end testing of the capture flow independent of any future UI.

#### Scenario: Fixed-duration recording via CLI
- **WHEN** the `record` CLI command is invoked with a duration of N seconds
- **THEN** the system records for approximately N seconds, switching and restoring the output device as usual, and saves the resulting file to `~/MeetRecordings/`

### Requirement: UI-agnostic capture module
The system SHALL implement the recording start/stop/save/device-switching logic in a module with no dependency on any specific caller (CLI or otherwise), so it can be reused by future interfaces without modification.

#### Scenario: Capture logic callable without the CLI handler
- **WHEN** the recording start, stop-and-save, and device-switching functions are called directly (not through the `record` CLI command)
- **THEN** they perform the full capture/switch/save behavior identically to when invoked via the CLI handler
