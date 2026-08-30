## Why

After the Mac has been awake for a long time (sleep/wake cycles, Bluetooth/USB
audio devices connecting and disconnecting), clicking "Iniciar" in the menu
bar app can hang the entire app instead of failing cleanly. `PaMacCore
(AUHAL)` errors (e.g. `-10851 Invalid Property Value`) in the logs point to
CoreAudio holding a stale default-input-device reference; opening a
`sounddevice.InputStream` against it blocks for a long time instead of
raising promptly. Because `start_recording()` currently runs synchronously on
the main thread (the same thread that runs the AppKit/rumps event loop), that
block freezes the whole menu bar UI — the icon gets stuck in a hover-highlight
state and every menu item stops responding, with no alert shown, until the
underlying call eventually returns or the user force-quits.

## What Changes

- Run `recorder.start_recording()` off the main thread when triggered from
  the menu bar (manual "Iniciar" click and autorecord's confirmed start), so
  a slow or hanging CoreAudio/PortAudio call can no longer block the AppKit
  run loop or freeze the menu. Menu state updates and the existing
  start-failure alert are marshaled back to the main thread once the call
  returns.
- Before opening the microphone `InputStream`, force `sounddevice`/PortAudio
  to refresh its device list (re-`_terminate()`/`_initialize()`) rather than
  reusing a cached device index, reducing the chance of handing CoreAudio a
  stale `AudioObjectID` in the first place.
- While a start is in flight (background thread running), disable "Iniciar"
  so a second click can't launch a concurrent start attempt.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `menubar-app`: starting a recording no longer blocks the menu bar's main
  thread/event loop; the "Iniciar" item is disabled while a start attempt is
  in flight, and the existing start-failure alert still fires (now
  dispatched from the background start) if the attempt fails.
- `audio-capture`: microphone device selection SHALL refresh PortAudio's
  device list before opening the input stream, instead of trusting a
  previously cached device index.

## Impact

- `meet_recorder/menubar.py`: `on_start`, `_maybe_start_recording` (the
  autorecord confirmed-start path), and `_set_recording_state` — start calls
  move to a background thread with results marshaled back via
  `AppHelper.callAfter`.
- `meet_recorder/recorder.py`: `_find_default_mic_device` /
  `start_recording` — add a PortAudio device-list refresh before opening the
  `InputStream`.
- No changes to the CLI `record` handler's behavior beyond whatever shared
  helper is reused for the device refresh (still synchronous there, since the
  CLI has no run loop to protect).
