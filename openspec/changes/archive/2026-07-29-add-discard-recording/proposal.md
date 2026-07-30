## Why

Sometimes a recording is started by mistake, or the meeting turns out to be irrelevant to capture (e.g. accidentally left running, wrong meeting, or the user changes their mind mid-recording). Today the only way to stop is "Parar" (stop, transcribe) or "Parar e não transcrever" (stop, save without transcribing) — both persist the audio to disk. There is no way to throw away an in-progress recording without first saving it and then manually deleting the file.

## What Changes

- Add a new "Descartar" menu item to the menu bar, enabled only while a recording is in progress (same enablement rule as "Parar" and "Parar e não transcrever").
- Clicking "Descartar" shows a confirmation modal before doing anything destructive.
- Confirming discards the entire in-progress recording: recording stops immediately, no merged `.wav` file is written to the recordings directory, and the temporary mic/system-audio buffers are deleted. No transcription is started.
- Declining the confirmation leaves the recording running untouched.
- Add a `recorder.discard_recording()` function that stops the active capture (mic stream, system-audio capture, writer threads) and deletes the temp directory without merging to a final output file, mirroring the teardown in `stop_recording_and_save()` but skipping `merge_and_cleanup`.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `menubar-app`: adds a "Descartar" menu item and its enablement/behavior, plus a confirmation-modal requirement before discarding.

## Impact

- `meet_recorder/menubar.py`: new `discard_item` menu entry, `on_discard` callback, confirmation alert, and inclusion in `_set_recording_state` enablement toggling.
- `meet_recorder/recorder.py`: new `discard_recording()` function alongside `stop_recording_and_save()`.
- `tests/test_menubar.py`, `tests/test_recorder.py` (or equivalent): new unit tests for the discard flow.
- `openspec/specs/menubar-app/spec.md`: updated via delta spec for this change.
