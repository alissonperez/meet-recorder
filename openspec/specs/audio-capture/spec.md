# audio-capture Specification

## Purpose
TBD - created by archiving change capture-audio-blackhole. Update Purpose after archive.

## Requirements

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

### Requirement: System-audio silence warning
The system SHALL monitor the RMS signal level of the system-audio (ScreenCaptureKit) channel while recording, using a bounded rolling buffer that covers only the most recent silence-detection window rather than the full recording history, and SHALL emit a warning if that channel remains silent (RMS at or near zero) for a sustained period, pointing the user at the Screen Recording permission as the likely cause, without stopping the recording. The system SHALL additionally report when a previously warned channel returns to a non-silent level, so a consumer of the warning can clear any alert state it raised.

#### Scenario: Sustained silence on system channel triggers a warning
- **WHEN** a recording is in progress and the system-audio channel has RMS at or near zero for a sustained period
- **THEN** a warning is emitted indicating the system audio appears silent and suggesting the Screen Recording permission be checked, and the recording continues uninterrupted

#### Scenario: Active system audio does not trigger a warning
- **WHEN** a recording is in progress and the system-audio channel has non-trivial RMS
- **THEN** no silence warning is emitted

#### Scenario: Silence detection does not require the full recording history
- **WHEN** a recording has been running long enough that its full history would no longer fit comfortably in memory
- **THEN** silence detection continues to function correctly using only a bounded rolling buffer of recent audio, without referencing the full recording history

#### Scenario: Recovery from silence is reported
- **WHEN** a channel that previously triggered a sustained-silence warning returns to a non-trivial RMS level
- **THEN** the system reports the recovery to the consumer of the silence warning, identifying the recovered channel, so any alert state raised for that channel can be cleared

### Requirement: Microphone silence warning
The system SHALL monitor the RMS signal level of the microphone channel while recording using the same bounded rolling-buffer mechanism used for the system-audio channel, and SHALL emit a warning if the microphone channel remains silent for a sustained period, identifying the microphone (rather than the Screen Recording permission) as the affected source and pointing the user at switching the microphone input device, without stopping the recording.

#### Scenario: Sustained silence on the microphone channel triggers a warning
- **WHEN** a recording is in progress and the microphone channel has RMS at or near zero for a sustained period
- **THEN** a warning is emitted identifying the microphone channel as silent and indicating that the input device can be switched, and the recording continues uninterrupted

#### Scenario: Microphone and system channels warn independently
- **WHEN** one channel is silent for a sustained period while the other channel carries a non-trivial signal
- **THEN** a warning is emitted only for the silent channel, identifying that channel, and no warning is emitted for the active channel

#### Scenario: Active microphone does not trigger a warning
- **WHEN** a recording is in progress and the microphone channel has non-trivial RMS
- **THEN** no microphone silence warning is emitted

### Requirement: Microphone input device can be switched during a recording
The system SHALL allow the microphone input device to be changed while a recording is in progress by pausing microphone capture, enumerating the input devices currently available, and resuming capture against a selected device, writing the resumed audio to the same microphone channel of the same in-progress recording. System-audio capture SHALL continue uninterrupted for the entire duration of the pause, so audio from other participants is not lost while the user selects a device.

#### Scenario: Switching the microphone mid-recording keeps one continuous recording
- **WHEN** the user switches the microphone input device while a recording is in progress
- **THEN** microphone capture resumes on the selected device, its audio is written to the same microphone channel of the same recording, and stopping the recording afterwards produces a single stereo file rather than a new or split recording

#### Scenario: System audio is not interrupted by a microphone switch
- **WHEN** microphone capture is paused for a device switch while a recording is in progress
- **THEN** system-audio capture continues recording throughout the pause, and the audio captured during the pause is present in the saved recording's system-audio channel

#### Scenario: Device list reflects devices connected after the recording started
- **WHEN** an input device is connected after a recording has started and the user opens the microphone switch
- **THEN** the newly connected device appears in the list of selectable input devices

#### Scenario: Abandoning the switch resumes microphone capture
- **WHEN** the user pauses microphone capture for a switch but does not select a device
- **THEN** microphone capture is resumed against the previously used device, or against the current default input device if the previous one is no longer available, and the recording is never left indefinitely without microphone capture

