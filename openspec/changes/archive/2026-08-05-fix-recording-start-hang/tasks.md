## 1. Recorder: refresh device list before opening the input stream

- [x] 1.1 Add a `_refresh_audio_devices()` helper in `meet_recorder/recorder.py` that calls `sd._terminate()` then `sd._initialize()`, with a short comment noting these are the private `sounddevice` calls used to force PortAudio to re-enumerate CoreAudio devices.
- [x] 1.2 Call `_refresh_audio_devices()` at the start of `start_recording()`, before `_find_default_mic_device()` is called.
- [x] 1.3 Add/update unit tests in `tests/test_recorder.py` asserting `start_recording()` triggers the refresh (e.g. monkeypatch `recorder.sd._terminate`/`recorder.sd._initialize` and assert both are called before device lookup), covering both the success path and the existing failure-cleanup paths (`test_start_recording_cleans_up_when_*`) so the refresh doesn't break existing cleanup behavior.

## 2. Menu bar: move start off the main thread

- [x] 2.1 In `meet_recorder/menubar.py`, add a `self._start_in_progress` flag (initialized `False` in `__init__`) guarding against concurrent start attempts.
- [x] 2.2 Refactor `on_start` to: return immediately (no-op) if `self._start_in_progress` is already `True`; otherwise set it `True`, disable `start_item`'s callback (so a rapid double-click can't race the flag check), and spawn a daemon `threading.Thread` that calls `recorder.start_recording()`.
- [x] 2.3 On the background thread, on success, use `AppHelper.callAfter` to marshal clearing `self._start_in_progress` and calling `self._set_recording_state(True)` back to the main thread.
- [x] 2.4 On the background thread, on failure, use `AppHelper.callAfter` to marshal clearing `self._start_in_progress`, restoring `start_item`'s callback to `self.on_start` (so retry is possible), and showing the existing failure alert (`rumps.alert(title='Failed to start recording', message=str(e))`).
- [x] 2.5 Apply the same background-thread + `callAfter` treatment to the autorecord confirmed-start path (`_maybe_start_recording`, `menubar.py:311-319`), reusing a shared helper instead of duplicating the thread/marshal logic between the two call sites.
- [x] 2.6 Add/update unit tests in `tests/test_menubar.py` covering: a slow/blocking `recorder.start_recording()` does not prevent other menu actions from being invoked while it's pending; a second `on_start` call while one is in flight is a no-op; failure still shows the alert and re-enables "Iniciar"; success still enables "Parar"/"Parar e não transcrever"/"Descartar" as before.

## 3. Verification

- [x] 3.1 Run `poetry run pytest` and `make lint`, fix any failures.
- [x] 3.2 Manually verify via `poetry run python main.py menubar`: start a recording normally (confirms no regression), and simulate a slow start (e.g. temporarily monkeypatch/sleep in `start_recording` or unplug/replug an audio device beforehand) to confirm the menu bar stays responsive and "Iniciar" is disabled until the attempt resolves.
