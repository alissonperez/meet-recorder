## 1. sck_capture: detect and stop cleanly on unexpected stream stop

- [x] 1.1 Add `stopped_unexpectedly` (initially `None`) to `CaptureHandle.__init__` in `meet_recorder/sck_capture.py`
- [x] 1.2 In `_CaptureDelegate.stream_didStopWithError_`, when `error is not None`: log as today, set `handle.stopped_unexpectedly = str(error)`, and set `handle._active = False` (guard on `handle` being non-`None`, matching the existing pattern in `stream_didOutputSampleBuffer_ofType_`)
- [x] 1.3 In `stop()`, return early (skip `stopCaptureWithCompletionHandler_` and its `_run_async` call) when `handle._active` is already `False`, so a stream that already stopped unexpectedly does not get a redundant stop request / -3808 log

## 2. recorder: surface a warning when a saved recording ended early

- [x] 2.1 In `_teardown_capture` (`meet_recorder/recorder.py`), read `_state['sys_handle'].stopped_unexpectedly` before the handle is cleared to `None`, and return it (or store it) alongside the existing `mic_temp_path, sys_temp_path, temp_dir` return values
- [x] 2.2 In `stop_recording_and_save`, after `merge_and_cleanup` succeeds, call `logger.warning(...)` naming the saved file path when the teardown reported an unexpected stop
- [x] 2.3 Confirm `discard_recording` is unaffected (it discards the recording regardless, so no warning is needed there)

## 3. Tests

- [x] 3.1 In `tests/test_sck_capture.py`, add a test that invoking `stream_didStopWithError_` with a non-`None` error sets `handle.stopped_unexpectedly` and `handle._active = False`
- [x] 3.2 Add a test that `stop()` on a handle with `_active = False` does not invoke `stopCaptureWithCompletionHandler_` (no redundant SCK call / no -3808-style error path taken)
- [x] 3.3 Add a test that `stream_didStopWithError_` called with `error=None` does not set `stopped_unexpectedly` and does not flip `_active` (matches current no-op logging behavior)
- [x] 3.4 In `tests/test_recorder.py` (or equivalent), add a test that `stop_recording_and_save` logs a warning naming the output path when the system-audio handle's teardown reports `stopped_unexpectedly`
- [x] 3.5 Add a test that a normal stop (no unexpected stop) does not emit the new warning

## 4. Verification

- [x] 4.1 Run `poetry run pytest` and confirm the full suite passes
- [x] 4.2 Run `make lint` and confirm it passes
