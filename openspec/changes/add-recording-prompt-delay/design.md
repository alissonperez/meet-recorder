## Context

`_maybe_prompt_start` (`meet_recorder/menubar.py:193-229`) currently guards on two things before showing the modal: the event hasn't already been prompted (`_prompted_events`), and its `start_dt` isn't in the future (`event.start_dt > now: return`). Once the start time has passed, the very next `_run_meeting_check` tick (as fast as `check_interval_seconds`, default 60s) shows the modal. There's a separate guard for the *other* end of the window, `max_meeting_age_minutes` (default 20min), which skips the modal if too much time has already passed. This change adds a third, symmetrical guard in between: a minimum elapsed time since `start_dt` before the modal is allowed to show.

## Goals / Non-Goals

**Goals:**
- Let the user configure a grace period, in seconds, after a meeting's start time before the start-recording modal appears.
- Default to `0` seconds so existing behavior (immediate prompt) is unchanged for anyone who doesn't set the new field.
- Reuse the existing re-check mechanism (meeting-check timer re-evaluating `_cached_events` on every tick) rather than adding a new timer or scheduling primitive.

**Non-Goals:**
- No change to `notify_before_minutes` / the upcoming-meeting notification — this only affects the *start* modal.
- No per-event or per-calendar override of the delay; it's a single global config value, consistent with the other `autorecord.*` fields.
- No change to `max_meeting_age_minutes` semantics; the new delay and the max-age window are independent guards that both measure from the same `start_dt`, and the delay is expected to be configured well below the max age.

## Decisions

**Add `prompt_delay_seconds` as a fourth guard in `_maybe_prompt_start`, ordered right after the "hasn't started yet" check and before the max-age check.** Concretely:

```python
if event.start_dt > now:
    logger.debug(...)
    return

age_seconds = (now - event.start_dt).total_seconds()
if age_seconds < self.config.autorecord.prompt_delay_seconds:
    logger.debug(f'"{event.title}": started {age_seconds:.0f}s ago, waiting for prompt_delay_seconds, skipping')
    return

age_minutes = age_seconds / 60
if age_minutes > self.config.autorecord.max_meeting_age_minutes:
    ...
```

Placing it before the max-age check keeps the ordering "too early -> too late" symmetrical and readable. The existing `age_minutes` computation is reused (computed once as `age_seconds`, then converted), avoiding a duplicate `(now - event.start_dt)` call.

Alternative considered: compute a single `"eligible window"` boolean combining both bounds in one comparison. Rejected — the two guards have different logging/intent and existing code already separates "too early" from "too late" into distinct early-returns; matching that style is more consistent than introducing a new combined check.

**Skipped-for-delay events are not added to `_prompted_events`**, exactly like the existing max-age skip. This lets the meeting-check timer naturally re-evaluate the event on its next tick once the delay has elapsed, with no new bookkeeping.

**Config field named `prompt_delay_seconds`, validated with `max(0, int(...))`**, matching the pattern already used for `check_interval_seconds` and `max_meeting_age_minutes` in `AutoRecordConfig.__init__`. Seconds (not minutes) matches the user's stated requirement ("Delay em segundos... valor 60").

## Risks / Trade-offs

- [If `prompt_delay_seconds` is configured larger than `max_meeting_age_minutes * 60`, the modal would never show for any meeting — the delay guard would always fail before the age guard could ever pass.] → Not validated/clamped against each other; this is a single-user config file the user edits by hand, consistent with how `max_meeting_age_minutes` and `check_interval_seconds` aren't cross-validated against each other today. Worth a one-line comment near the field if it causes confusion later.
- [A delay means the modal can now appear anywhere from `prompt_delay_seconds` up to `prompt_delay_seconds + check_interval_seconds` after the true elapsed threshold, same granularity trade-off the meeting-check interval already has for the "started" transition.] → Acceptable; no mitigation needed, this mirrors existing timing precision limits documented in the `split-autorecord-poll-and-check-intervals` change.
