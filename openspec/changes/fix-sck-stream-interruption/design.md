## Context

`meet_recorder/sck_capture.py` wraps a ScreenCaptureKit `SCStream` behind `start()`/`stop()` and a `CaptureHandle`. `_CaptureDelegate.stream_didStopWithError_` is SCK's callback for an unrequested stop; today it only logs. `CaptureHandle._active` already exists but is only used to gate `stream_didOutputSampleBuffer_ofType_` — it is never flipped by the delegate's stop callback, and nothing reads it after the fact.

`meet_recorder/recorder.py::_teardown_capture` unconditionally calls `sck_capture.stop(_state['sys_handle'])` when a recording ends, whether the stream is still alive or already died. `stop_recording_and_save` (recorder.py:374) has no way to know the system-audio stream died early, so a truncated recording is reported to the caller (and thus the menubar UI / logs) exactly like a clean one.

## Goals / Non-Goals

**Goals:**
- Detect, on the `CaptureHandle`, that SCK stopped the stream on its own (not via our `stop()` call).
- Stop `stop()` from calling `stopCaptureWithCompletionHandler_` a second time on an already-dead stream (removes the -3808 log noise).
- Surface a warning through the existing logger when `stop_recording_and_save` completes after an unexpected mid-recording stop, so the truncation is visible instead of silent.

**Non-Goals:**
- No automatic recovery/restart of the SCK stream after an unexpected stop — out of scope for this fix.
- No change to the menubar UI's visual state machine beyond whatever the existing warning-logging path already surfaces (this repo's silence-warning path already goes through `logger.warning`, not a UI dialog).
- No change to how microphone-side (`sd.InputStream`) failures are handled.

## Decisions

- **Track state on `CaptureHandle`, not as a callback.** Add `handle.stopped_unexpectedly = False` at construction, and set it to the stringified error inside `stream_didStopWithError_` before flipping `handle._active = False`. This mirrors the existing pattern of stashing capture state on the handle (channels, `_format_logged`) rather than introducing a new callback/event plumbing across the SCK delegate boundary, which runs on an SCK-owned dispatch thread.
  - Alternative considered: an `on_unexpected_stop` callback passed into `start()`. Rejected — adds cross-thread callback complexity for no benefit, since `recorder.py` already polls `sys_handle` synchronously at teardown.
- **`stop()` becomes a no-op body (skip the SCK call) when `handle._active` is already `False`.** This is the direct fix for the -3808 double-stop error, and it's a natural extension of `_active`'s existing meaning ("the stream is still running from our point of view").
- **`recorder.py` reads `sys_handle.stopped_unexpectedly` inside `_teardown_capture`, before the handle is cleared to `None`,** and `stop_recording_and_save` logs a `logger.warning(...)` after the merge if it was set, naming the saved file path so the user can correlate the warning with a specific recording. Detection happens in `_teardown_capture` (single place both `stop_recording_and_save` and `discard_recording` funnel through) but the warning is only emitted from `stop_recording_and_save`, since `discard_recording` throws the file away regardless.
  - Alternative considered: raising an exception from `stop_recording_and_save` on unexpected stop. Rejected — the recording is still valid audio up to the interruption point and should still be saved; failing the whole save would lose that partial data from the caller's perspective.

## Risks / Trade-offs

- [SCK may call `stream_didStopWithError_` on a background dispatch queue concurrently with the main thread reading `_active`] → Python's GIL makes the single boolean/attribute set and read atomic enough for this use case (matches the existing unsynchronized use of `_active` in the output callback); no lock introduced.
- [A stream that stops unexpectedly very close to when `stop()` is independently invoked could race] → `stop()` checks `_active` once at entry; worst case is one harmless extra/skipped SCK call, not a correctness issue for the audio data already written.
