## Why

Meet Recorder currently has no audio capture capability — it's an empty CLI scaffold. To record meetings we need to capture both the local microphone and the computer's system audio (the other participants) at the same time, using BlackHole as the virtual audio driver, so the two sources can later be told apart (e.g. for transcription/diarization). This proposal delivers that capture capability as a standalone, UI-agnostic module and a CLI handler to exercise it, laying the groundwork for a future menu bar interface without coupling the two.

## What Changes

- Add a `meet_recorder/recorder.py` module that:
  - Discovers the system's default microphone input and the BlackHole 2ch input at record time (no hardcoded device names).
  - Opens simultaneous input streams for mic and system audio (via BlackHole).
  - Writes a single stereo `.wav` file per recording: channel 0 = microphone, channel 1 = system audio. No mixing/summing of channels.
  - Records at 44.1kHz.
  - Switches the system's audio output device to the Multi-Output Device automatically when recording starts (via `SwitchAudioSource`), and restores the previously active output device when recording stops.
  - Monitors the RMS level of the system-audio channel while recording and emits a warning (log) if it stays silent for a sustained period, signaling the Multi-Output Device likely isn't selected as output.
  - Saves output files to `~/MeetRecordings/<timestamp>.wav`.
- Add `handler_record(duration, ...)` to `meet_recorder/handlers.py`, following the existing `handler_*` convention (auto-exposed as a CLI command via `python-fire`), that records for a fixed duration and saves the file — this is a manual test entrypoint, not the final UX.
- Document the one-time manual Audio MIDI Setup step (creating the "Multi-Output (BlackHole)" device) as an onboarding step in the README.
- Add `switchaudio-osx` and audio capture dependencies (`sounddevice`, `numpy`, `soundfile`) to `pyproject.toml`, and document the `blackhole-2ch` + `switchaudio-osx` brew dependencies in the README.

## Capabilities

### New Capabilities
- `audio-capture`: Simultaneous dual-source (mic + system) audio recording to a single stereo WAV file, with automatic output-device switching and system-audio silence detection.

### Modified Capabilities
_None — no existing specs in this repo yet._

## Impact

- **New files**: `meet_recorder/recorder.py`, `~/MeetRecordings/` (runtime output directory, not part of the repo).
- **Modified files**: `meet_recorder/handlers.py` (new `handler_record`), `pyproject.toml` (new deps), `README.md` (onboarding steps + system dependencies).
- **New system dependencies**: `blackhole-2ch` and `switchaudio-osx` (Homebrew), plus one-time manual Multi-Output Device setup in Audio MIDI Setup.
- **New Python dependencies**: `sounddevice`, `numpy`, `soundfile`.
- **Out of scope**: menu bar UI (future proposal), transcription/diarization, programmatic detection/creation of the Multi-Output Device.
