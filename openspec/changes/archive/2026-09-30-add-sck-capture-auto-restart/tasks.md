## 1. Restart state scaffolding

- [x] 1.1 Add the restart constants to `meet_recorder/recorder.py` (`SYS_RESTART_MAX_ATTEMPTS = 5`, `SYS_RESTART_BASE_DELAY_SECONDS = 1.0`, `SYS_RESTART_HEALTHY_RESET_SECONDS = 60.0`, `SYS_RESTART_CHECK_INTERVAL_SECONDS = 0.5`) alongside the existing silence/padding constants, and verify `poetry run ruff check .` passes.
- [x] 1.2 Stash the system-audio chunk callback as `_state['sys_on_chunk']` in `start_recording` (mirroring the existing `_state['mic_callback']`), and add the `_state` keys `sys_restart` and `sys_restart_lock`, initializing them in `start_recording` and clearing them in `_teardown_capture`'s `finally` block alongside the other per-recording keys; verify the existing `poetry run pytest tests/test_recorder.py` suite still passes.
- [x] 1.3 Add the module-level `on_sys_capture_interrupted(error)` / `on_sys_capture_restored()` hooks defaulting to no-ops, next to `on_silence_warning` / `on_silence_recovered`, and verify a unit test asserts the defaults are callable no-ops so the CLI path is unaffected.

## 2. Restart supervisor

- [x] 2.1 Implement `_sys_restart_tick(now)` holding the whole policy — record a newly observed `handle.stopped_unexpectedly`, fire `on_sys_capture_interrupted`, schedule the first attempt, run a due attempt via `sck_capture.start(_state['sys_on_chunk'], ...)`, double the delay and decrement the budget on failure, and publish plus fire `on_sys_capture_restored` on success — taking `now` as a parameter and never calling `time.sleep`; verify with unit tests that drive it directly with synthetic `now` values.
- [x] 2.2 Implement the budget reset inside `_sys_restart_tick`: restore `attempts_left` to `SYS_RESTART_MAX_ATTEMPTS` only once the restarted stream has been up for `SYS_RESTART_HEALTHY_RESET_SECONDS` and `_state['last_chunk_at']['sys']` is fresher than `STALE_CHUNK_TIMEOUT_SECONDS`; verify with a unit test that a short-lived restart does not reset the budget while a sustained healthy one does.
- [x] 2.3 Implement `_sys_restart_loop`, `_start_restart_supervisor`, and `_stop_restart_supervisor` following the `_padding_loop` / `_start_padding_thread` / `_stop_padding_thread` shape, start the supervisor at the end of `start_recording`, and stop it in `_teardown_capture` before `sck_capture.stop(sys_handle)`; verify a test asserts the thread is running after `start_recording` and stopped after `stop_recording_and_save`.
- [x] 2.4 Guard handle publication with `_state['sys_restart_lock']` plus an in-lock `_state['recording_active']` re-check that stops the freshly created stream instead of publishing it when the recording already ended, and take the same lock where `_teardown_capture` snapshots and clears `sys_handle`; verify a test simulates a restart completing after teardown and asserts the new stream is stopped and `_state['sys_handle']` stays `None`.

## 3. Interruption bookkeeping and save-time warning

- [x] 3.1 Change `_teardown_capture` to return the accumulated `sys_restart['interruptions']` list instead of the single `stopped_unexpectedly` string, appending the live handle's flag first if the supervisor never observed it, so a stop that races an interruption is still recorded; verify with a test that stops a recording immediately after marking the stub handle interrupted.
- [x] 3.2 Rewrite the `stop_recording_and_save` warning to compose from that list — number of interruptions, and recovered (silent gap, capture resumed) versus exhausted (no system audio to the end, microphone preserved) — never describing the file as truncated; verify with tests asserting the two wordings differ and that neither contains "truncated".
- [x] 3.3 Update `discard_recording`'s unpacking of the changed `_teardown_capture` return value and verify `poetry run pytest tests/test_recorder.py` passes.

## 4. Menu bar notifications

- [x] 4.1 Wire `recorder.on_sys_capture_interrupted` / `recorder.on_sys_capture_restored` in `MenuBarApp.__init__` next to the silence hooks, with `AppHelper.callAfter` marshalling to `_handle_sys_capture_interrupted` / `_handle_sys_capture_restored` that call `_notify`; verify with tests stubbing `_notify` and the marshaller that each hook requests a notification with text identifying the interruption and the restoration.

## 5. Test suite

- [x] 5.1 Add `tests/test_recorder.py` coverage for the supervisor per the test-suite delta spec — successful restart writes to the same in-progress recording, bounded attempts with increasing delays, exhausted budget makes no further start calls, budget reset after sustained healthy capture, no reset after a short-lived restart, and no restart after a user-requested stop — with `sck_capture.start` stubbed and no real sleeps; verify `poetry run pytest tests/test_recorder.py` passes.
- [x] 5.2 Add `tests/test_sck_capture.py` coverage that a handle replaced by a restart keeps its own `stopped_unexpectedly` value and that `stop()` on the replaced handle remains a no-op; verify `poetry run pytest tests/test_sck_capture.py` passes.
- [x] 5.3 Run the full suite and linter (`poetry run pytest` and `make lint`) and verify both are clean.

## 6. Wrap-up

- [x] 6.1 Confirm no change was made to the dynamic context sent with the transcription, summary, or title prompts, so `docs/prompts.md` needs no update under the CLAUDE.md contribution checklist; verify by grepping the diff for `prompts.md`-relevant modules (`transcriber.py`, prompt builders) and recording the conclusion in the PR description.
- [ ] 6.2 Manually verify recovery end to end: start a recording from the menu bar, force the ScreenCaptureKit stream to stop mid-recording, and confirm the interruption and restoration notifications appear, the saved `.wav` has system audio before and after a silent gap, both channels stay in sync, and the save-time warning names the recovered case.
- [ ] 6.3 Open the pull request for this change with `Closes #22` in its description, so merging it closes [issue #22](https://github.com/alissonperez/meet-recorder/issues/22); verify by checking that the PR page shows issue #22 linked under "Development"/"Linked issues" before merge.
