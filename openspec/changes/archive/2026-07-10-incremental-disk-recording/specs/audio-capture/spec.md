## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Dual-source stereo recording
The system SHALL simultaneously capture audio from the system's default microphone input and from the BlackHole 2ch input, writing each source incrementally to its own temporary file on disk during recording, and SHALL merge them at stop time into a single stereo WAV file where channel 0 contains the microphone signal and channel 1 contains the system-audio signal, without mixing or summing the two signals.

#### Scenario: Recording captures both sources into one file
- **WHEN** a recording is started and later stopped after audio has played through the system and the user has spoken into the microphone
- **THEN** a single `.wav` file is produced with 2 channels, where channel 0 contains the microphone audio and channel 1 contains the system audio

#### Scenario: Recording quality
- **WHEN** a recording is started
- **THEN** audio is captured at a 44.1kHz sample rate

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
