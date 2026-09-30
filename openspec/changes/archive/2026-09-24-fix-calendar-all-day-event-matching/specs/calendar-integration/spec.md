## MODIFIED Requirements

### Requirement: Recording-anchored event lookup
The system SHALL find the calendar event matching a recording by querying all configured accounts over a window anchored on the recording's start time, SHALL only consider candidates whose parsed start time falls within that window, SHALL prefer events the user has accepted ("Yes") over events the user has tentatively responded to ("Maybe") or left unanswered, and SHALL return the single qualifying event whose start time is closest to the recording's start time, or none when no event qualifies.

#### Scenario: Event found within the window
- **WHEN** a recording's start time falls within the configured match window of an accepted event on any configured account
- **THEN** that event (title, description, source account, start/end, and attendee display names) is returned as the match

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

#### Scenario: Event without a description
- **WHEN** a matched event's API payload has no `description` field
- **THEN** the returned event has no description (absent, not an empty string), and callers that build prompt context from it treat it the same as an event with no attendees

#### Scenario: Candidate outside the configured match window is excluded
- **WHEN** the calendar API returns an event that overlaps the queried time range but whose parsed start time falls outside `[anchor - calendar_match_before_minutes, anchor + calendar_match_after_minutes]`
- **THEN** that event is not considered a candidate for matching, even if it is the only event the API returned

#### Scenario: No match when only all-day events are returned
- **WHEN** the only event(s) the calendar API returns for the anchor window are all-day events
- **THEN** `find_event` returns no match rather than matching one of the all-day events

### Requirement: RSVP and ignore-slug filtering
The system SHALL exclude from candidacy any event whose slugified title contains a configured ignore-slug, and SHALL exclude from candidacy any all-day event (an event whose `start` payload has a `date` field and no `dateTime` field), in every lookup that applies this filtering: `find_event`, `upcoming_events`, and `past_events`. For recording-anchored lookup (`find_event`) and upcoming-event lookup (`upcoming_events`), the system SHALL additionally exclude any event the user has declined. For past-event lookup used by Meet-transcript ingestion (`past_events`), declined events SHALL remain candidates — RSVP status is not used to exclude them.

#### Scenario: Declined event excluded from recording-anchored and upcoming-event lookup
- **WHEN** a candidate event lists the user as an attendee with response status "declined", and the lookup is `find_event` or `upcoming_events`
- **THEN** that event is excluded from matching

#### Scenario: Declined event retained for past-event/Meet-transcript lookup
- **WHEN** a candidate event lists the user as an attendee with response status "declined", and the lookup is `past_events`
- **THEN** that event remains a candidate and is evaluated for transcript/Gemini-notes attachments like any other occurrence

#### Scenario: Ignored title excluded everywhere
- **WHEN** a candidate event's slugified title contains any entry from the configured ignore-slug list
- **THEN** that event is excluded from matching regardless of which lookup (`find_event`, `upcoming_events`, or `past_events`) is being performed

#### Scenario: Event without attendee response accepted
- **WHEN** a candidate event has no attendee list or no explicit response for the user
- **THEN** it is not excluded on RSVP grounds and remains a candidate

#### Scenario: All-day event excluded from every lookup
- **WHEN** a candidate event's `start` payload contains a `date` field with no `dateTime` field (an all-day event)
- **THEN** that event is excluded from candidacy for `find_event`, `upcoming_events`, and `past_events`, regardless of RSVP status or ignore-slug match
