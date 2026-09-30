## Why

ScreenCaptureKit stops the system-audio stream on its own mid-recording (observed twice in practice: `SCStreamErrorDomain` code -3805, "app connection interruption"). Today the app only *detects* the stop and warns about it — it never tries to bring the stream back, so every interruption costs the user the entire remaining system-audio track of the meeting, even when the underlying fault was transient and would have cleared seconds later.

This is the last open follow-up of [issue #22](https://github.com/alissonperez/meet-recorder/issues/22) ("attempt to restart capture"). The other two follow-ups from that issue — detecting the unexpected stop and surfacing it, and treating the redundant -3808 stop as a benign no-op — shipped in `fix-sck-stream-interruption`, and the truncation it described was separately eliminated by the frame-alignment padding in `fix-mic-device-switch`. Landing this change closes #22.

## What Changes

- The recorder gains a **system-audio restart supervisor**: when the ScreenCaptureKit stream stops unexpectedly during an in-progress recording, a background watcher notices the dead handle and attempts to start a fresh stream, rather than leaving system audio dead for the rest of the recording.
- Restart attempts are **bounded with exponential backoff** — up to 5 attempts spaced 1s, 2s, 4s, 8s, 16s — so a transient interruption recovers within seconds while a permanent fault (e.g. Screen Recording permission revoked) stops retrying after roughly half a minute instead of hammering the OS for the rest of the meeting.
- The attempt budget **resets after the restarted capture has been healthy for a sustained period**, so a long meeting hit by two unrelated interruptions far apart is fully recovered from both, while a stream that keeps dying immediately after each restart still terminates the retry loop.
- A restarted stream **reuses the existing system-audio chunk callback**, so it keeps writing to the same temporary file and the same recording; the existing padding thread fills the outage with silence, keeping both channels frame-aligned exactly as it does during a microphone device switch.
- The **unexpected-stop warning emitted at save time distinguishes recovery from failure**: a recording whose stream was restarted reports the interruption and the resulting silent gap(s), while one whose restarts were exhausted reports that system audio was lost from that point onward. Interruptions are accumulated across the recording rather than read off whichever handle happens to be live at teardown.
- The menu bar **notifies on interruption and again on restoration**, so the user can tell mid-meeting that system audio dropped and that it came back, instead of discovering it after the fact.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `audio-capture`: adds a requirement that an unexpectedly stopped system-audio stream is automatically restarted under a bounded, backing-off retry budget that resets after sustained healthy capture, that a restarted stream continues writing to the same recording with the outage padded as silence, and amends the existing unexpected-stop requirement so the save-time warning distinguishes a recovered interruption from an unrecoverable one and reflects every interruption in the recording rather than only the last.
- `menubar-app`: adds requirements for a notification when system-audio capture is interrupted and a further notification when it is restored.
- `test-suite`: adds coverage for the restart supervisor — successful restart, backoff schedule, budget exhaustion, budget reset after healthy capture, no restart after a user-requested stop, and the recovered-vs-exhausted warning wording.

## Impact

- `meet_recorder/sck_capture.py`: `CaptureHandle` / `_CaptureDelegate.stream_didStopWithError_` must expose the unexpected stop in a form the supervisor can poll without racing teardown.
- `meet_recorder/recorder.py`: new restart supervisor thread and its start/stop lifecycle (alongside `_start_silence_monitor` / `_start_padding_thread`), new interruption bookkeeping in `_state`, `_teardown_capture` returning the accumulated interruption history instead of a single handle field, and the `stop_recording_and_save` warning text.
- `meet_recorder/menubar.py`: new `on_sys_capture_interrupted` / `on_sys_capture_restored` hooks wired to notifications, following the existing `on_silence_warning` main-thread marshalling pattern.
- `tests/test_recorder.py`, `tests/test_sck_capture.py`, `tests/test_menubar.py`: coverage for the above.
- `docs/prompts.md`: not affected (no change to prompt context).
- GitHub: the pull request for this change must close [issue #22](https://github.com/alissonperez/meet-recorder/issues/22).
