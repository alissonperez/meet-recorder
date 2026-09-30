## ADDED Requirements

### Requirement: Whole-recording pause and resume
The system SHALL allow an in-progress recording to be paused and later resumed as the same recording. While the recording is paused, it SHALL capture neither microphone nor system audio, SHALL append no artificial silence for the paused interval, and SHALL suspend silence monitoring and initial-buffer checks so the absence of audio does not produce warnings. Resuming SHALL restore both channels to capture, and audio recorded after resumption SHALL remain in the same stereo output file as audio recorded before the pause. Resume SHALL be transactional: both channels SHALL become active together, and failure to restore either channel SHALL leave both channels stopped and the session paused without losing its temporary audio. Capture lifecycle transitions SHALL be serialized so a concurrent or stale operation cannot reactivate a finalized session. This whole-recording pause SHALL be distinct from and mutually exclusive with the microphone-only pause used to change input devices, during which system-audio capture continues.

#### Scenario: Pausing excludes both audio channels
- **WHEN** the user pauses an in-progress recording
- **THEN** neither microphone audio nor system audio is captured until the user resumes the recording

#### Scenario: Resuming preserves one recording without a silent pause interval
- **WHEN** the user pauses an in-progress recording, resumes it, and later saves it
- **THEN** the saved stereo file contains the audio captured before and after the pause as one recording and contains no padding or captured audio for the paused interval

#### Scenario: Silence monitoring is inactive while paused
- **WHEN** an in-progress recording remains paused longer than the configured silence-warning period
- **THEN** no microphone or system-audio silence warning is emitted solely because recording is paused

#### Scenario: Initial system-buffer check excludes the paused interval
- **WHEN** the recording is paused before its first system-audio buffer arrives and an old initial-buffer timer races with cancellation
- **THEN** the old timer emits no warning, and a successful resume starts a new complete initial-buffer window

#### Scenario: Microphone device switching remains a partial pause
- **WHEN** microphone capture is paused to switch its input device during an in-progress recording
- **THEN** system-audio capture continues and the whole-recording paused state is not entered

#### Scenario: Whole-recording pause does not overlap microphone switching
- **WHEN** whole-recording pause is requested while a microphone-device switch is in progress
- **THEN** the request has no effect and microphone switching remains the only active transition

#### Scenario: Pause and resume are guarded by recording state
- **WHEN** pause is requested while idle or already paused, or resume is requested while actively recording or idle
- **THEN** the request has no effect on capture state or the in-progress recording

#### Scenario: Resume rolls back a partial source start
- **WHEN** one capture source starts during resume but restoring the other source fails
- **THEN** the newly started source is stopped, neither new handle is published, the session remains paused, and its temporary audio remains available for another resume or finalization attempt

#### Scenario: Resume falls back after the previous microphone is disconnected
- **WHEN** the microphone used before the pause can no longer be opened during resume but a default input device is available
- **THEN** the audio device list is refreshed, capture resumes on the current default microphone together with system audio, the selected microphone is updated, and the fallback is reported to the caller

#### Scenario: Resume remains paused when no microphone can be restored
- **WHEN** neither the previous microphone nor the current default microphone can be opened during resume
- **THEN** system-audio capture is not left running, the session remains paused with its temporary audio intact, and the failure is reported

#### Scenario: Lifecycle transitions cannot resurrect a finalized session
- **WHEN** pause, resume, save, discard, or microphone-only transition requests overlap
- **THEN** the capture module executes lifecycle changes serially, rejects combinations that are invalid after the preceding transition, and never starts a source after that session has been saved or discarded

#### Scenario: Saving or discarding while paused is safe
- **WHEN** the user saves or discards an in-progress recording while it is paused
- **THEN** both capture channels are finalized safely and the save or discard has the same outcome as for an actively recording session
