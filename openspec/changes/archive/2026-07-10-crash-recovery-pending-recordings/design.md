## Context

`meet_recorder/recorder.py` already writes each recording incrementally to `~/MeetRecordings/.in-progress/<timestamp>/{mic,sys}.wav` (mono, PCM_16, 44.1kHz) via a queue + writer-thread per source (`_start_writer`/`_writer_loop`). On a clean `stop_recording_and_save`, those two files are merged block-by-block into a stereo `.wav` under `~/MeetRecordings/` (`_merge_to_stereo`) and the `.in-progress/<timestamp>/` directory is removed. If the process dies before `stop_recording_and_save` runs — crash, `kill -9`, forced restart/sleep interruption — the orphaned directory and its two partial `.wav` files are left behind indefinitely with no cleanup path today.

All in-memory recording state (`_state` dict) is process-local and not persisted, so there is no existing signal (lock file, PID, heartbeat) distinguishing "a directory left by a dead process" from "a directory currently being written to by a live process." The team has explicitly decided (see proposal) to accept this ambiguity rather than add tracking infrastructure, because the scan only ever runs once, at process boot, when the current process cannot yet own any `.in-progress/` directory itself.

## Goals / Non-Goals

**Goals:**
- Detect orphaned `.in-progress/<timestamp>/` directories at process startup (menu bar app and a new CLI command).
- Automatically and silently discard orphans whose `mic.wav`/`sys.wav` are unreadable or empty (crash occurred before any usable audio was flushed, or header never finalized in a way libsndfile can parse).
- For remaining valid orphans, get one decision from the user — applied to all of them — covering: merge + transcribe, leave alone, or delete.
- Reuse the existing merge and transcription code paths as-is rather than duplicating logic.

**Non-Goals:**
- No lock file, PID file, or other liveness tracking for in-progress recordings.
- No per-orphan granular decisions (the user picks one action for the whole batch this run — rejecting one orphan means re-running recovery later and choosing differently, likely by manually deleting the ones they don't want first).
- No continuous/background polling for orphans while the app is already running — detection is boot-time only.
- No change to the normal (non-crash) record/stop/transcribe flow.

## Decisions

**1. Detection timing: process boot only, no locking (Option C from exploration).**
Rationale: the only process that could legitimately be writing to `.in-progress/` is the currently running one, and by definition it hasn't started a recording yet at boot time. Alternatives considered: a lock/PID file (correct but adds a new failure mode — stale locks after a crash — for a problem that boot-time-only scanning already avoids), and an mtime-based staleness heuristic (arbitrary threshold, false positives during silence/pause). Rejected both as unnecessary complexity for this scope. The "Ignorar" action is the deliberate escape hatch for the rare/unsupported multi-instance case, rather than trying to detect it.

**2. Orphan validity check: open with `soundfile`, require > 0 frames.**
Each of `mic.wav` and `sys.wav` is opened via `sf.SoundFile(path, mode='r')`; if either raises (unreadable, e.g. RIFF header never finalized because the writer never called `close()`) or reports `0` frames, the whole orphan directory is discarded automatically without prompting. This mirrors the read path already used by `_merge_to_stereo`, so "would this orphan actually merge successfully" is answered directly rather than inferred from file size/mtime heuristics.

**3. Reuse merge/transcribe logic via extraction, not duplication.**
`recorder.py` will expose a function that performs the same merge-to-final-stereo-wav-and-cleanup-temp-dir behavior that `stop_recording_and_save` uses internally (extracting `_merge_to_stereo` + output-path-building + temp dir removal into a helper callable with an explicit `mic_path`/`sys_path`/`temp_dir` rather than reading from `_state`). Recovery calls this helper directly, then calls `transcriber.transcribe(path)` the same way `menubar.py`'s `_transcribe_in_background` already does. This keeps "what a successfully recovered recording looks like" identical to a normally stopped one.

**4. One prompt, batched decision, per proposal.**
Both entrypoints scan first, then present a single summary ("N gravação(ões) pendente(s) encontrada(s)") with three choices. Menu bar: `rumps.alert` with three buttons, invoked from a callback scheduled after `run()` starts the event loop (not from `__init__`, since `rumps.alert` needs the underlying NSApplication running to render correctly) — e.g. via `rumps.Timer` firing once shortly after launch, or an `applicationDidFinishLaunching`-style hook if rumps exposes one; if not, a zero-delay one-shot `rumps.Timer`. CLI: plain `input()` prompt in `handler_recover` in the CLI's synchronous flow, since there's no event loop constraint there.

**5. Recovery processing runs in series, reusing the background-thread pattern.**
Because pending orphans are expected to be rare (at most one or two between app runs, per proposal), recovery processes them one at a time synchronously within a single background thread (menu bar) or synchronously inline (CLI), rather than parallelizing. This avoids concurrent hits on the transcription API and keeps the icon state machine (`active_transcriptions` counter) simple to reason about — each recovered recording increments/decrements it just like `_transcribe_in_background` does for a normal stop.

**6. Discard = `shutil.rmtree` the orphan directory; no soft-delete/trash.**
Consistent with the existing cleanup in `stop_recording_and_save`, which already does `shutil.rmtree(temp_dir, ignore_errors=True)`.

## Risks / Trade-offs

- **[Risk]** A `.wav` file with a valid-looking header but truncated/garbled audio data (e.g. crash mid-write left a partial last block) passes the `soundfile` open check but produces an audibly broken merged recording. → **Mitigation**: accepted as a known limitation per the original idea doc ("perda de poucos segundos é aceitável comparada à perda total"); no further validation (e.g. checksums) is in scope.
- **[Risk]** "Ignorar" leaves the orphan in place, so if the user picks it repeatedly across restarts (e.g. because they don't understand the prompt), the directory accumulates disk usage indefinitely with no auto-expiry. → **Mitigation**: acceptable for now; user has "Apagar" available whenever they're ready; not automating disk cleanup is consistent with treating this as user-driven recovery, not garbage collection.
- **[Risk]** Assuming boot-time-only scanning is safe for concurrency could break if the app is ever changed to support multiple simultaneous instances or a daemon mode. → **Mitigation**: explicitly a non-goal/accepted assumption today; called out here so a future change touching multi-instance support knows to revisit this decision.
- **[Trade-off]** Batched single decision for all orphans is simpler to implement and reason about than per-orphan decisions, at the cost of forcing an all-or-nothing choice when a user has a mix of orphans they'd treat differently. Acceptable given orphans are expected to be rare.

## Open Questions

- None outstanding; all decisions above were confirmed during exploration before this proposal was written.
