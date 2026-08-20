## ADDED Requirements

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
