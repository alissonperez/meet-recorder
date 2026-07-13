## Context

`meet_recorder/recorder.py` already captures a start timestamp in `_build_temp_paths()` (called from `start_recording()`), used only to name the `.in-progress/<timestamp>/` temp directory. The final `.wav` filename is built separately and later, in `_build_output_path()`, which calls `datetime.now()` again at stop/merge time — so the saved file's name reflects when recording *stopped*, not started. `merge_and_cleanup(mic_path, sys_path, temp_dir)` already receives `temp_dir`, whose basename *is* the start timestamp string, so the value needed to fix this is already available at the call site without adding new state.

`meet_recorder/transcriber.py`'s `_resolve_timestamp(wav_path)` parses the timestamp straight out of the `.wav` filename (falling back to file mtime only if the name doesn't match `FILENAME_TIMESTAMP_FORMAT`). Once the `.wav` filename carries the start time, transcript/summary naming and calendar-anchor lookup inherit the fix with no code change in `transcriber.py`.

`meet_recorder/calendar.py`'s `_find_event(anchor, config)` filters out declined events via `_accepted_events`, then picks the single closest-start-time event across all accounts with `min(candidates, key=distance)`. There is currently no concept of RSVP tiers (accepted vs. tentative) — both compete equally by distance.

## Goals / Non-Goals

**Goals:**
- Recording `.wav` filenames reflect the recording's start time.
- Transcript/summary filenames and month-folder placement reflect the same start time (via the existing filename-parsing path in `transcriber.py`).
- Calendar event matching still anchors on recording start time and picks the closest-starting event, but now prefers accepted ("Yes") events over tentative ("Maybe") ones, only falling back to tentative when no accepted event qualifies within the match window.

**Non-Goals:**
- No migration of existing `.wav`/transcript/summary files already on disk — they keep their current (end-time-derived) names.
- No change to the match window sizing (`calendar_match_before_minutes`/`calendar_match_after_minutes`) or to the declined-event exclusion.
- No change to how `transcriber.py` resolves timestamps — it already reads from the filename correctly; only the filename's *source* value changes.

## Decisions

- **Thread the start timestamp through `merge_and_cleanup` instead of introducing new global state.** `temp_dir`'s basename already equals the start-time string produced by `_build_temp_paths()`. `merge_and_cleanup` will parse it back out (`os.path.basename(temp_dir)`) and pass it to `_build_output_path(timestamp)`, which stops calling `datetime.now()` itself. This avoids adding a parallel `_state['start_time']` entry that could drift from the temp-dir name.
  - *Alternative considered*: store `datetime.now()` in `_state` at `start_recording()` and read it back in `stop_recording_and_save()`. Rejected because it duplicates a value already encoded in `temp_dir`, and `_state` is cleared in the `finally` block of `stop_recording_and_save()` before `merge_and_cleanup`'s return value is used elsewhere — passing the value explicitly through the existing `temp_dir` argument is simpler and keeps a single source of truth.
- **No changes needed in `transcriber.py`.** `_resolve_timestamp` already prefers parsing the filename over mtime; once the filename is start-time-based, `find_event`, `_build_base_filename`, and `_write_markdown`'s month-folder all automatically use the start time. Verify with a unit test rather than touching the code.
- **RSVP tiering in `calendar.py`: filter candidates into an "accepted" tier first; only use the "tentative" tier if the accepted tier is empty after distance-based selection within the window.** Concretely, `_accepted_events` (or a new helper) partitions non-declined candidates by the current user's `responseStatus` (`accepted` vs. `tentative`/`needsAction`/no response), and `_find_event` runs its existing closest-distance `min()` selection over the accepted tier first, falling back to the tentative tier only when the accepted tier yields no candidates within the window.
  - *Alternative considered*: score every candidate by `(tier, distance)` and take the global min. Rejected because it could let a tentative event far from an accepted-but-out-of-window event win in edge cases; a strict "try accepted first, then tentative" pass matches the user's stated preference ("Sim" then "Talvez") more literally and is easier to reason about.
  - Events with no attendee response entry for the user remain non-excluded per the existing spec (`Event without attendee response accepted`) — these are treated as their own tier below accepted, alongside or after tentative (implementation detail to confirm during tasks: likely grouped with tentative as "not explicitly accepted").

## Risks / Trade-offs

- [Parsing the start timestamp back out of `temp_dir`'s basename is stringly-typed] → Mitigated by reusing the exact same `strftime`/`strptime` format constant already used in `_build_temp_paths`, so there's a single format string, not two.
- [RSVP-tier fallback could change which event gets matched for recordings that previously matched a tentative event when a farther-but-accepted event existed] → This is the intended behavior change (accepted should win), called out as a proposal item; existing scenario coverage in `calendar-integration` spec should be extended, not silently altered.
- [Orphan/crash-recovery recordings recovered from `.in-progress/<timestamp>/` after a crash] → Confirmed non-issue: both `handlers.py:handler_recover()` and the menubar crash-recovery flow call `merge_and_cleanup(mic_path, sys_path, orphan_dir)` — the same function and same `orphan_dir`/`temp_dir` shape used by the live stop-and-save path — so the task 1.3 fix covers crash recovery automatically with no separate code path.

## Migration Plan

No data migration. This only changes behavior for recordings started after the change ships. No rollback concerns beyond a normal code revert.

## Open Questions

- Should events with no attendee-response entry for the user (currently "not excluded" per existing spec) be treated as accepted-tier, tentative-tier, or their own third tier for matching purposes? Leaning toward grouping them with tentative (i.e., not preferred over a genuine accepted RSVP) — to confirm in tasks/implementation.
