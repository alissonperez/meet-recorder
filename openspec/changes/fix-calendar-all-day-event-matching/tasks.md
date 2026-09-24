## 1. Calendar filtering

- [x] 1.1 Add `_is_all_day(event)` helper to `meet_recorder/calendar.py` (`'date' in start and 'dateTime' not in start` on `event.get('start', {})`).
- [x] 1.2 Add an unconditional all-day drop to `_eligible_events`, alongside the existing ignore-slug check.
- [x] 1.3 In `_find_event`, skip candidates whose parsed `start` falls outside `[time_min, time_max]` before appending them to `candidates`.

## 2. Tests

- [x] 2.1 Add an `_all_day_event()` helper to `tests/test_calendar.py` (start/end as `{'date': ...}`, no `dateTime`).
- [x] 2.2 Add unit tests for `_is_all_day` (true for a date-only event, false for a `dateTime` event, false for an empty/missing `start`).
- [x] 2.3 Add an `_eligible_events` test asserting an all-day event is dropped while a timed event in the same batch survives.
- [x] 2.4 Add a `find_event` regression test: only an all-day candidate is returned by `_query_events` across all configured accounts -> `find_event` returns `None`.
- [x] 2.5 Add a `find_event` regression test: an all-day event and a valid timed candidate are both returned -> the timed candidate wins.
- [x] 2.6 Add a `find_event` regression test: a sole timed candidate whose parsed start is outside the configured match window is returned by `_query_events` -> `find_event` returns `None`.
- [x] 2.7 Run `poetry run pytest` and confirm the full suite passes.

## 3. Spec / docs

- [x] 3.1 Confirm `docs/prompts.md` needs no change (this fix only narrows whether `find_event` returns a match; it doesn't change the shape of prompt context built from a genuine match).
- [x] 3.2 Run `make lint` and fix any issues.
