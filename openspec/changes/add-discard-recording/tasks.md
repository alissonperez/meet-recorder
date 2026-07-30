## 1. Recorder: teardown refactor + discard

- [x] 1.1 Extract stream/thread/state teardown from `stop_recording_and_save()` into a shared `_teardown_capture()` helper, returning the paths/temp_dir needed for merging
- [x] 1.2 Update `stop_recording_and_save()` to use `_teardown_capture()` then call `merge_and_cleanup()` as before
- [x] 1.3 Add `discard_recording()` that calls `_teardown_capture()` then `shutil.rmtree(temp_dir, ignore_errors=True)`, skipping the merge, and raises `RuntimeError` if no recording is in progress (mirroring `stop_recording_and_save()`)
- [x] 1.4 Add/update unit tests in `tests/test_recorder.py` covering `discard_recording()` (no output file written, temp dir removed, error when idle) and confirming `stop_recording_and_save()` still behaves the same after the refactor

## 2. Menu bar: "Descartar" item

- [x] 2.1 Add `discard_item = rumps.MenuItem('Descartar', callback=None)` and insert it into `self.menu` after "Parar e não transcrever"
- [x] 2.2 Toggle `discard_item`'s callback alongside the other recording-dependent items in `_set_recording_state()`
- [x] 2.3 Implement `on_discard(self, _)`: show a confirmation alert ("Descartar gravação?" / ok="Descartar" / cancel="Cancelar") via `_show_alert`; on confirm, call `recorder.discard_recording()`, log it, and call `_set_recording_state(False)`; on cancel, do nothing
- [x] 2.4 Add/update unit tests in `tests/test_menubar.py` covering: item enabled only while recording, confirm discards and resets state, cancel leaves recording running and state untouched

## 3. Docs

- [x] 3.1 Update `docs/prompts.md` only if this change affects dynamic context sent to a configurable prompt (it does not — discard never reaches transcription/summary, so no update needed; confirm this during implementation)
