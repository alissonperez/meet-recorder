## 1. Channel alignment foundation

- [x] 1.1 Track frames enqueued per channel in `_enqueue`, counting both written and dropped frames, so each channel's intended frame position is known independently of the writer queue
- [x] 1.2 Add a padding thread (modeled on `_silence_monitor_loop`) that periodically levels both channels to the running maximum frame count, enqueuing zeros through the lagging channel's own queue — bidirectional, with a tolerance so a merely slow channel is not inflated
- [x] 1.3 Start the padding thread in `start_recording` and stop it in `_teardown_capture`, alongside the existing silence monitor; ensure teardown performs a final levelling pass before the writers are stopped
- [x] 1.4 Verify the system-audio padding route does not interfere with `sck_capture`'s chunk delivery while the stream is alive
- [x] 1.5 Tests: dropped frames on either channel are padded so the merged output stays aligned; padding accrues continuously rather than only on resume
- [x] 1.6 Tests: a recording whose system-audio stream stops early keeps its full microphone tail instead of being truncated, and still emits the existing unexpected-stop warning

## 2. Two-channel silence monitoring

- [x] 2.1 Generalize the silence buffer and `_silence_monitor_loop` to per-channel state (buffer, lock, `silent_since`, `warned`), feeding the microphone buffer from `mic_callback` as `sys_on_chunk` already does for system audio
- [x] 2.2 Change `on_silence_warning` to identify the affected channel, keeping the system-audio warning text pointing at Screen Recording permission and giving the microphone its own text pointing at switching the input device
- [x] 2.3 Add the `on_silence_recovered` hook with a no-op default matching `_default_on_silence_warning`, fired where the loop already resets `warned` on recovery
- [x] 2.4 Decide and implement the microphone grace period at recording start (open question in design.md) so a warning does not fire in the first seconds
- [x] 2.5 Tests: independent per-channel warnings, recovery hook fires on return to signal, no warning while a channel is active

## 3. Microphone pause and resume

- [x] 3.1 Add `pause_mic()`: stop and close the current `InputStream`, leave queues, writer threads, padding thread, and system-audio capture untouched, and record the previously used device
- [x] 3.2 Add `list_input_devices()`: call `_refresh_audio_devices()` and return the current input devices; refuse to run while microphone capture is active, with a comment at the definition explaining that `sd._terminate()` invalidates live streams (mirroring the comment on `_refresh_audio_devices`)
- [x] 3.3 Add `resume_mic(device=None)`: open a new `InputStream` bound to the given device (falling back to the previous device, then the current default) using the same `mic_callback`, and restore the recording state
- [x] 3.4 Handle resume failure (unsupported sample rate or channel count) by reporting it and falling back to a usable device rather than aborting the recording
- [x] 3.5 Stop discarding `status` in `mic_callback`: log non-empty status as a warning identifying the microphone source
- [x] 3.6 Tests: system-audio capture continues across a pause; resume writes to the same `mic.wav`; abandoned pause resumes on the previous device; enumeration is refused while capture is active; resume failure falls back without stopping the recording

## 4. Menu bar icon blink

- [x] 4.1 Add a microphone-attention flag to `MenubarApp` and a blink interval constant
- [x] 4.2 Make `_current_state_name` alternate between the current state and `idle` when the flag is set, driven by a `rumps.Timer` that only runs while the flag is set
- [x] 4.3 Set the flag from the microphone silence warning and while microphone capture is paused; clear it from `on_silence_recovered` and on resume
- [x] 4.4 Resolve whether `recording_transcribing` also blinks (open question in design.md) and implement the chosen behavior
- [x] 4.5 Tests: blink toggles state names while the flag is set, stops on recovery, and leaves the four steady states unchanged when the flag is clear

## 5. Menu bar microphone switch

- [x] 5.1 Add the "Trocar microfone…" menu item, enabled and disabled by `_set_recording_state` alongside the existing recording-only items
- [x] 5.2 Implement the handler: pause microphone capture, enumerate devices, present the selection dialog built at activation time, then resume on the chosen device
- [x] 5.3 Run the pause/enumerate/resume work off the AppKit run loop and marshal results back via `AppHelper.callAfter`, following the `_start_recording_async` pattern
- [x] 5.4 Resume on the previous device when the dialog is dismissed without a selection
- [x] 5.5 Show a modal alert on switch failure via `_show_alert_on_main`, leaving the recording running
- [x] 5.6 Add the microphone silence notification and clear the alert state on recovery, alongside the existing `on_silence_warning` notification
- [x] 5.7 Tests: menu item enablement follows recording state; the dialog is built only after the pause; cancellation resumes capture; failure shows an alert without stopping the recording

## 6. Verification

- [x] 6.1 Run `poetry run pytest` and `make lint`
- [x] 6.2 Manual check: start a recording, unplug the active microphone, confirm the notification and blinking icon, switch to another device from the menu, stop and verify the saved file has both channels aligned with silence only for the switch window
- [ ] 6.3 Manual check: connect a device after the recording started and confirm it appears in the switch dialog
