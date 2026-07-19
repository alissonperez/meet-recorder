## MODIFIED Requirements

### Requirement: Meeting-start confirmation modal
The system SHALL show a modal dialog (not a passive notification) when an accepted, non-ignored event's start time has arrived at least `autorecord.prompt_delay_seconds` ago and is no older than `autorecord.max_meeting_age_minutes`, stating the meeting's title and start time, and offering the user a choice to start recording or dismiss. The system SHALL start a recording if and only if the user confirms in that dialog.

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

#### Scenario: Meeting started but the prompt delay hasn't elapsed yet
- **WHEN** an accepted, non-ignored event's start time has passed but less than `autorecord.prompt_delay_seconds` have elapsed since then
- **THEN** the app does not show the start-time modal for that event, and does not mark the event as having been prompted, so it is re-evaluated on the next meeting-check tick

#### Scenario: Prompt delay defaults to zero
- **WHEN** `autorecord.prompt_delay_seconds` is not set in config
- **THEN** the app shows the start-time modal as soon as the event's start time has arrived, identical to behavior before this setting existed
