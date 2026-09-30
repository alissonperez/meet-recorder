## Why

Recording-anchored calendar matching (`calendar.find_event`) can return a
spurious all-day event instead of no match. When a user has only some of
their Google accounts connected (e.g. a personal account but not their work
account), and no real timed meeting exists on any connected account near the
recording's start time, `_find_event` still picks the closest candidate the
API returned — and Google's Calendar API returns all-day events for any
query window that touches that calendar date at all, regardless of how
narrow the configured match window is. `_parse_boundary` treats an all-day
event's `date` field as local midnight, so its "distance" from the anchor is
computed against a fabricated time, not a real one. With no other candidate
present, that all-day event (e.g. a birthday, holiday, or reminder) wins by
default and gets attached to the recording as if it were the meeting.

The underlying gap is twofold: (1) nothing in `calendar.py` filters out
all-day (`date`-only) events, and (2) `_find_event` never verifies that its
winning candidate's parsed start actually falls inside the configured
`[anchor - calendar_match_before_minutes, anchor + calendar_match_after_minutes]`
window — it trusts the Calendar API's overlap semantics, which are
date-granular for all-day events rather than minute-granular. This was
flagged as a risk during the original calendar-integration design and never
guarded against.

## What Changes

- `calendar._eligible_events` SHALL exclude all-day events (events whose
  `start` payload has a `date` field and no `dateTime` field) from
  candidacy in every lookup that uses it: `find_event`, `upcoming_events`,
  and `past_events`.
- `calendar._find_event` SHALL only consider a candidate whose parsed start
  time actually falls within the configured match window
  (`[anchor - calendar_match_before_minutes, anchor + calendar_match_after_minutes]`),
  instead of trusting every event the Calendar API returns for the query
  range.
- No config, CLI surface, or prompt-context shape changes — this is a
  correctness fix to matching/filtering only.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `calendar-integration`: the "RSVP and ignore-slug filtering" requirement
  gains unconditional all-day-event exclusion; the "Recording-anchored
  event lookup" requirement gains explicit window-containment enforcement
  for the winning candidate.

## Impact

- `meet_recorder/calendar.py`: `_eligible_events` (new `_is_all_day` check),
  `_find_event` (candidate window-containment check).
- `tests/test_calendar.py`: add coverage for all-day-only candidates
  producing no match, all-day events losing to a real timed candidate, and
  an out-of-window sole candidate producing no match.
- No config or CLI surface changes; behavior-only fix.
