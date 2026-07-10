## 1. Recorder module: extract reusable merge/cleanup + orphan discovery

- [x] 1.1 Extract a helper in `meet_recorder/recorder.py` that merges an explicit `mic_path`/`sys_path` pair into a final stereo `.wav` and removes the given temp directory (factored out of `stop_recording_and_save` so both the normal stop flow and recovery call the same code)
- [x] 1.2 Add a function to list candidate orphan subdirectories under `~/MeetRecordings/.in-progress/`
- [x] 1.3 Add a validation function that opens a candidate's `mic.wav`/`sys.wav` with `soundfile` and returns whether both are readable and non-empty
- [x] 1.4 Add a function that, given the list of candidates, deletes (via `shutil.rmtree`) any candidate failing validation and returns the remaining valid orphans
- [x] 1.5 Add a function to delete a given valid orphan directory without processing it (used by the "Apagar" action)

## 2. CLI: `handler_recover`

- [x] 2.1 Add `handler_recover` to `meet_recorder/handlers.py`, wired up automatically via the existing `handler_` prefix convention (no manual registration needed)
- [x] 2.2 Implement the scan + auto-discard-invalid step, reporting "nothing to recover" and exiting early if no valid orphans remain
- [x] 2.3 Implement the terminal prompt (`input()`) describing the count of pending recordings and offering process/ignore/delete
- [x] 2.4 Wire the "Processar" choice to merge each valid orphan (via the task 1.1 helper) and then call `transcriber.transcribe(path)` for each, one at a time in series, logging progress per recording
- [x] 2.5 Wire the "Ignorar" choice to exit without touching any files
- [x] 2.6 Wire the "Apagar" choice to delete every valid orphan directory (task 1.5) without processing

## 3. Menu bar: boot-time recovery prompt

- [x] 3.1 Add a mechanism in `meet_recorder/menubar.py` to run the scan once after the `rumps` run loop has started (e.g. a one-shot `rumps.Timer` fired shortly after `run()` begins), not inside `MenubarApp.__init__`
- [x] 3.2 Skip showing any alert if no valid orphans are found after auto-discarding invalid ones
- [x] 3.3 Show a `rumps.alert` describing the count of pending recordings with three buttons/options mapping to process/ignore/delete
- [x] 3.4 Wire "Processar" to run the merge+transcribe recovery in a background thread (reusing the same `active_transcriptions` counter and `_refresh_title()` pattern used by `_transcribe_in_background`), processing orphans one at a time in series
- [x] 3.5 Wire "Ignorar" to leave files untouched and dismiss the alert
- [x] 3.6 Wire "Apagar" to delete every valid orphan directory without processing

## 4. Manual verification

- [x] 4.1 Simulate a crash: start a recording via CLI or menu bar, `kill -9` the process mid-recording, confirm `.in-progress/<timestamp>/` remains with partial `mic.wav`/`sys.wav`
- [x] 4.2 Run `recover` CLI against that orphan, choose "Processar", confirm a stereo `.wav` appears in `~/MeetRecordings/` and transcript/summary files are produced
- [x] 4.3 Repeat the crash simulation, choose "Ignorar", confirm the orphan directory is untouched and is detected again on the next scan
- [x] 4.4 Repeat the crash simulation, choose "Apagar", confirm the orphan directory is removed and nothing is produced in `~/MeetRecordings/`
- [x] 4.5 Truncate/corrupt a `mic.wav` in an orphan directory (or create an empty one) and confirm it is auto-discarded without any prompt appearing
- [x] 4.6 Launch the menu bar app with one or more valid orphans present and confirm the `rumps.alert` appears after launch (not blocking icon appearance) and each action works as in the CLI checks above
