## 1. Setup

- [x] 1.1 Add `rumps` as a dependency via `poetry add rumps` (latest version, no pin)

## 2. Recorder module hook for silence notifications

- [x] 2.1 Add an optional module-level callback hook in `meet_recorder/recorder.py` (e.g. `on_silence_warning`) that `_silence_monitor_loop` invokes alongside the existing `logger.warning` call, defaulting to a no-op so the CLI-only path is unchanged
- [x] 2.2 Confirm `recorder.py` still has no import of `rumps` or any UI-specific code

## 3. Menu bar app module

- [x] 3.1 Create `meet_recorder/menubar.py` with a `rumps.App` subclass exposing the "Iniciar" / "Parar" / "Sair" menu items
- [x] 3.2 Implement idle vs. recording icon state (neutral icon by default, red-indicator icon while recording)
- [x] 3.3 Implement "Iniciar" callback: call `recorder.start_recording()`, update icon and enable/disable menu items on success; on exception, show `rumps.alert(...)` describing the failure and leave state unchanged
- [x] 3.4 Implement "Parar" callback: call `recorder.stop_recording_and_save()`, update icon and enable/disable menu items
- [x] 3.5 Wire `recorder.on_silence_warning` to trigger `rumps.notification(...)` while the menu bar app is running
- [x] 3.6 Implement "Sair" callback: if a recording is in progress, call `recorder.stop_recording_and_save()` first, then quit the application
- [x] 3.7 Set initial menu state on launch so "Parar" starts disabled and "Iniciar" starts enabled

## 4. CLI entrypoint

- [x] 4.1 Add `handler_menubar()` to `meet_recorder/handlers.py` (using the existing `@handler` decorator) that constructs and runs the `rumps.App`
- [x] 4.2 Verify `python main.py menubar` launches the app and `python main.py --help` lists it

## 5. Manual verification

- [x] 5.1 Verify starting and stopping a recording via the menu bar produces the same `.wav` output as `handler_record`
- [x] 5.2 Verify the alert appears when starting with BlackHole/mic unavailable (simulate by temporarily renaming/disconnecting the device or mocking the lookup)
- [x] 5.3 Verify the silence notification appears when the Multi-Output Device is not selected as system output during a recording
- [x] 5.4 Verify quitting via "Sair" while recording saves a valid file before the app exits
- [x] 5.5 Run `make lint`
