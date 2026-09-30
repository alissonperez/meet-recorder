## ADDED Requirements

### Requirement: System-audio restart supervision is verified
The test suite SHALL verify the system-audio restart behavior of `meet_recorder.recorder` with the ScreenCaptureKit capture layer stubbed, so no real screen-capture stream, audio device, or timing-dependent sleep is exercised: a successful restart continues writing to the same in-progress recording, the retry schedule is bounded and increases its delay between attempts, an exhausted budget stops further attempts, sustained healthy capture resets the budget, a short-lived restart does not reset it, and no restart is attempted after a user-requested stop. The backoff delays SHALL be verifiable without the test waiting real time for them.

#### Scenario: Successful restart continues the same recording
- **WHEN** the stubbed capture layer reports an unexpected stop and the next start attempt succeeds
- **THEN** the test asserts that capture was started again and that audio delivered afterwards is written to the same in-progress recording as before the interruption

#### Scenario: Retry schedule is bounded and backs off
- **WHEN** every stubbed restart attempt fails after an unexpected stop
- **THEN** the test asserts that the number of attempts does not exceed the configured budget and that each successive attempt's delay is longer than the previous one

#### Scenario: Exhausted budget stops further attempts
- **WHEN** the stubbed restart attempts have exhausted the budget
- **THEN** the test asserts that no further start call is made for the remainder of the recording

#### Scenario: Sustained healthy capture resets the budget
- **WHEN** a stubbed restart succeeds and the restarted capture is reported healthy for the sustained period before a later unexpected stop
- **THEN** the test asserts that the later interruption is retried with a full budget

#### Scenario: A short-lived restart does not reset the budget
- **WHEN** a stubbed restart succeeds but the capture stops again before the sustained healthy period elapses
- **THEN** the test asserts that the remaining budget was not restored and the retry loop still terminates

#### Scenario: No restart after a user-requested stop
- **WHEN** the recording is stopped through the normal stop-and-save path
- **THEN** the test asserts that the capture layer's start function is not called again

#### Scenario: Save-time warning distinguishes recovery from loss
- **WHEN** a recording is saved after an interruption that was recovered, and separately after one whose restarts were exhausted
- **THEN** the test asserts that the emitted warning text differs between the two cases and that neither describes the saved file as truncated

### Requirement: Menu bar system-audio interruption notifications are verified
The test suite SHALL verify that the menu bar app's system-audio interruption and restoration hooks each produce a native notification, with the notification API and the main-thread marshalling stubbed so no AppKit call or real notification occurs during the test run.

#### Scenario: Interruption hook notifies
- **WHEN** the menu bar app's system-audio interruption hook is invoked
- **THEN** the test asserts that a notification was requested whose text identifies the interruption

#### Scenario: Restoration hook notifies
- **WHEN** the menu bar app's system-audio restoration hook is invoked
- **THEN** the test asserts that a notification was requested whose text identifies the restoration
