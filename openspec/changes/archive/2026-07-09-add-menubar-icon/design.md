## Context

`meet_recorder/recorder.py` already implements dual-source capture as a UI-agnostic module (`start_recording()`, `stop_recording_and_save()`, module-level `_state` dict) exercised today via `handler_record(duration)` in `meet_recorder/handlers.py` (a `python-fire` CLI subcommand via the `@handler` decorator in `meet_recorder/tools.py`). That decorator injects `verbose`/`dryrun` and runs coroutine handlers via `asyncio.run(...)`.

This change adds the menu bar UI that `recorder.py` was explicitly designed to support without modification (see the archived `capture-audio-blackhole` design: "the future menu bar can call the exact same functions the CLI handler calls today"). A menu bar app needs a persistent, event-driven process with a native macOS run loop — a fundamentally different execution model than the fire CLI's "run one command and exit."

## Goals / Non-Goals

**Goals:**
- Start/stop recording from a menu bar icon, reusing `recorder.start_recording()` / `recorder.stop_recording_and_save()` unchanged.
- Visual state: neutral icon when idle, red-indicator icon while recording.
- Submenu with **Iniciar**, **Parar**, **Sair** always visible; the inapplicable action is disabled per state.
- Modal alert on start failure (device not found, `SwitchAudioSource` failure).
- Native notification when the system-audio channel is detected as silent for a sustained period.
- Clean quit: auto-stop-and-save if a recording is in progress when "Sair" is clicked.
- New `handler_menubar()` fire subcommand to launch the app (`python main.py menubar`).

**Non-Goals:**
- Launch-at-login / auto-start on boot (manual start for now).
- Recording duration/timer shown in the menu bar title.
- Custom icon assets (`.icns`/PNG) — uses `rumps`' built-in title/icon mechanism (emoji or text glyph) for now.
- Packaging as a standalone `.app` bundle (e.g. `py2app`) — runs via `poetry run python main.py menubar` for now.
- Any change to `recorder.py`'s capture, device-switching, or silence-detection logic.

## Decisions

**1. `rumps` for the menu bar framework.**
`rumps` is a thin, well-established wrapper over PyObjC/Cocoa purpose-built for exactly this (`rumps.App`, `rumps.MenuItem`, `rumps.notification`, `rumps.alert`). Alternatives considered: raw PyObjC (much more boilerplate for no added value here) and a separate native Swift menu bar app (would duplicate `recorder.py`'s logic across two languages/processes — rejected, since the whole point of `recorder.py` being UI-agnostic was to avoid exactly this). `rumps` keeps everything in one Python process and one dependency.

**2. New `handler_menubar()` runs `rumps.App.run()` directly, bypassing the async path.**
`rumps.App.run()` is a blocking call that must run on the main thread (it drives the Cocoa run loop). The existing `@handler` decorator supports both sync and `asyncio.run(...)`-wrapped coroutine handlers — `handler_menubar` will be a plain sync `@handler`-decorated function that constructs the `rumps.App` and calls `.run()`, same shape as any other blocking CLI command today. No changes needed to `tools.py`.

**3. Silence monitoring stays inside `recorder.py`; the menu bar module only adds a listener side-effect.**
Rather than duplicating the RMS/silence-window logic, `menubar.py` will attach a callback (or poll a small state flag exposed by `recorder.py`) so the existing `_silence_monitor_loop` can trigger a `rumps.notification(...)` when running under the menu bar, while the plain `logger.warning` remains the source of truth for the CLI. Minimal surface change to `recorder.py`: expose an optional callback hook (e.g. a module-level `on_silence_warning` set by `menubar.py`) rather than importing `rumps` into `recorder.py` (`recorder.py` must stay UI-agnostic per the original design — it must not import `rumps`).

**4. Menu items are always visible, state toggles `enabled`.**
`rumps.MenuItem` supports `.set_callback(None)` to disable an item (grays it out, blocks clicks) without removing it from the menu. This avoids the flicker/reflow of dynamically adding/removing items and keeps the three-item menu structure constant, matching the decision made during exploration.

**5. Auto-stop-and-save on quit.**
The `Sair` (quit) callback checks whether a recording is in progress (via `recorder`'s state) and, if so, calls `stop_recording_and_save()` before calling `rumps.quit_application()`. This guarantees no partial/lost recording, at the cost of a brief delay on quit while the file is written — acceptable given recordings are typically short-lived WAV writes.

**6. New dependency installed at latest version.**
Per the project's stated implementation principle (carried over from `capture-audio-blackhole`), `rumps` is added via `poetry add rumps` (no pinned old version) to pick up the latest release at implementation time.

## Risks / Trade-offs

- **[Risk]** `rumps.App.run()` blocks the main thread indefinitely; if `start_recording()` raises inside a menu callback, an uncaught exception could crash the whole menu bar app, not just the recording attempt. → **Mitigation**: wrap the "Iniciar" callback's call to `recorder.start_recording()` in a try/except that shows `rumps.alert(...)` and leaves the app running.
- **[Risk]** `recorder._state` is currently a private module-level dict; `menubar.py` needs to know "is a recording in progress" for menu enabling and quit handling. → **Mitigation**: use the same public/observable surface already implied by `stop_recording_and_save()` raising `RuntimeError('No recording is in progress')` — wrap calls in try/except rather than reaching into `_state` directly, or add a minimal public `recorder.is_recording()` helper if needed during implementation.
- **[Trade-off]** No `.app` bundle packaging means the app runs attached to a terminal process (`poetry run python main.py menubar`) rather than being launchable from Finder/Spotlight. Acceptable for V1 per the explicit non-goal; revisit if launch-at-login is added later.
