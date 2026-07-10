# audio-capture Specification

## Purpose
TBD - created by archiving change capture-audio-blackhole. Update Purpose after archive.

## Requirements

### Requirement: Dual-source stereo recording
The system SHALL simultaneously capture audio from the system's default microphone input and from the BlackHole 2ch input, writing each source incrementally to its own temporary file on disk during recording, and SHALL merge them at stop time into a single stereo WAV file where channel 0 contains the microphone signal and channel 1 contains the system-audio signal, without mixing or summing the two signals.

#### Scenario: Recording captures both sources into one file
- **WHEN** a recording is started and later stopped after audio has played through the system and the user has spoken into the microphone
- **THEN** a single `.wav` file is produced with 2 channels, where channel 0 contains the microphone audio and channel 1 contains the system audio

#### Scenario: Recording quality
- **WHEN** a recording is started
- **THEN** audio is captured at a 44.1kHz sample rate

### Requirement: Bounded-memory incremental capture
The system SHALL write captured audio frames for each source (microphone, system-audio) to disk incrementally during recording, rather than accumulating the full recording in memory, so that memory usage during capture does not grow proportionally with recording duration.

#### Scenario: Memory stays bounded during a long recording
- **WHEN** a recording runs continuously for an extended duration (e.g. two hours)
- **THEN** the process's memory usage attributable to captured audio frames does not grow unbounded over the course of the recording, because frames are flushed to per-source temporary files on disk as they arrive instead of being retained in memory for the full session

#### Scenario: Per-source temporary files exist during recording
- **WHEN** a recording is in progress
- **THEN** a temporary mono audio file for the microphone source and a temporary mono audio file for the system-audio source exist on disk and are being appended to, independent of when the recording is eventually stopped

### Requirement: Bounded-memory stereo merge on stop
The system SHALL produce the final stereo WAV file by reading the two per-source temporary files and writing the interleaved stereo output in fixed-size blocks, without loading either full-length source file into memory at once.

#### Scenario: Stop-and-save merges without loading full recordings into memory
- **WHEN** `stop_recording_and_save` is called after a long recording
- **THEN** the final stereo `.wav` file is produced by block-wise reading of the two temporary mono files and block-wise writing of the interleaved result, and the two temporary files are removed after the merge completes successfully

#### Scenario: Shorter source truncates the merge
- **WHEN** the two per-source temporary files differ in length (e.g. one source stopped receiving frames slightly earlier than the other)
- **THEN** the final stereo file's length is truncated to the length of the shorter of the two sources, consistent with existing dual-source recording behavior

### Requirement: Automatic output device switching
The system SHALL automatically switch the macOS default audio output device to the Multi-Output Device when a recording starts, and SHALL restore the audio output device that was active immediately before the recording started when the recording stops.

#### Scenario: Output switched on record start
- **WHEN** a recording is started while the system output is set to some device D
- **THEN** the system output is switched to the Multi-Output Device before capture begins

#### Scenario: Output restored on record stop
- **WHEN** a recording that switched the output from device D to the Multi-Output Device is stopped
- **THEN** the system output is switched back to device D

### Requirement: System-audio silence warning
The system SHALL monitor the RMS signal level of the system-audio (BlackHole) channel while recording, using a bounded rolling buffer that covers only the most recent silence-detection window rather than the full recording history, and SHALL emit a warning log if that channel remains silent (RMS at or near zero) for a sustained period, without stopping the recording.

#### Scenario: Sustained silence on system channel triggers a warning
- **WHEN** a recording is in progress and the system-audio channel has RMS at or near zero for a sustained period
- **THEN** a warning is logged indicating the system audio appears silent, and the recording continues uninterrupted

#### Scenario: Active system audio does not trigger a warning
- **WHEN** a recording is in progress and the system-audio channel has non-trivial RMS
- **THEN** no silence warning is logged

#### Scenario: Silence detection does not require the full recording history
- **WHEN** a recording has been running long enough that its full history would no longer fit comfortably in memory
- **THEN** silence detection continues to function correctly using only a bounded rolling buffer of recent audio, without referencing the full recording history

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