#### Scenario: Resuming against an unusable device does not abort the recording
- **WHEN** resuming microphone capture against a selected device fails (for example, the device does not support the recording's sample rate or channel count)
- **THEN** the failure is reported to the user, microphone capture is resumed against a usable device, and the in-progress recording is not stopped or discarded

### Requirement: Input device enumeration requires paused microphone capture
The system SHALL only enumerate the currently available input devices while microphone capture is paused or not started, because enumeration re-initializes the underlying audio library and invalidates any open input stream. The enumeration function SHALL document this constraint at its definition, and the pause and resume operations SHALL own the refresh so that callers do not have to sequence it themselves.

#### Scenario: Enumeration during active capture is prevented
- **WHEN** input device enumeration is requested while microphone capture is active
- **THEN** the system does not re-initialize the audio library and does not invalidate the active input stream

#### Scenario: Enumeration while paused returns the current device list
- **WHEN** input device enumeration is requested while microphone capture is paused
- **THEN** the audio library's device list is refreshed and the current set of input devices is returned

### Requirement: Capture channels stay frame-aligned with each other
The system SHALL keep the microphone and system-audio channels frame-aligned with each other for the whole recording by padding whichever channel has produced fewer frames with silence, in either direction, until it matches the other — including while microphone capture is paused for a device switch, when frames are dropped because a writer queue is full, and when the system-audio stream has stopped early and is no longer delivering audio. Padding SHALL be written continuously as the shortfall accrues rather than computed and applied only when capture resumes, so the temporary files on disk are frame-aligned at every instant. This is required because the stereo merge combines the two temporary files by position rather than by timestamp, so an unpadded shortfall both shifts every subsequent frame and truncates the output to the shorter channel. Padding SHALL NOT suppress, replace, or delay any warning about the underlying fault.

#### Scenario: Microphone pause does not desynchronize the saved recording
- **WHEN** microphone capture is paused for a period during a recording and then resumed, and the recording is stopped and saved
- **THEN** audio captured after the pause is aligned with the system-audio channel at the same position it occurred in real time, and the microphone channel contains silence for the duration of the pause

#### Scenario: Padding accrues during the pause rather than at resume
- **WHEN** microphone capture has been paused for a period and the in-progress temporary files are inspected before capture resumes
- **THEN** the microphone temporary file has already been padded to match the frames written to the system-audio temporary file

#### Scenario: A crash during a pause leaves a recoverable aligned recording
- **WHEN** the application terminates unexpectedly while microphone capture is paused, and the resulting orphan recording is later recovered
- **THEN** the recovered file's two channels are aligned, with silence on the microphone channel for the paused period

#### Scenario: Dropped frames on either channel are padded
- **WHEN** frames on either channel are dropped during a recording because that channel's writer queue is full
- **THEN** that channel is padded so it remains frame-aligned with the other, and audio after the drop is not shifted relative to the other channel

#### Scenario: An early system-audio stream stop no longer truncates the recording
- **WHEN** the system-audio stream stops unexpectedly partway through a recording and the microphone continues capturing until the user stops the recording
- **THEN** the system-audio channel is padded with silence for the remainder of the recording, and the saved file retains the full microphone audio captured after the stream stopped rather than being truncated at the point of failure

#### Scenario: Padding does not suppress the unexpected-stop warning
- **WHEN** a recording is saved after its system-audio stream stopped unexpectedly and the system-audio channel was padded to full length
- **THEN** the existing unexpected-stop warning is still emitted for that recording

### Requirement: Microphone callback status flags are surfaced
The system SHALL log the status flags reported by the audio library's microphone input callback (such as input overflow, input underflow, or an invalidated device) instead of discarding them, so that microphone capture problems leave a diagnostic trace.

#### Scenario: Input callback reports a status flag
- **WHEN** the microphone input callback is invoked with a non-empty status value during a recording
- **THEN** the status is logged as a warning identifying the microphone source, and the recording continues

#### Scenario: Normal callbacks are not logged
- **WHEN** the microphone input callback is invoked with an empty status value
- **THEN** no status warning is logged

### Requirement: Recording file output location
The system SHALL save completed recordings as `.wav` files in the `~/MeetRecordings` directory, named using a timestamp of when the recording started, not when it was stopped or saved.

#### Scenario: Recording saved with timestamped filename
- **WHEN** a recording is stopped and saved
- **THEN** the resulting file is written under `~/MeetRecordings/` with a filename derived from the recording's start timestamp (e.g. `2026-07-09_14-30.wav`)

#### Scenario: Long recording keeps its start-time filename
- **WHEN** a recording runs long enough that the wall-clock time at stop differs from the wall-clock time at start (e.g. by more than an hour, or across midnight)
- **THEN** the saved filename still reflects the moment the recording started, not the moment it was stopped

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

### Requirement: Microphone device list refreshed before capture starts
The system SHALL refresh the underlying audio library's device list immediately before selecting and opening the default microphone input device for a recording, rather than relying on a device list cached since process/library startup, to reduce the chance of opening the input stream against a stale device reference.

#### Scenario: Device list refreshed on every recording start
- **WHEN** a recording is started (via the CLI or the menu bar app)
- **THEN** the audio library's device list is refreshed before the default microphone device index is read and the input stream is opened

#### Scenario: Refresh does not change behavior when the device list is already current
- **WHEN** a recording is started and the system's audio devices have not changed since the last refresh
- **THEN** the same default microphone device is selected and the recording starts normally, identical to behavior without the refresh

### Requirement: Unexpected ScreenCaptureKit stream stop is detected and surfaced
The system SHALL detect when the ScreenCaptureKit system-audio stream stops on its own during recording (i.e. not as a result of the application calling its own stop function), SHALL NOT attempt to send a redundant stop request to a stream that has already stopped, and SHALL emit a warning identifying the affected recording when such a recording is saved, so the resulting file is not reported as a clean, complete recording.

#### Scenario: Unexpected stream stop marks the capture inactive without a duplicate stop error
- **WHEN** the ScreenCaptureKit stream stops on its own during an in-progress recording (e.g. due to an application connection interruption)
- **THEN** the system-audio capture is marked inactive as a result of that stop, and the subsequent call to stop capture for that recording does not attempt to stop the stream again and does not log a "stream already stopped" error

#### Scenario: Saving a recording after an unexpected stop warns the user
- **WHEN** a recording is stopped and saved after its ScreenCaptureKit stream had already stopped unexpectedly partway through
- **THEN** the system emits a warning identifying the saved recording file as having ended early, in addition to completing the normal save

#### Scenario: Normal stop is unaffected
- **WHEN** a recording is stopped normally (the ScreenCaptureKit stream did not stop on its own beforehand)
- **THEN** the stream is stopped via the standard stop request and no unexpected-stop warning is emitted
