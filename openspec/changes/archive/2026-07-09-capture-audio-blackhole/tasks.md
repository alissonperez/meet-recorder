## 1. Dependencies & environment

- [x] 1.1 Add `sounddevice`, `numpy`, `soundfile` to `pyproject.toml` dependencies at their latest available versions (e.g. via `poetry add sounddevice numpy soundfile`, not pinned to older releases) and run `poetry lock` / install
- [x] 1.2 Document `brew install blackhole-2ch switchaudio-osx` and the manual Multi-Output Device setup (Audio MIDI Setup) as an onboarding section in `README.md`
- [x] 1.3 Add any new env vars (e.g. output directory override, Multi-Output Device name) to `.env.example` with sensible defaults documented

## 2. Core capture module (`meet_recorder/recorder.py`)

- [x] 2.1 Implement device discovery: resolve system default mic input via `sounddevice`, resolve BlackHole input by name lookup
- [x] 2.2 Implement `start_recording()`: open mic + BlackHole `InputStream`s, begin buffering frames per channel
- [x] 2.3 Implement stereo write path: combine mic and system frames as separate channels (ch0/ch1) of one buffer — no summing/mixing
- [x] 2.4 Implement `stop_recording_and_save()`: stop streams, assemble stereo array, write 44.1kHz `.wav` to `~/MeetRecordings/<timestamp>.wav` (create dir if missing)
- [x] 2.5 Implement output-device switching: capture current output device before switching, switch to Multi-Output Device on start via `SwitchAudioSource`, restore original device on stop (including via a `finally`/error path)
- [x] 2.6 Implement RMS-based silence monitoring on the system-audio channel during recording, logging a one-time warning per sustained-silence episode
- [x] 2.7 Ensure all tunables (output dir, device name, silence threshold/window) read from env vars with defaults, no hardcoded paths/names outside of fallback defaults

## 3. CLI integration

- [x] 3.1 Add `handler_record(duration=..., ...)` to `meet_recorder/handlers.py` using the existing `@handler` decorator pattern, delegating entirely to `recorder.py`
- [x] 3.2 Verify `poetry run python main.py record --duration=10` performs a full start → wait → stop → save → device-restore cycle

## 4. Verification

- [x] 4.1 Manually record a short session with the Multi-Output Device correctly configured; confirm output `.wav` has mic on channel 0 and system audio on channel 1 by ear/inspection
- [x] 4.2 Manually verify output device is restored to the original device after recording stops
- [x] 4.3 Manually verify the silence warning logs when system output is *not* routed to the Multi-Output Device during a test recording
- [x] 4.4 Run `make lint` and fix any issues
