## MODIFIED Requirements

### Requirement: RSVP and ignore-slug filtering
The system SHALL exclude from candidacy any event whose slugified title contains a configured ignore-slug. For recording-anchored lookup (`find_event`) and upcoming-event lookup (`upcoming_events`), the system SHALL additionally exclude any event the user has declined. For past-event lookup used by Meet-transcript ingestion (`past_events`), declined events SHALL remain candidates — RSVP status is not used to exclude them.

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
