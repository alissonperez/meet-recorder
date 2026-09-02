## ADDED Requirements

### Requirement: System-audio capture interruption notification
The system SHALL show a native macOS notification when system-audio capture is interrupted during a recording started from the menu bar, indicating that system audio has stopped and that recovery is being attempted, and SHALL show a further notification when system-audio capture is restored, so the user learns mid-meeting both that the problem occurred and that it cleared. The recording SHALL continue uninterrupted in both cases, and neither notification SHALL replace or suppress the sustained-silence notification that applies when capture is not restored.

#### Scenario: Interruption triggers a notification
- **WHEN** a recording started from the menu bar is in progress and its system-audio capture stops unexpectedly
- **THEN** a native macOS notification is shown stating that system audio was interrupted and that reconnection is being attempted, and the recording continues

#### Scenario: Restoration triggers a notification
- **WHEN** system-audio capture is successfully restarted after an interruption during a recording started from the menu bar
- **THEN** a native macOS notification is shown stating that system audio was restored

#### Scenario: An unrecovered interruption still reaches the sustained-silence notification
- **WHEN** system-audio capture is interrupted and every restart attempt fails, leaving the system-audio channel silent for the sustained period defined by the capture module
- **THEN** the existing system-audio sustained-silence notification is shown in addition to the interruption notification

#### Scenario: Notifications are shown without blocking capture
- **WHEN** the capture module reports an interruption or a restoration from its own background thread
- **THEN** the notification is delivered on the main thread and the reporting thread is not blocked waiting for it
