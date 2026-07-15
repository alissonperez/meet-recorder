## Why

The menu bar app's meeting-prompt scheduler (`meet_recorder/menubar.py`) uses a single timer and a single interval (`autorecord.poll_interval_minutes`, default 5min) both to query Google Calendar and to decide whether to show the start-recording modal. Because both responsibilities share one interval, a meeting's start can go undetected — and the modal delayed — for up to 5 minutes after it actually begins (GitHub issue #8).

## What Changes

- Split the single autorecord timer into two: a **calendar-poll timer** (fetches events from Google Calendar, keeps its current cadence) and a **meeting-check timer** (evaluates the already-fetched, in-memory events to decide whether to notify/prompt, on a much shorter, independently configurable cadence).
- Add config field `autorecord.check_interval_seconds` (default `60`) controlling the meeting-check timer's interval, in seconds.
- **BREAKING**: Rename config field `autorecord.poll_interval_minutes` -> `autorecord.calendar_poll_interval_minutes` (no migration/alias — this is a single-user personal project; the local `config.yaml` is updated by hand).
- Add config field `autorecord.max_meeting_age_minutes` (default `20`): the start-recording modal is no longer shown for an event that started more than this many minutes ago, guarding against a stale/late prompt (e.g. app restarted or woke from sleep long after a meeting began).

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `meeting-autorecord`: the scheduler now runs calendar polling and meeting-start checks on two independent, separately configured intervals instead of one; the start-time confirmation modal gains an upper bound on how late it can fire after a meeting's start.

## Impact

- `meet_recorder/config.py`: `AutoRecordConfig` — rename `poll_interval_minutes` -> `calendar_poll_interval_minutes`; add `check_interval_seconds` and `max_meeting_age_minutes` fields with new defaults.
- `meet_recorder/menubar.py`: split `_autorecord_timer`/`_run_autorecord_poll` into a fetch-only calendar-poll timer/method and a new meeting-check timer/method that reads a cached event list; extend `_maybe_prompt_start` with the max-age guard; adjust the kickoff timer to seed both the cache and an immediate check on startup.
- `tests/test_config.py`, `tests/test_menubar.py`: update/add unit tests for the renamed/new config fields and the split scheduler behavior (per project convention of always adding tests where possible).
- Existing local `config.yaml` files using `poll_interval_minutes` need manual renaming to `calendar_poll_interval_minutes` (no other action required — the field is optional with a default, so an unrenamed old key is silently ignored rather than erroring).
