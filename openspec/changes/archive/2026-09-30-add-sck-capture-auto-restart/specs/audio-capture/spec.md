## ADDED Requirements

### Requirement: Unexpectedly stopped system-audio capture is automatically restarted
The system SHALL attempt to restart system-audio capture when the ScreenCaptureKit stream stops on its own during an in-progress recording, so that a transient interruption costs the recording only the seconds it took to recover rather than the whole remainder of the meeting. Restart attempts SHALL be bounded by an attempt budget and spaced by an exponentially increasing delay, so that a permanent fault stops the retry loop within a bounded time instead of retrying for the rest of the recording. The attempt budget SHALL reset once restarted capture has delivered audio continuously for a sustained period, so that separate interruptions in one long recording are each recovered from, while a stream that dies again immediately after every restart still exhausts the budget. A restarted stream SHALL continue writing to the same in-progress recording as the stream it replaces, and the interval during which no system audio was delivered SHALL be padded with silence by the existing frame-alignment behavior, so that audio captured after the restart stays aligned with the microphone channel at the position it occurred in real time. The system SHALL NOT attempt a restart once the recording has been stopped by the user or the application, nor for a stream that stopped because the application itself requested the stop. This requirement resolves the remaining follow-up of [issue #22](https://github.com/alissonperez/meet-recorder/issues/22).

#### Scenario: Transient interruption is recovered automatically
- **WHEN** the ScreenCaptureKit stream stops on its own during an in-progress recording and a subsequent restart attempt succeeds
- **THEN** system audio is captured again into the same recording, the gap during which no system audio was delivered is padded with silence, and audio captured after the restart is aligned with the microphone channel at the position it occurred in real time

#### Scenario: Restart attempts back off and are bounded
- **WHEN** the system-audio stream stops unexpectedly and every restart attempt fails
- **THEN** the system makes a bounded number of attempts, each separated by a longer delay than the previous one, and after the budget is exhausted it stops attempting restarts for the remainder of the recording

#### Scenario: Attempt budget resets after sustained healthy capture
- **WHEN** a restart succeeds and the restarted stream then delivers system audio continuously for the sustained healthy period before a later, unrelated unexpected stop occurs
- **THEN** the later interruption is retried with a full attempt budget rather than with the attempts left over from the earlier interruption

#### Scenario: Repeated immediate failure still exhausts the budget
- **WHEN** each restart succeeds but the restarted stream stops again before it has delivered audio for the sustained healthy period
- **THEN** the attempt budget is not reset by those short-lived restarts and the retry loop terminates once the budget is exhausted

#### Scenario: A user-requested stop does not trigger a restart
- **WHEN** the recording is stopped by the user or the application, causing the system-audio stream to stop
- **THEN** no restart is attempted and the recording is saved normally

#### Scenario: Recording remains saveable while a restart is pending
- **WHEN** the user stops the recording while a restart attempt is outstanding
- **THEN** the recording is torn down and saved without waiting indefinitely for the restart, and the saved file's two channels remain frame-aligned

## MODIFIED Requirements

### Requirement: Unexpected ScreenCaptureKit stream stop is detected and surfaced
The system SHALL detect when the ScreenCaptureKit system-audio stream stops on its own during recording (i.e. not as a result of the application calling its own stop function), SHALL NOT attempt to send a redundant stop request to a stream that has already stopped, and SHALL emit a warning identifying the affected recording when such a recording is saved, so the resulting file is not reported as a clean, complete recording. The warning SHALL reflect every unexpected stop that occurred during the recording, not only the most recent one, and SHALL distinguish a recording whose system-audio capture was successfully restarted — which contains a silent gap on the system-audio channel but system audio thereafter — from one whose restart attempts were exhausted, which contains no system audio from the point of failure onward. The warning SHALL NOT describe the saved file as truncated, since the microphone channel is retained for the full recording regardless of when the system-audio stream stopped.

#### Scenario: Unexpected stream stop marks the capture inactive without a duplicate stop error
- **WHEN** the ScreenCaptureKit stream stops on its own during an in-progress recording (e.g. due to an application connection interruption)
- **THEN** the system-audio capture is marked inactive as a result of that stop, and the subsequent call to stop capture for that recording does not attempt to stop the stream again and does not log a "stream already stopped" error

#### Scenario: Saving a recording after an unexpected stop warns the user
- **WHEN** a recording is stopped and saved after its ScreenCaptureKit stream had already stopped unexpectedly partway through
- **THEN** the system emits a warning identifying the saved recording file as having been interrupted, in addition to completing the normal save

#### Scenario: A recovered interruption is reported as a gap, not a loss
- **WHEN** a recording is saved after its system-audio stream stopped unexpectedly and was successfully restarted
- **THEN** the warning states that system audio is missing only for the duration of the interruption and that capture resumed, rather than stating that system audio was lost for the remainder of the recording

#### Scenario: An unrecoverable interruption is reported as a loss
- **WHEN** a recording is saved after its system-audio stream stopped unexpectedly and every restart attempt failed
- **THEN** the warning states that system audio is missing from the point of failure to the end of the recording, and that the microphone channel was preserved for the whole recording

#### Scenario: Multiple interruptions are all reported
- **WHEN** a recording is saved after its system-audio stream stopped unexpectedly more than once, each time followed by a successful restart
- **THEN** the warning reflects that more than one interruption occurred rather than reporting only the last one

#### Scenario: Normal stop is unaffected
- **WHEN** a recording is stopped normally (the ScreenCaptureKit stream did not stop on its own beforehand)
- **THEN** the stream is stopped via the standard stop request and no unexpected-stop warning is emitted
