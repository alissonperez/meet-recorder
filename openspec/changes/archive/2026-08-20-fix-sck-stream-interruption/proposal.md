## Why

ScreenCaptureKit can stop a stream mid-recording on its own (observed: `SCStreamErrorDomain` code -3805, "app connection interruption"). The current delegate only logs this and never marks the capture as inactive, so the recorder keeps behaving as if system-audio capture is still active, the eventual `stop()` call fails again (code -3808, "already stopped"), and the saved `.wav` is silently truncated with no indication to the user that anything went wrong. See GitHub issue #22.

## What Changes

- `stream_didStopWithError_` marks the `CaptureHandle` inactive (`_active = False`) and records the error on the handle when SCK stops the stream unexpectedly, instead of only logging it.
- `stop()` treats stopping an already-inactive handle as a no-op (skips the redundant `stopCaptureWithCompletionHandler_` call), eliminating the spurious -3808 error log.
- The recorder layer surfaces an unexpected-stop as a warning to the user (e.g. via the existing logging/menubar warning path) when a recording is saved after an unrequested SCK stream stop, so a truncated recording is not reported as a silent success.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `audio-capture`: adds a requirement that an unrequested ScreenCaptureKit stream stop during recording is detected, does not produce a duplicate stop error, and results in a user-visible warning rather than a silently truncated recording reported as successful.

## Impact

- `meet_recorder/sck_capture.py`: `_CaptureDelegate.stream_didStopWithError_`, `CaptureHandle`, `stop()`.
- `meet_recorder/recorder.py`: `stop_recording_and_save` (and the `sys_handle` stop call around line 281/353) needs to check the handle's unexpected-stop state after capture ends and emit a warning.
- `tests/test_sck_capture.py`: new coverage for the unexpected-stop path.
