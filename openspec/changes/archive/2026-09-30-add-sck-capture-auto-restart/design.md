## Context

See proposal.md — Why. The relevant current state:

- `meet_recorder/sck_capture.py` already flags an unrequested stop on the handle (`handle.stopped_unexpectedly`, `handle._active = False`) and makes `stop()` a no-op on an already-dead handle — that came from `fix-sck-stream-interruption`, whose design explicitly listed automatic restart as a non-goal. This change lifts that non-goal.
- `meet_recorder/recorder.py` already runs two background threads per recording (`_silence_monitor_loop`, `_padding_loop`) started at the end of `start_recording` and stopped in `_teardown_capture`, and already keeps all per-recording state in the module-level `_state` dict.
- `resume_mic()` already solves the "restart one source without disturbing the other or the files" problem for the microphone: it stashes the callback (`_state['mic_callback']`), reopens a stream against it, and lets `_level_channels` pad the gap. The system-audio side of the same problem is structurally identical.
- `_teardown_capture` currently reads `sys_handle.stopped_unexpectedly` once, at teardown, and returns it; `stop_recording_and_save` turns that into a warning. Earlier on this branch the warning text was corrected to stop claiming the file is truncated (the padding from `fix-mic-device-switch` had already made that false).
- `sck_capture.start()` is blocking and slow in the worst case: `_run_async` waits up to `CONTENT_LIST_TIMEOUT_SECONDS` (10s) then up to `START_TIMEOUT_SECONDS` (10s). Any restart mechanism has to assume a single attempt can occupy its caller for ~20s.
- `_CaptureDelegate.stream_didStopWithError_` is invoked on an SCK-owned dispatch queue, not a thread this codebase controls.

## Goals / Non-Goals

**Goals:**
- Restart system-audio capture into the *same* in-progress recording, with no file surgery and no change to the merge.
- Keep the retry loop's timing decisions testable without a test ever waiting real wall-clock time.
- Preserve every interruption that happened during a recording, so the save-time warning can describe the whole recording rather than the last handle's state.
- Add no new blocking work to the padding or silence threads, whose intervals (0.5s / 1.0s) are load-bearing for frame alignment and silence detection.

**Non-Goals:**
- Diagnosing or preventing the -3805 condition itself (still unknown; issue #22's third follow-up).
- Restarting the microphone automatically — that stays user-initiated via "Trocar microfone…", per `fix-mic-device-switch`.
- Making the retry budget or backoff user-configurable. `recorder.py` deliberately takes no dependency on `meet_recorder.config`; its tunables are module constants or env vars, and these follow that.
- Recovering the audio that played during the outage. It is unrecoverable by construction; the gap is silence.

## Decisions

- **Run the restart from a dedicated supervisor thread, not from the SCK delegate callback.** `stream_didStopWithError_` runs on a ScreenCaptureKit-owned dispatch queue, and a restart blocks for up to ~20s inside `_run_async`; occupying an SCK callback thread for that long risks deadlocking the framework's own teardown of the stream that just died. A dedicated thread also isolates the blocking call from the padding thread, which must keep ticking every 0.5s throughout the outage — the padding is precisely what keeps the recording aligned while system audio is dead.
  - Alternative considered: reuse the silence monitor or padding thread. Rejected — a multi-second blocking `start()` inside either one stalls the behavior that makes the interruption survivable in the first place.
  - Alternative considered: an `on_unexpected_stop` callback plumbed through `start()`. Rejected for the same reason the archived `fix-sck-stream-interruption` design rejected it: it moves work onto the SCK thread and adds cross-thread callback plumbing where polling module state already suffices.

- **Detect the stop by polling `handle.stopped_unexpectedly`, keeping the delegate unchanged.** The supervisor reads the flag the delegate already sets. This keeps the `sck_capture` layer free of any knowledge of retry policy and preserves the existing GIL-atomic, lock-free contract on that attribute.

- **Restart by reusing the stashed system-audio chunk callback, mirroring `resume_mic`.** `sys_on_chunk` closes over `sys_queue`, which is local to `start_recording`, so it is stashed as `_state['sys_on_chunk']` exactly as `mic_callback` already is. The supervisor then calls `sck_capture.start(_state['sys_on_chunk'], sample_rate=SAMPLE_RATE, channels=SYS_AUDIO_CHANNELS)` and publishes the resulting handle. Because the callback is unchanged, the new stream feeds the same queue, the same writer thread, and the same `sys.wav` — the restart is invisible to the merge, and `_level_channels` pads the outage with silence on its own with no special-casing.
  - Alternative considered: tear down and rebuild the sys queue/writer/file and stitch files at merge time. Rejected — strictly more machinery for an outcome the existing padding already produces.

- **Split the retry policy into a clock-driven pure tick, `_sys_restart_tick(now)`, called by the supervisor loop.** The loop itself only does `while not stop_event.wait(SYS_RESTART_CHECK_INTERVAL_SECONDS): _sys_restart_tick(time.monotonic())`. All scheduling is expressed as comparisons against a `next_attempt_at` monotonic deadline held in `_state`, never as `time.sleep(delay)`. Tests then drive `_sys_restart_tick` directly with synthetic `now` values to assert the 1/2/4/8/16s schedule, budget exhaustion, and budget reset in milliseconds of real time. This mirrors `_level_channels` being unit-testable independently of `_padding_loop`, and is what makes the test-suite spec's "verifiable without waiting real time" requirement achievable.

- **Keep restart state in one `_state['sys_restart']` dict**: `interruptions` (append-only records of `{error, recovered}`), `attempts_left`, `next_attempt_at`, `pending_error`, `restarted_at`. One key keeps the growing `_state` dict legible and makes the whole restart subsystem resettable in one assignment during teardown.

- **Accumulate interruptions in `_state`, not on the handle, because a restart replaces the handle.** The dead handle carrying `stopped_unexpectedly` is dropped on a successful restart, so reading only the live handle at teardown would report "no interruption" for a recording that was interrupted and recovered, and would report only the last of several. The supervisor appends a record the moment it observes a dead handle and marks it `recovered=True` when a restart succeeds. `_teardown_capture` additionally records the live handle's flag if the recording was stopped before the supervisor ever ticked on it, so a stop racing an interruption still warns.
  - Consequence: `_teardown_capture` returns the interruption list where it previously returned a single error string, and `stop_recording_and_save` composes its warning from that list (count, and whether capture was ultimately recovered or lost).

- **Reset the attempt budget from evidence of real audio, not merely from a successful `start()`.** A stream can start cleanly and deliver nothing (the exact failure mode `_check_early_sys_buffers` exists for). The budget resets only when the restarted stream has been up for `SYS_RESTART_HEALTHY_RESET_SECONDS` *and* `_state['last_chunk_at']['sys']` is fresh by the existing `STALE_CHUNK_TIMEOUT_SECONDS` rule — reusing the timestamp the silence monitor already maintains rather than adding a second liveness signal.

- **Serialize handle publication and teardown with a lock, and bound the join.** A restart attempt can be in flight when the user stops the recording. `_teardown_capture` stops the supervisor first (before `sck_capture.stop`), joins with a short timeout in the style of the existing `join(timeout=2)` calls, and then snapshots-and-clears `_state['sys_handle']` under `_state['sys_restart_lock']`. The supervisor takes the same lock to publish a new handle and, inside it, re-checks `_state['recording_active']`; if the recording ended, it stops the stream it just created instead of publishing it. This keeps the user's stop bounded (the spec's "recording remains saveable while a restart is pending") without leaking an orphaned SCK stream.

