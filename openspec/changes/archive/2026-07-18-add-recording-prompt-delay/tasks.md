## 1. Config

- [x] 1.1 In `meet_recorder/config.py`, add `DEFAULT_AUTORECORD_PROMPT_DELAY_SECONDS = 0` alongside the other `DEFAULT_AUTORECORD_*` constants.
- [x] 1.2 In `AutoRecordConfig.__init__`, add `self.prompt_delay_seconds = max(0, int(data.get('prompt_delay_seconds', DEFAULT_AUTORECORD_PROMPT_DELAY_SECONDS)))`, following the same `max(min_bound, int(...))` pattern used for `check_interval_seconds` and `max_meeting_age_minutes`.
- [x] 1.3 In `tests/test_config.py`, add test cases covering: default value (`0`) when `prompt_delay_seconds` is absent, an explicit configured value, and the lower-bound clamp for a negative value.

## 2. Modal delay in menubar.py

- [x] 2.1 In `MenubarApp._maybe_prompt_start` (`meet_recorder/menubar.py`), right after the existing `if event.start_dt > now: return` guard and before the `max_meeting_age_minutes` guard, add an elapsed-time guard using `prompt_delay_seconds`:
      ```python
      age_seconds = (now - event.start_dt).total_seconds()
      if age_seconds < self.config.autorecord.prompt_delay_seconds:
          logger.debug(f'"{event.title}": started {age_seconds:.0f}s ago, waiting for prompt_delay_seconds, skipping')
          return
      ```
      Do not add the event to `self._prompted_events` in this branch, so the meeting-check timer re-evaluates it on the next tick.
- [x] 2.2 Update the existing `age_minutes = (now - event.start_dt).total_seconds() / 60` line just below to reuse `age_seconds` (i.e. `age_minutes = age_seconds / 60`) instead of recomputing `(now - event.start_dt)`.

## 3. Tests for menubar prompt delay

- [x] 3.1 In `tests/test_menubar.py`, add a test asserting that an event whose `start_dt` is in the past by less than `prompt_delay_seconds` does not trigger `_show_alert`/the modal and is not added to `self._prompted_events`.
- [x] 3.2 Add a test asserting that once enough time has elapsed (>= `prompt_delay_seconds`) the modal is shown as before.
- [x] 3.3 Add a test with `prompt_delay_seconds` at its default (`0`) confirming behavior is unchanged from before this change (modal shows immediately once `start_dt <= now`).

## 4. Docs / local config

- [x] 4.1 Add `prompt_delay_seconds: 0` to the commented `autorecord:` example block in `config.example.yaml` (after `check_interval_seconds`, before `notify_before_minutes` or `max_meeting_age_minutes` — match existing ordering conventions in that block).
- [x] 4.2 If `README.md` documents the other `autorecord.*` fields, add a matching entry for `prompt_delay_seconds`.

## 5. Verification

- [x] 5.1 Run `make lint` and the test suite (`poetry run pytest`) to confirm no regressions.

## 6. Pull request

- [x] 6.1 Push the branch and open a pull request for this change via `gh pr create`.
