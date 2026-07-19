## Why

Today the start-recording modal fires the instant a meeting-check tick observes that a meeting's start time has arrived — as early as `check_interval_seconds` after it started. In practice, meetings often start a bit late or take a minute to actually get going (waiting for other attendees, small talk, etc.), so an immediate prompt interrupts the user before there's anything worth recording yet. The user wants a configurable grace period so the modal only appears once the meeting has plausibly actually started.

## What Changes

- Add config field `autorecord.prompt_delay_seconds` (default `0`, preserving current immediate-prompt behavior for anyone who doesn't set it).
- `_maybe_prompt_start` will only show the start-recording modal once at least `prompt_delay_seconds` have elapsed since the event's `start_dt`, instead of showing it as soon as `start_dt <= now`.
- An event whose delay hasn't elapsed yet is left unmarked (not added to `_prompted_events`), the same way the existing `max_meeting_age_minutes` guard leaves late events unmarked, so the meeting-check timer re-evaluates it on the next tick until the delay elapses (or the event ages out via `max_meeting_age_minutes`).

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `meeting-autorecord`: the start-time confirmation modal now waits for a configurable delay after the meeting's start time before it is shown, instead of showing immediately once the start time has passed.

## Impact

- `meet_recorder/config.py`: `AutoRecordConfig` — add `prompt_delay_seconds` field (default `DEFAULT_AUTORECORD_PROMPT_DELAY_SECONDS = 0`), validated/bounded like the other autorecord interval fields.
- `meet_recorder/menubar.py`: `_maybe_prompt_start` — replace the "has it started yet" guard with a "has it started at least `prompt_delay_seconds` ago" guard.
- `tests/test_config.py`, `tests/test_menubar.py`: add tests for the new config field's default/validation and for the modal's delayed-prompt behavior (per project convention of always adding tests where possible).
