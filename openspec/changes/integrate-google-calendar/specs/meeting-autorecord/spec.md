## ADDED Requirements

### Requirement: Opt-in auto-record scheduler
The system SHALL run a background scheduler in the menu bar app that watches upcoming calendar events only when auto-record is enabled in config and calendar is configured, and SHALL otherwise remain inactive.

#### Scenario: Auto-record enabled
- **WHEN** the menu bar app runs with `autorecord.enabled` true and at least one calendar account configured
- **THEN** a background timer periodically queries upcoming accepted events and drives notifications and auto-start

#### Scenario: Auto-record disabled or calendar unconfigured
- **WHEN** auto-record is disabled or no calendar is configured
- **THEN** the scheduler performs no calendar queries and the menu bar app behaves exactly as it did before this change

### Requirement: Upcoming-meeting notification
The system SHALL show a notification announcing an upcoming accepted meeting when its start time is within the configured lead time, at most once per event.

#### Scenario: Next meeting is approaching
- **WHEN** an accepted, non-ignored event's start time falls within the configured `notify_before_minutes`
- **THEN** a notification naming the meeting and its start time is shown once for that event

### Requirement: Automatic recording start
The system SHALL automatically start a recording at an accepted, non-ignored event's start time when no recording is already in progress, and SHALL show a notification indicating recording has started for that meeting.

#### Scenario: Meeting starts and no recording is active
- **WHEN** an accepted, non-ignored event's start time has arrived and no recording is in progress
- **THEN** the app starts a recording via the same path as a manual start, updates the menu bar to the recording state, and shows a notification naming the meeting being recorded

#### Scenario: Meeting starts while already recording
- **WHEN** an event's start time arrives while a recording is already in progress
- **THEN** the app does not start a second recording and does not interrupt the current one

#### Scenario: Event matches an ignore-slug
- **WHEN** an upcoming event's slugified title contains a configured ignore-slug
- **THEN** the app neither notifies about nor auto-starts a recording for that event

### Requirement: End-of-meeting notification without auto-stop
The system SHALL notify the user when an auto-started recording passes its event's scheduled end time, and SHALL NOT stop the recording automatically.

#### Scenario: Scheduled end time reached
- **WHEN** a recording that was auto-started for an event passes that event's end time
- **THEN** a notification is shown once indicating the scheduled meeting time has ended, and the recording continues until the user stops it manually

### Requirement: Scheduler resilience
The system SHALL keep the scheduler running across transient calendar failures, logging and retrying on the next poll rather than terminating the timer.

#### Scenario: A poll fails to reach the calendar
- **WHEN** a scheduler poll encounters a calendar API or authentication error
- **THEN** the error is logged (and surfaced via notification for persistent failures), the timer keeps running, and the next poll retries
