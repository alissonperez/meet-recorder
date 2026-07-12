# audio-capture Delta: Migrate system-audio capture to ScreenCaptureKit

## ADDED Requirements

### Requirement: System-audio capture prerequisites
The system SHALL capture system audio via ScreenCaptureKit, which requires macOS 13 or later and the macOS Screen Recording permission granted to the process that runs the application, and SHALL NOT require any virtual audio driver (such as BlackHole), any Multi-Output Device configuration, or the `SwitchAudioSource` binary.

#### Scenario: Recording works without BlackHole installed
- **WHEN** a recording is started on a machine that has Screen Recording permission granted but no BlackHole driver, no Multi-Output Device, and no `SwitchAudioSource` binary installed
- **THEN** the recording starts successfully and captures both microphone and system audio

#### Scenario: Missing Screen Recording permission produces a clear failure signal
- **WHEN** a recording is started while the running process lacks Screen Recording permission
- **THEN** the system either raises a clear error at start, or — if the stream starts but delivers no audio buffers — emits a warning that points at the Screen Recording permission, rather than failing silently

### Requirement: System volume remains user-controllable during recording
The system SHALL leave the macOS output-device configuration and routing untouched while recording, so that the user can adjust system volume normally for the entire duration of a recording.

#### Scenario: Volume adjusted mid-recording
- **WHEN** the user changes the system output volume while a recording is in progress
- **THEN** the audible output volume changes normally, the recording continues uninterrupted, and the captured system-audio signal is unaffected by the volume change being possible

## MODIFIED Requirements

### Requirement: Dual-source stereo recording
The system SHALL simultaneously capture audio from the system's default microphone input (via the audio input API) and from the system-audio output (via a ScreenCaptureKit stream with audio capture enabled), converting the system-audio stream's Float32 interleaved buffers to mono, writing each source incrementally to its own temporary file on disk during recording, and SHALL merge them at stop time into a single stereo WAV file where channel 0 contains the microphone signal and channel 1 contains the system-audio signal, without mixing or summing the two signals.

#### Scenario: Recording captures both sources into one file
- **WHEN** a recording is started and later stopped after audio has played through the system and the user has spoken into the microphone
- **THEN** a single `.wav` file is produced with 2 channels, where channel 0 contains the microphone audio and channel 1 contains the system audio

#### Scenario: Recording quality
- **WHEN** a recording is started
- **THEN** audio is captured at a 16kHz sample rate on both channels

#### Scenario: Multi-channel system audio is downmixed to mono
- **WHEN** the ScreenCaptureKit stream delivers multi-channel (e.g. stereo) Float32 audio buffers
- **THEN** the channels are downmixed into a single mono signal before being written to the system-audio temporary file

### Requirement: System-audio silence warning
The system SHALL monitor the RMS signal level of the system-audio (ScreenCaptureKit) channel while recording, using a bounded rolling buffer that covers only the most recent silence-detection window rather than the full recording history, and SHALL emit a warning if that channel remains silent (RMS at or near zero) for a sustained period, pointing the user at the Screen Recording permission as the likely cause, without stopping the recording.

#### Scenario: Sustained silence on system channel triggers a warning
- **WHEN** a recording is in progress and the system-audio channel has RMS at or near zero for a sustained period
- **THEN** a warning is emitted indicating the system audio appears silent and suggesting the Screen Recording permission be checked, and the recording continues uninterrupted

#### Scenario: Active system audio does not trigger a warning
- **WHEN** a recording is in progress and the system-audio channel has non-trivial RMS
- **THEN** no silence warning is emitted

#### Scenario: Silence detection does not require the full recording history
- **WHEN** a recording has been running long enough that its full history would no longer fit comfortably in memory
- **THEN** silence detection continues to function correctly using only a bounded rolling buffer of recent audio, without referencing the full recording history

## REMOVED Requirements

### Requirement: Automatic output device switching
**Reason**: ScreenCaptureKit captures system audio directly from the OS without rerouting output through a Multi-Output Device, so there is no device switch to perform or restore, and system volume stays controllable during recording.
**Migration**: No user action needed to record. The Multi-Output Device and BlackHole driver become unused and may be deleted from Audio MIDI Setup; the `MULTI_OUTPUT_DEVICE_NAME` environment variable is ignored; the `SwitchAudioSource` binary is no longer invoked. Screen Recording permission must be granted to the running process instead.
