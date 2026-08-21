## Why

The microphone input device is resolved once at `start_recording()` and the `sd.InputStream` stays bound to that device index for the whole recording. If the user switches microphones mid-call (USB mic → AirPods), the app silently keeps capturing from the original device — or, if that device is unplugged, captures nothing at all. Neither case produces any warning today, so the user only discovers the problem when listening to the saved file. See GitHub issue #24 (the microphone-side twin of #23).

Detecting an OS default-input change automatically would require a CoreAudio property listener, which has no precedent in this codebase. Instead this change puts the user in the loop: warn when the microphone channel goes silent, and give them a menu bar action to switch the input device without losing the recording.

## What Changes

- The existing silence monitor also watches the **microphone** channel, not just the system-audio channel, so a dead or wrong microphone is surfaced instead of being discovered after the fact.
- A new `on_silence_recovered` hook complements `on_silence_warning`, so the UI can clear an alert state when audio returns (the monitor already self-resets internally but never reports it).
- The recorder gains **pause/resume of the microphone source only**: the input stream can be closed and reopened against a different device while the ScreenCaptureKit system-audio capture keeps recording uninterrupted. Both streams continue writing to the same temporary files — no file surgery.
- Whenever either channel falls behind the other — while the microphone is paused, when frames are dropped, or when the ScreenCaptureKit stream stops early — the lagging channel is **padded with silence so both stay frame-aligned**. Because `_merge_to_stereo` zips the two temporary files by block index rather than by timestamp, any unpadded shortfall permanently desynchronizes the stereo output from that point on, and the merge additionally truncates the output to the *shorter* channel. Padding is bidirectional and written continuously rather than computed at resume, so a crash mid-pause still leaves a frame-aligned orphan for crash recovery.
- As a direct consequence of bidirectional padding, a recording whose ScreenCaptureKit stream stopped early (issue #22, change `fix-sck-stream-interruption`) is no longer **truncated** at the point of failure: the system-audio channel is padded with silence and the microphone audio recorded after the failure is preserved instead of being discarded by the merge.
- The list of available input devices is enumerated only while the microphone is paused. Enumeration requires `_refresh_audio_devices()` (`sd._terminate()` / `sd._initialize()`), which would invalidate a live `InputStream`; it must not be called during active microphone capture.
- `mic_callback` stops discarding its `status` argument — PortAudio overflow/underflow/device-invalidated flags are logged instead of silently dropped.
- The menu bar gains a **"Trocar microfone…"** action, enabled while recording, which pauses the microphone, presents a freshly enumerated device list, and resumes capture on the chosen device.
- The menu bar icon **blinks** between the recording and idle indicators whenever the microphone needs attention (silent channel, or paused during a switch). The recording indicator is a red circle, so blinking it is visible without adding a new icon asset.

Not in scope: automatic detection of an OS default-input change while the previous device is still connected and producing audio. That case is silent by construction and is left to the user-initiated switch.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `audio-capture`: adds requirements that the microphone channel is monitored for sustained silence, that the microphone source can be paused and resumed against a different device mid-recording while system-audio capture continues, and that the microphone channel stays frame-aligned with the system-audio channel across pauses and dropped frames.
- `menubar-app`: adds requirements for a microphone-switch action available during recording, a notification when the microphone channel is silent, and a blinking icon state signalling that the microphone needs attention.

## Impact

- `meet_recorder/recorder.py`: `start_recording` (`mic_callback`, device resolution), `_silence_monitor_loop` and the silence buffer (currently system-audio only), `_enqueue`, `_teardown_capture`, plus new `pause_mic` / `resume_mic` / `list_input_devices` and a padding thread.
- `meet_recorder/menubar.py`: new menu item and device-selection dialog, `_current_state_name` / `_refresh_icon` blink handling, `on_silence_warning` / new `on_silence_recovered`, `_set_recording_state` enablement.
- `tests/test_recorder.py`, `tests/test_menubar.py`: coverage for microphone silence detection, pause/resume alignment, padding, and the blink state machine.
- `docs/prompts.md`: not affected (no change to prompt context).
