## MODIFIED Requirements

### Requirement: Opt-in meeting-prompt scheduler
The system SHALL run two independent background timers in the menu bar app, active only when the meeting prompt is enabled in config and calendar is configured, and SHALL otherwise remain inactive: a calendar-poll timer that fetches upcoming accepted events from Google Calendar on `autorecord.calendar_poll_interval_minutes`, and a meeting-check timer that evaluates the most recently fetched events (without querying Google Calendar) on the independent, finer-grained `autorecord.check_interval_seconds`. The scheduler SHALL never start, stop, or otherwise control recording on its own — any recording start SHALL only happen as a direct result of explicit user confirmation in the start-time modal (see below).

#### Scenario: Meeting prompt enabled
- **WHEN** the menu bar app runs with `autorecord.enabled` true and at least one calendar account configured
- **THEN** the calendar-poll timer periodically queries upcoming accepted events and the meeting-check timer periodically evaluates those events to drive the upcoming-meeting notification and the start-time confirmation modal

#### Scenario: Meeting prompt disabled or calendar unconfigured
- **WHEN** the meeting prompt is disabled or no calendar is configured
- **THEN** neither timer runs, no calendar queries happen, and the menu bar app behaves exactly as it did before this change

#### Scenario: Meeting-check runs independently of calendar polling
- **WHEN** `autorecord.check_interval_seconds` is configured to a value shorter than `autorecord.calendar_poll_interval_minutes` converted to seconds
- **THEN** the meeting-check timer fires at its own configured cadence, evaluating the events fetched by the most recent calendar poll, without triggering an additional Google Calendar request

#### Scenario: App starts mid-meeting
- **WHEN** the menu bar app starts while an accepted, non-ignored event's start time has already passed (and it is not older than `autorecord.max_meeting_age_minutes`)
- **THEN** an initial calendar fetch and an initial meeting-check both run immediately on startup, so the start-time modal is not delayed by a full `check_interval_seconds` or `calendar_poll_interval_minutes` wait

### Requirement: Meeting-start confirmation modal
The system SHALL show a modal dialog (not a passive notification) when an accepted, non-ignored event's start time has arrived and is no older than `autorecord.max_meeting_age_minutes`, stating the meeting's title and start time, and offering the user a choice to start recording or dismiss. The system SHALL start a recording if and only if the user confirms in that dialog.

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

#### Scenario: Meeting started too long ago
- **WHEN** an accepted, non-ignored event's start time is more than `autorecord.max_meeting_age_minutes` in the past (e.g. the app was just launched, or woke from sleep, long after the meeting began)
- **THEN** the app does not show the start-time modal for that event, and does not mark the event as having been prompted
