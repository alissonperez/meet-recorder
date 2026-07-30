## Context

`meet_recorder/recorder.py` holds a single module-level `_state` dict tracking the active mic stream, system-audio handle, writer threads, and a temp directory (`mic.wav` + `sys.wav`) written incrementally during capture. `stop_recording_and_save()` tears this down and calls `merge_and_cleanup()`, which merges the two temp files into a final stereo `.wav` in the recordings directory and removes the temp directory. `meet_recorder/menubar.py` exposes "Parar" and "Parar e não transcrever", both of which call `stop_recording_and_save()` and differ only in whether they kick off a background transcription afterward.

## Goals / Non-Goals

**Goals:**
- Let the user discard an in-progress recording entirely: stop capture, delete the temp mic/system-audio buffers, and never write a final `.wav`.
- Guard the action behind a confirmation modal, since it's destructive and irreversible.
- Reuse the existing capture-teardown logic rather than duplicating it.

**Non-Goals:**
- Discarding a recording that has already been stopped and saved (out of scope; the file can be deleted manually from Finder).
- Undo/trash-can semantics — a discarded recording's temp buffers are deleted immediately, not moved to a recoverable location. This mirrors `delete_orphan()`'s existing behavior for orphaned recordings.

## Decisions

- **New `recorder.discard_recording()` function**, factored out of `stop_recording_and_save()`: extract the stream/thread teardown (mic stream stop/close, `sck_capture.stop`, writer thread joins, `_state` reset) into a shared `_teardown_capture()` helper. `stop_recording_and_save()` calls it then `merge_and_cleanup()`; `discard_recording()` calls it then `shutil.rmtree(temp_dir, ignore_errors=True)` instead, skipping the merge. This avoids duplicating the teardown sequence and keeps the two paths from drifting apart.
- **Confirmation via the existing `NSAlert`-based `_show_alert` helper** in `menubar.py`, consistent with the orphan-recovery and quit-with-transcriptions confirmations already in the app, rather than `rumps.alert` (which cannot be styled with custom button labels as easily and isn't used elsewhere for confirm/cancel). Buttons: "Descartar" (destructive, ok) / "Cancelar" (cancel).
- **Menu item enablement mirrors "Parar"**: enabled only while `is_recording`, toggled in `_set_recording_state()` alongside the other two recording-dependent items.
- **No transcription path**: discarding never starts a transcription thread and never increments `active_transcriptions`, since there is no output file to transcribe.

## Risks / Trade-offs

- [Accidental data loss if the user misclicks "Descartar" and confirms] → Mitigated by the required confirmation modal; no further mitigation (e.g. soft-delete/trash) is in scope per Non-Goals.
- [Teardown refactor could subtly change `stop_recording_and_save()` behavior] → Keep the extracted `_teardown_capture()` helper a pure refactor (same operations, same order, same `_state` resets) and cover both `stop_recording_and_save()` and `discard_recording()` with unit tests.
