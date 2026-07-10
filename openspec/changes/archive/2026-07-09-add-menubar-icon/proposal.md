## Why

Meet Recorder currently only exposes recording via a CLI test entrypoint (`handler_record(duration)`), which requires a terminal and a fixed, pre-specified duration. To make recording usable day-to-day, users need a way to start and stop recording on demand from the macOS menu bar, without opening a terminal, while getting visual feedback and alerts if something goes wrong.

## What Changes

- Add a `meet_recorder/menubar.py` module built on `rumps` that:
  - Shows a menu bar icon with a neutral state when idle and a red-indicator state while recording.
  - Exposes a submenu with three always-visible items — **Iniciar**, **Parar**, **Sair** — where the item not applicable to the current state (e.g. "Parar" while idle) is disabled rather than hidden.
  - Calls the existing `recorder.start_recording()` / `recorder.stop_recording_and_save()` functions unchanged — no changes to `meet_recorder/recorder.py`'s capture logic.
  - Shows a modal alert (`rumps.alert`) if `recorder.start_recording()` raises (e.g. mic or BlackHole device not found, `SwitchAudioSource` failure).
  - Surfaces the existing system-audio silence condition (currently only `logger.warning` inside `recorder.py`) as a native macOS notification when running under the menu bar app.
  - On "Sair", if a recording is in progress, stops and saves it automatically before quitting (no data loss, no blocking prompt).
- Add `handler_menubar()` to `meet_recorder/handlers.py`, following the existing `handler_*` convention, that launches the `rumps.App` run loop (blocking, main-thread) — a new CLI subcommand (`python main.py menubar`) that starts the menu bar app.
- Add `rumps` as a dependency in `pyproject.toml`.

## Capabilities

### New Capabilities
- `menubar-app`: macOS menu bar icon and submenu (start/stop/quit) for controlling recording, with visual recording indicator, error alerts, and silence notifications.

### Modified Capabilities
_None — `audio-capture` requirements are unchanged; the menu bar only calls the existing public functions._

## Impact

- **New files**: `meet_recorder/menubar.py`.
- **Modified files**: `meet_recorder/handlers.py` (new `handler_menubar`), `pyproject.toml` (new `rumps` dependency).
- **New Python dependencies**: `rumps` (latest version).
- **Out of scope**: launch-at-login / auto-start on boot (manual start for now, future proposal), recording duration display in the menu bar title, custom `.icns`/PNG icon assets (uses a built-in indicator for now).