- **Surface interruption and restoration through module-level hooks, mirroring the silence hooks.** `on_sys_capture_interrupted(error)` and `on_sys_capture_restored()` default to no-ops so the CLI path is unchanged, and `menubar.py` assigns them next to `on_silence_warning` / `on_silence_recovered` and marshals to the main thread with `AppHelper.callAfter`, matching the existing comment's reasoning about AppKit work from a recorder-owned thread.

- **Constants live in `recorder.py`**, following `SILENCE_CHECK_INTERVAL_SECONDS` and friends: `SYS_RESTART_MAX_ATTEMPTS = 5`, `SYS_RESTART_BASE_DELAY_SECONDS = 1.0` (yielding 1/2/4/8/16s, ~31s to exhaust), `SYS_RESTART_HEALTHY_RESET_SECONDS = 60.0`, `SYS_RESTART_CHECK_INTERVAL_SECONDS = 0.5`.

## Risks / Trade-offs

- [A restart attempt blocks the supervisor for up to ~20s, during which a second unexpected stop is not noticed] → Acceptable and self-correcting: the flag is sticky, so the next tick sees it. Nothing else depends on the supervisor's latency — padding and silence detection run on their own threads.
- [The exhaustion window (~31s) and the silence window (30s) are close, so a permanently broken stream may notify twice in quick succession — "interrupted" then "system audio may be silent"] → Kept deliberately. The spec requires the silence notification to still fire when capture is not restored; the two messages say different things (we tried and gave up vs. this channel is dead), and suppressing one would hide a real fault.
- [A flapping stream that starts cleanly and dies repeatedly could notify on each recovery] → Bounded by the budget: short-lived restarts never reset it, so at most `SYS_RESTART_MAX_ATTEMPTS` restore notifications can occur per healthy period.
- [Publishing a handle from the supervisor while teardown clears it is a genuine race, unlike the lock-free `_active` flag] → Mitigated by `_state['sys_restart_lock']` covering publication and the teardown snapshot, plus the in-lock `recording_active` re-check. This is the one place in this module where GIL atomicity is not sufficient, because two related fields must change together.
- [Supervisor thread that times out its join keeps running briefly after `stop_recording_and_save` returns] → It is a daemon thread whose only remaining action is to stop the stream it created and exit; it cannot touch `_state` for the next recording because it re-checks `recording_active` under the lock before publishing.
- [`_teardown_capture`'s return signature changes shape (string → list)] → Internal to the module; `discard_recording` already discards the value and `stop_recording_and_save` is the only consumer. Covered by updating the existing tests that assert on it.

## Migration Plan

None required. The change is additive at runtime and touches no on-disk format, config schema, or CLI surface: recordings, temporary files, and the merge are unchanged. Rollback is a plain revert of the change — a reverted build simply stops attempting restarts and falls back to the current detect-and-warn behavior.
