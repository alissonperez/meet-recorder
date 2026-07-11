## ADDED Requirements

### Requirement: Opt-in meeting-prompt scheduler
The system SHALL run a background scheduler in the menu bar app that watches upcoming calendar events only when the meeting prompt is enabled in config and calendar is configured, and SHALL otherwise remain inactive. The scheduler SHALL never start, stop, or otherwise control recording on its own — any recording start SHALL only happen as a direct result of explicit user confirmation in the start-time modal (see below).

#### Scenario: Meeting prompt enabled
- **WHEN** the menu bar app runs with `autorecord.enabled` true and at least one calendar account configured
- **THEN** a background timer periodically queries upcoming accepted events and drives the upcoming-meeting notification and the start-time confirmation modal

#### Scenario: Meeting prompt disabled or calendar unconfigured
- **WHEN** the meeting prompt is disabled or no calendar is configured
- **THEN** the scheduler performs no calendar queries and the menu bar app behaves exactly as it did before this change

### Requirement: Upcoming-meeting notification
The system SHALL show a notification announcing an upcoming accepted meeting when its start time is within the configured lead time, at most once per event.

#### Scenario: Next meeting is approaching
- **WHEN** an accepted, non-ignored event's start time falls within the configured `notify_before_minutes`
- **THEN** a notification naming the meeting and its start time is shown once for that event

### Requirement: Meeting-start confirmation modal
The system SHALL show a modal dialog (not a passive notification) when an accepted, non-ignored event's start time arrives, stating the meeting's title and start time, and offering the user a choice to start recording or dismiss. The system SHALL start a recording if and only if the user confirms in that dialog.

#### Scenario: User confirms the modal
- **WHEN** an accepted, non-ignored event's start time has arrived and the user confirms the modal (chooses to start recording)
- **THEN** the app starts a recording via the same path as a manual start and updates the menu bar to the recording state

#### Scenario: User dismisses or declines the modal
- **WHEN** the user dismisses the modal or explicitly declines to record
- **THEN** the app does not start a recording and takes no further action for that event

#### Scenario: Meeting starts while already recording
- **WHEN** an event's start time arrives while a recording is already in progress
- **THEN** the app does not show the modal (or shows it with recording-already-in-progress reflected) and never starts a second recording or interrupts the current one

#### Scenario: Event matches an ignore-slug
- **WHEN** an upcoming event's slugified title contains a configured ignore-slug
- **THEN** the app shows neither the upcoming-meeting notification nor the start-time modal for that event

#### Scenario: Modal shown once per event
- **WHEN** an event's start-time modal has already been shown (confirmed or dismissed)
- **THEN** the app does not show the modal again for that same event

### Requirement: Scheduler resilience
The system SHALL keep the scheduler running across transient calendar failures, logging and retrying on the next poll rather than terminating the timer.

#### Scenario: A poll fails to reach the calendar
- **WHEN** a scheduler poll encounters a calendar API or authentication error
- **THEN** the error is logged (and surfaced via notification for persistent failures), the timer keeps running, and the next poll retries
