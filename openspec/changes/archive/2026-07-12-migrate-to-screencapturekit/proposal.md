# Migrate system-audio capture to ScreenCaptureKit

## Why

BlackHole requires routing all system output through a Multi-Output Device, which removes the ability to control system volume during a recording and depends on an external virtual audio driver plus the `SwitchAudioSource` binary. ScreenCaptureKit (macOS 13+) captures system audio natively without touching the output device, so volume stays controllable, no driver install is needed, and an entire class of failure modes (misrouted output, output device stuck after a crash) disappears.

## What Changes

- Replace the BlackHole `sounddevice.InputStream` for the system-audio channel with an `SCStream` (ScreenCaptureKit via pyobjc) configured with `capturesAudio = True` and a minimal (discarded) video stream.
- **BREAKING** Remove automatic output-device switching entirely: no more Multi-Output Device, no `SwitchAudioSource` dependency, no save/restore of the previous output device.
- **BREAKING** Lower the capture sample rate from 44.1kHz to 16kHz for both channels. ScreenCaptureKit only guarantees 8/16/24/48kHz; 16kHz matches what Whisper-family transcription models consume internally (they resample everything to 16kHz), cuts disk usage ~2.8x versus today, and the microphone channel moves to 16kHz too so the merge stays single-rate.
- Convert ScreenCaptureKit's Float32 interleaved stereo buffers to mono float32 chunks before enqueueing, so the existing writer-thread/incremental-disk/merge pipeline is unchanged.
- Reword the system-audio silence warning: it no longer indicates Multi-Output misrouting, but remains as the safety net for broken Screen Recording permission or a capture callback that never fires.
- Microphone capture stays on `sounddevice` (scope decision: single-source swap first; unifying mic capture into ScreenCaptureKit is a possible follow-up).
- New `meet_recorder/sck_capture.py` module isolates the ScreenCaptureKit/pyobjc plumbing (delegate, dispatch queue, sync bridge over the async SCK completion handlers) behind a small `start`/`stop` interface. No CLI run-loop changes needed — verified during implementation that GCD-delivered completion handlers work with the existing blocking `handler_record` unmodified (see design.md D7).
- New runtime requirement: the process running the app needs macOS Screen Recording permission (instead of a BlackHole driver install).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `audio-capture`:
  - "Automatic output device switching" requirement is **removed**.
  - "Dual-source stereo recording" changes its system-audio source from BlackHole input device to ScreenCaptureKit stream, and the recording quality scenario changes from 44.1kHz to 16kHz.
  - "System-audio silence warning" changes its rationale/wording from Multi-Output routing checks to capture-health checks (permission/callback failures).
  - New requirement: capture prerequisites (Screen Recording permission granted to the running process; macOS 13+).

## Impact

- **Code**: `meet_recorder/sck_capture.py` (new), `meet_recorder/recorder.py` (system-audio stream source, removal of device-switching helpers and `previous_output_device` state, `SAMPLE_RATE` 44100→16000), `meet_recorder/menubar.py` (silence-warning notification text only), `tests/test_sck_capture.py` (new), `tests/test_recorder.py`, `tests/test_handlers.py`.
- **Dependencies**: add `pyobjc-framework-ScreenCaptureKit`, `pyobjc-framework-CoreMedia`, `pyobjc-framework-Quartz`, `pyobjc-framework-libdispatch`; drop the runtime requirement on BlackHole and `SwitchAudioSource`.
- **Environment/config**: `MULTI_OUTPUT_DEVICE_NAME` env var becomes obsolete; Screen Recording permission must be granted to the invoking process (Terminal for dev, the LaunchAgent-spawned process for `com.alisson.meet-recorder.plist` usage — TCC behavior under launchd is a known risk, see design).
- **Docs**: README setup instructions (BlackHole/Multi-Output section replaced by Screen Recording permission), `blackhole-python-guide.md` superseded by `screencapture-guide.md`.
