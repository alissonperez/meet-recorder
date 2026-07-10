## Why

Today a recording lives entirely in `.in-progress/<timestamp>/{mic,sys}.wav` on disk while in progress (incremental writing already implemented), but if the process crashes, is killed, or the Mac restarts/sleeps mid-recording, nothing ever merges those two mono files into the final stereo `.wav` or transcribes them — they sit orphaned forever and the recording is silently unrecoverable from the user's perspective, even though the raw audio is still on disk.

## What Changes

- Add a recovery scan that runs once at process start (menu bar app boot and a new standalone CLI command), listing subdirectories of `~/MeetRecordings/.in-progress/`.
- For each orphaned subdirectory, validate `mic.wav` and `sys.wav` by attempting to open them with `soundfile` and checking they contain at least one frame; automatically discard (delete) any orphan where either file fails to open or is empty, with no user prompt for those.
- For the remaining valid orphans, present a single confirmation to the user covering all of them at once, with three possible actions applied uniformly to all pending orphans:
  - **Processar**: merge each pair into the final stereo `.wav` (reusing the existing merge logic) and run automatic transcription for each, one at a time (in series), reusing the existing transcription pipeline.
  - **Ignorar**: leave the orphaned directories untouched (they will be re-detected and re-prompted on the next start) — this is the safety valve for the (rare, unsupported) case of another instance actually still writing to that directory.
  - **Apagar**: delete the orphaned directories without processing them.
- In the menu bar app, the confirmation is a `rumps.alert` modal shown after the app's run loop is up (not during `__init__`), so alerts render correctly.
- Add `handler_recover` in `meet_recorder/handlers.py`, exposed as a CLI command, using a terminal prompt (`input()`) for the same three-way confirmation.
- No lock file or PID tracking is introduced — detection assumes a single process owns `.in-progress/` at any given time and only scans at process boot, when by construction no recording from *this* process can yet be in progress.

## Capabilities

### New Capabilities
- `crash-recovery`: detecting, validating, and resolving (process/ignore/discard) orphaned in-progress recording directories left behind by a prior crash, on both the menu bar app and a CLI entrypoint.

### Modified Capabilities
(none — this is additive; existing merge and transcription logic is reused, not changed in behavior)

## Impact

- `meet_recorder/recorder.py`: new functions to list/validate orphaned `.in-progress/` subdirectories and reuse `_merge_to_stereo`-equivalent logic for recovery (likely extracting the merge/cleanup steps so both `stop_recording_and_save` and recovery can call them).
- `meet_recorder/handlers.py`: new `handler_recover` CLI command.
- `meet_recorder/menubar.py`: recovery scan triggered on app startup (after run loop is live), reusing `rumps.alert` and the existing background-transcription pattern from `on_stop`.
- `meet_recorder/transcriber.py`: no changes expected; reused as-is for recovered recordings.
- No new dependencies; `soundfile` is already a dependency.
