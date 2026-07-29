## Why

Meet-transcript ingestion (`meet_transcripts` / the menu bar poller) currently reuses the same RSVP filter as live auto-record: any event with response status "declined" is dropped before its attachments are even inspected. In practice, RSVP status often doesn't reflect whether the meeting was actually attended (late accepts, meetings joined despite a stale decline, etc.), so a real transcript/Gemini-notes doc sitting on a declined event is silently skipped and never surfaces in the vault — the only current workaround is manually fixing the RSVP and re-running ingestion.

## What Changes

- Past-event lookup for Meet-transcript ingestion (`calendar.past_events`) SHALL no longer exclude declined events from candidacy; declined events are still subject to the existing ignore-slug title filter.
- Live auto-record event lookup (`calendar.upcoming_events`) and recording-anchored matching (`calendar.find_event`) keep excluding declined events — this change is scoped to already-finished occurrences being ingested for transcripts/notes, not to prompting the user to record a meeting they declined.
- `meet_ingest.ingest_once` continues to gate ingestion on transcript/Gemini-notes docs actually being attached, so declined events with no attachments still produce no output, unchanged from today.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `calendar-integration`: the "RSVP and ignore-slug filtering" requirement's decline exclusion no longer applies uniformly to all candidacy lookups — it's scoped out for past-event/meet-transcript-ingest lookup while remaining in force for upcoming-event and recording-anchored lookup.

## Impact

- `meet_recorder/calendar.py`: `_eligible_events`, `past_events`, `upcoming_events` — decline filtering needs to become conditional per caller instead of a single shared filter.
- `tests/test_calendar.py`: add/update coverage for declined events surviving `past_events` while still being excluded from `upcoming_events`/`find_event`.
- No config or CLI surface changes; behavior-only fix.
