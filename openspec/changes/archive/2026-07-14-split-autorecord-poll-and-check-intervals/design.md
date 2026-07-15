## Context

`MenubarApp` (`meet_recorder/menubar.py`) runs one `rumps.Timer` (`_autorecord_timer`) on `autorecord.poll_interval_minutes` (default 5min). Its callback, `_run_autorecord_poll`, does two unrelated things in one pass:

1. Fetches upcoming events from Google Calendar (`calendar.upcoming_events`).
2. Immediately decides, for each fetched event, whether to fire the "upcoming meeting" notification (`_maybe_notify_upcoming`) and/or the "start recording?" modal (`_maybe_prompt_start`).

Because decision-making only happens right after a fetch, the modal can lag up to `poll_interval_minutes` behind the real meeting start. A separate kickoff timer (`_autorecord_kickoff_timer`) runs the same combined method once immediately at startup so an in-progress meeting isn't missed for a full interval after app launch.

`rumps.Timer(callback, interval)` takes `interval` in seconds (the current code multiplies minutes by 60 itself), so nothing new is needed in `rumps` to support a sub-minute interval — this is purely an application-level split.

## Goals / Non-Goals

**Goals:**
- Detect a meeting start and show the modal within `check_interval_seconds` (default 60s) of the real start, independent of how infrequently the Calendar API is polled.
- Keep Calendar API call volume unchanged (still one fetch per `calendar_poll_interval_minutes`).
- Avoid showing the start modal for a meeting that started so long ago that prompting is no longer useful (e.g., app was asleep or just restarted mid-way through an old, still-open calendar block).

**Non-Goals:**
- No change to the notification/modal content, RSVP filtering, or ignore-slug logic.
- No backward-compatibility shim for the renamed `poll_interval_minutes` config key — this is a single-user project, and updating the local `config.yaml` is on the user.
- No change to `_notified_events`/`_prompted_events` bookkeeping (they still grow unbounded for the process lifetime, and event eviction from the cache is entirely driven by the next successful poll's fetch window — pre-existing behavior, out of scope here).

## Decisions

**Two timers, one shared cache attribute.** Introduce `self._cached_events: list = []` in `__init__`. `_run_calendar_poll` (renamed from `_run_autorecord_poll`) only fetches and overwrites `self._cached_events` on success; it no longer calls `_maybe_notify_upcoming`/`_maybe_prompt_start`. A new `_run_meeting_check` reads `self._cached_events` and runs that decision logic. Both timers and `rumps` callbacks run on the main thread via the Cocoa run loop, so no locking is needed around `self._cached_events`.

Alternative considered: a single timer at the fast interval that fetches from Calendar every tick, filtering API calls in application logic. Rejected — it re-adds complexity to avoid over-fetching that a second timer gets for free, and it couples "how often do we ask Google" to "how often do we re-check the clock," which is exactly what the issue asks to decouple.

**Config field renamed, not aliased.** `poll_interval_minutes` -> `calendar_poll_interval_minutes`. Since only the project owner runs this app locally, a stale key in `config.yaml` is simply ignored (falls back to the default) rather than causing an error — acceptable, confirmed with the user, no alias/back-compat path added.

**`check_interval_seconds` is its own field, not reusing minute granularity.** The issue explicitly asks for "every minute or even seconds (configurable)"; a minutes-only field can't express that, so this is a new integer field in seconds, independent unit from the calendar-poll field.

**Max-meeting-age guard lives in `_maybe_prompt_start`, not just the kickoff path.** Confirmed with the user: any late-firing prompt (kickoff, or the check timer waking up after the app was suspended/minimized) should be subject to the same guard, so the check is added right after the existing "has it started yet?" guard, before the recording-state check:

```python
age_minutes = (now - event.start_dt).total_seconds() / 60
if age_minutes > self.config.autorecord.max_meeting_age_minutes:
    logger.debug(f'"{event.title}": started {age_minutes:.1f}min ago, older than max_meeting_age_minutes, skipping')
    return
```

**Skipped-for-age events are not added to `_prompted_events`.** Judgment call, made explicit here: the alternative (marking them prompted immediately) would permanently suppress the modal even if config's `max_meeting_age_minutes` were increased later in the same run, for no real benefit — the event is removed from `_cached_events` anyway on the next successful poll once it falls outside `calendar.upcoming_events`'s fetch window. Leaving it unprompted-but-unmarked is simpler and self-correcting.

**Kickoff seeds both fetch and check.** `_run_calendar_poll_kickoff` (renamed from `_run_autorecord_kickoff`) calls `_run_calendar_poll` and then `_run_meeting_check` once, synchronously, so a meeting already in-progress at app launch is evaluated immediately rather than waiting for the first `check_interval_seconds` tick against an empty cache.

## Risks / Trade-offs

- [More frequent timer wakeups (every `check_interval_seconds`, potentially every few seconds) add negligible CPU/battery cost since the check only iterates an in-memory list — no I/O.] → No mitigation needed; documented as expected given the feature request.
- [Renaming `poll_interval_minutes` silently breaks any existing `config.yaml` that still uses the old key, falling back to the default interval without an error.] → Accepted trade-off per user decision (single-user project); worth a one-line README/CHANGELOG-style callout if one exists, but no code-level migration.
- [`max_meeting_age_minutes` could suppress a legitimate prompt if the app is asleep for a long time and wakes up after the cutoff.] → This is the intended behavior per the issue's follow-up requirement; the user can always start recording manually via the menu.

## Open Questions

(none — all prior open questions from discovery were resolved with the user before writing this design)
