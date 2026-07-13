## MODIFIED Requirements

### Requirement: Recording-anchored event lookup
The system SHALL find the calendar event matching a recording by querying all configured accounts over a window anchored on the recording's start time, SHALL prefer events the user has accepted ("Yes") over events the user has tentatively responded to ("Maybe") or left unanswered, and SHALL return the single qualifying event whose start time is closest to the recording's start time, or none when no event qualifies.

#### Scenario: Event found within the window
- **WHEN** a recording's start time falls within the configured match window of an accepted event on any configured account
- **THEN** that event (title, source account, start/end, and attendee display names) is returned as the match

#### Scenario: Recording started after the meeting began
- **WHEN** a recording is started up to the configured "before" window (e.g. ~30 minutes) after an event's start time
- **THEN** that event still falls within the window and is returned as the match

#### Scenario: Closest accepted event wins across accounts
- **WHEN** multiple accepted events across one or more accounts fall within the window
- **THEN** the accepted event whose start time has the smallest absolute distance to the recording's start time is returned, regardless of which account it came from

#### Scenario: Accepted event preferred over a closer tentative event
- **WHEN** both an accepted ("Yes") event and a tentative ("Maybe") event fall within the window, and the tentative event's start time is closer to the recording's start time than the accepted event's
- **THEN** the accepted event is returned as the match, not the closer tentative event

#### Scenario: Tentative event used when no accepted event qualifies
- **WHEN** no accepted event falls within the window but one or more tentative events do
- **THEN** the tentative event whose start time is closest to the recording's start time is returned as the match

#### Scenario: No qualifying event
- **WHEN** no event survives filtering within the window, or calendar is unconfigured, or the lookup errors
- **THEN** no match is returned and the caller proceeds without calendar data
