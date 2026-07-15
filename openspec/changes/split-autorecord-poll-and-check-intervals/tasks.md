## 1. Config

- [x] 1.1 In `meet_recorder/config.py`, rename `AutoRecordConfig`'s `poll_interval_minutes` field/kwarg to `calendar_poll_interval_minutes` (keep `DEFAULT_AUTORECORD_POLL_INTERVAL_MINUTES` value of 5, rename the constant too for clarity, e.g. `DEFAULT_AUTORECORD_CALENDAR_POLL_INTERVAL_MINUTES`).
- [x] 1.2 Add `check_interval_seconds` field to `AutoRecordConfig` (default `DEFAULT_AUTORECORD_CHECK_INTERVAL_SECONDS = 60`).
- [x] 1.3 Add `max_meeting_age_minutes` field to `AutoRecordConfig` (default `DEFAULT_AUTORECORD_MAX_MEETING_AGE_MINUTES = 20`).
- [x] 1.4 Update `tests/test_config.py`: rename existing assertions/fixtures using `poll_interval_minutes` to `calendar_poll_interval_minutes`, and add cases covering defaults and explicit values for `check_interval_seconds` and `max_meeting_age_minutes`.

## 2. Scheduler split in menubar.py

- [x] 2.1 Add `self._cached_events = []` in `MenubarApp.__init__`.
- [x] 2.2 Rename `_autorecord_timer` -> `_calendar_poll_timer` and its builder `_build_autorecord_timer` -> `_build_calendar_poll_timer`, using `self.config.autorecord.calendar_poll_interval_minutes * 60` as the interval (unchanged value, renamed reference).
- [x] 2.3 Rename `_run_autorecord_poll` -> `_run_calendar_poll`; strip out the per-event `_maybe_notify_upcoming`/`_maybe_prompt_start` calls, keep the `calendar.upcoming_events(...)` fetch, failure handling (`_on_poll_failure`, resetting `_poll_failures`), and store the fetched list into `self._cached_events` on success.
- [x] 2.4 Add `_meeting_check_timer = rumps.Timer(self._run_meeting_check, self.config.autorecord.check_interval_seconds)` (built alongside the poll timer, only when `_autorecord_active()`), and start it in `run()` next to the other autorecord timers.
- [x] 2.5 Add `_run_meeting_check(self, sender)`: compute `now = datetime.now().astimezone()`, iterate `self._cached_events`, calling `_maybe_notify_upcoming(event, now)` and `_maybe_prompt_start(event, now)` for each — this is the decision logic removed from `_run_calendar_poll` in 2.3.
- [x] 2.6 Rename `_autorecord_kickoff_timer` -> `_calendar_poll_kickoff_timer` and `_run_autorecord_kickoff` -> `_run_calendar_poll_kickoff`; after it stops itself and calls `_run_calendar_poll(sender)`, have it also call `self._run_meeting_check(sender)` once so a meeting already in progress at launch is evaluated immediately against the freshly seeded cache.
- [x] 2.7 In `_maybe_prompt_start`, immediately after the existing `if event.start_dt > now: return` guard, add the max-age guard (do not add the event to `self._prompted_events` in this branch):
      ```python
      age_minutes = (now - event.start_dt).total_seconds() / 60
      if age_minutes > self.config.autorecord.max_meeting_age_minutes:
          logger.debug(f'"{event.title}": started {age_minutes:.1f}min ago, older than max_meeting_age_minutes, skipping')
          return
      ```
- [x] 2.8 Update `_autorecord_window_minutes` to read `self.config.autorecord.calendar_poll_interval_minutes` (renamed field, same formula: `notify_before_minutes + calendar_poll_interval_minutes`).
- [x] 2.9 Update the `__init__` log line ("Meeting prompt active: polling every {poll_interval_minutes}min...") to reference `calendar_poll_interval_minutes` and also mention `check_interval_seconds`.

## 3. Tests for menubar scheduler

- [x] 3.1 In `tests/test_menubar.py`, add/update tests asserting that `_run_calendar_poll` only fetches and populates `self._cached_events` and does not call notify/prompt logic (e.g. by asserting `_maybe_notify_upcoming`/`_maybe_prompt_start` are not invoked from it, via mocking).
- [x] 3.2 Add a test asserting `_run_meeting_check` calls `_maybe_notify_upcoming`/`_maybe_prompt_start` for each event currently in `self._cached_events`, without calling `calendar.upcoming_events`.
- [x] 3.3 Add tests for `_maybe_prompt_start`'s max-age guard: an event started within `max_meeting_age_minutes` still prompts; an event started longer ago than `max_meeting_age_minutes` does not prompt and is not added to `self._prompted_events`.
- [x] 3.4 Add/update a test for the kickoff path confirming it triggers both an immediate fetch and an immediate check (e.g. a stale-cache/empty-cache scenario at startup still prompts for an already-started meeting within the age window).
- [x] 3.5 Update any existing test fixtures/mocks referencing the old `poll_interval_minutes` config key or `_autorecord_timer`/`_run_autorecord_poll` names to match the renamed fields/methods.

## 4. Docs / local config

- [x] 4.1 Update any README or example config (e.g. `.env.example`-equivalent config sample, if one documents `autorecord.poll_interval_minutes`) to show `calendar_poll_interval_minutes`, `check_interval_seconds`, and `max_meeting_age_minutes`.
- [x] 4.2 Manually rename `poll_interval_minutes` -> `calendar_poll_interval_minutes` in the local `~/.config/meet-recorder/config.yaml` (outside version control, reminder only — no code change).

## 5. Verification

- [x] 5.1 Run `make lint` and the test suite (`poetry run pytest`) to confirm the rename and split introduce no regressions.

## 6. Pull request

- [ ] 6.1 Push the branch and open a pull request for this change via `gh pr create`.
- [ ] 6.2 Include `Closes #8` in the pull request body so merging it automatically closes GitHub issue #8.
