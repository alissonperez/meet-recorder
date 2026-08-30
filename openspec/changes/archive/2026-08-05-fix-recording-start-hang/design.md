## Context

`rumps.App` runs its menu and all `MenuItem` callbacks on the main thread,
which is also AppKit's run loop thread. `on_start` (`menubar.py:393`) and the
autorecord confirmed-start path (`menubar.py:311-319`) both call
`recorder.start_recording()` inline from that thread. `start_recording()`
(`recorder.py:226`) opens a `sounddevice.InputStream`, which under the hood
blocks on synchronous CoreAudio calls (PortAudio's AUHAL host API). When
CoreAudio's cached default-input-device object is stale — observed after the
Mac has been awake a long time, alongside `PaMacCore (AUHAL)` /
`-10851 Invalid Property Value` errors in the logs — that open call can hang
for a long time instead of failing fast. Because it runs on the main thread,
the entire menu bar UI freezes: no redraw, no click handling, no way for the
user to even see an error.

The app already has a working pattern for keeping long operations off the
main thread while still touching AppKit safely afterward:
`_transcribe_in_background` runs stop's transcription on a daemon thread, and
`_show_alert_on_main` uses `AppHelper.callAfter` to marshal `NSAlert` calls
back to the main thread from a background poller. This change applies the
same pattern to the start path.

## Goals / Non-Goals

**Goals:**
- Starting a recording never blocks the AppKit run loop, regardless of how
  long the underlying CoreAudio/PortAudio calls take or whether they hang.
- The existing start-failure alert (`menubar-app` spec: "Start failure
  alert") still fires when the start attempt fails, from whichever thread it
  finishes on.
- Reduce the odds of hitting the stale-device hang in the first place by not
  trusting a cached PortAudio device index across app-lifetime device
  changes.
- A second "Iniciar" click while a start is already in flight can't kick off
  a concurrent `start_recording()` call.

**Non-Goals:**
- Don't add a timeout that force-aborts a hung CoreAudio call — PortAudio
  gives no safe cross-platform way to cancel an in-flight `InputStream` open,
  and killing/retrying the underlying audio unit from another thread risks
  leaving CoreAudio in a worse state. If the refresh-before-open mitigation
  doesn't fully eliminate the hang, the UI no longer freezes, which is the
  actual user-facing bug being fixed here.
- Don't change the CLI (`handler_record`) start path — it has no run loop to
  protect, so `start_recording()` stays synchronous there.
- Don't change `stop_recording_and_save`, `discard_recording`, or any other
  menu action — only the start path is affected by this hang.

## Decisions

### Run start on a background thread, marshal UI updates back to main

`on_start` and the autorecord confirmed-start path spawn a daemon thread that
calls `recorder.start_recording()`. On success or failure, the thread uses
`AppHelper.callAfter` to invoke the existing `_set_recording_state(True)` /
`rumps.alert(...)` calls back on the main thread — the same mechanism
`_show_alert_on_main` already uses. This keeps `NSAlert` and menu-state
mutation on the main thread (AppKit requirement) while the blocking
CoreAudio call itself runs elsewhere.

Alternative considered: run `start_recording()` in a `concurrent.futures`
executor with a `.result(timeout=...)`. Rejected per the timeout non-goal
above — there's no safe way to actually stop the blocked call when the
timeout fires, so a timeout would just change what the user sees (an error
while the leaked thread is still stuck) without addressing the risk of two
`InputStream` opens racing against the same device later.

### Guard against a concurrent second start attempt

While a start is in flight, `on_start` must not be re-entrant: the menu
already disables "Iniciar" only once `_set_recording_state(True)` runs, which
now happens asynchronously after the background thread finishes. Introduce a
`self._start_in_progress` flag (set before spawning the thread, cleared in
the `callAfter`-marshaled completion handler) and have `on_start` return
immediately (no-op) if it's already set. This mirrors the existing
`is_recording` guard in `start_recording()` itself
(`RuntimeError('A recording is already in progress')`), which only protects
against a second call once the first has already fully started — not against
two overlapping in-flight attempts.

### Refresh PortAudio's device list before opening the input stream

`_find_default_mic_device()` (`recorder.py:81`) reads `sd.default.device`,
which reflects whatever device list PortAudio cached at
`sounddevice` import/initialization time. Add a small helper,
`_refresh_audio_devices()`, that calls `sd._terminate()` followed by
`sd._initialize()` (the same private calls `sounddevice` itself exposes for
this purpose) immediately before device lookup in `start_recording()`, so
PortAudio re-enumerates CoreAudio's current device list rather than reusing
a snapshot from process startup.

Alternative considered: catch the PortAudio error and retry once after a
refresh. Rejected for this change — the underlying symptom is a *hang*, not
a *fast failure*, so a catch-and-retry can't run if the call never returns.
Refreshing unconditionally before every start is cheap (device
enumeration, not stream I/O) and addresses the same root cause
proactively.

This mitigation reduces the likelihood of the hang; it's not proven to
eliminate it, which is why it's paired with the background-thread fix rather
than relied on alone.

## Risks / Trade-offs

- [Background start means the UI reports success optimistically] → No —
  `_set_recording_state(True)` only runs after `start_recording()` returns
  successfully, so the icon still only flips to "recording" once capture has
  actually started; the user just isn't blocked from interacting with other
  menu items while waiting (they're disabled via `_start_in_progress`
  instead, which is a much better failure mode than the whole app freezing).
- [`sd._terminate()`/`sd._initialize()` are private `sounddevice` APIs] →
  Documented in `sounddevice`'s own source as the supported way to force a
  device-list refresh; pin the `sounddevice` version already in
  `pyproject.toml` and note the dependency in a code comment so a future
  upgrade that removes them is caught by `make lint`/tests rather than
  silently regressing.
- [A start that never returns still leaves a daemon thread running forever]
  → Acceptable: it's a daemon thread, so it doesn't block app quit, and this
  is strictly better than today's full-UI-freeze. `_start_in_progress` stays
  set (Iniciar stays disabled) in that case, which correctly reflects that
  the app doesn't know whether a recording is happening.

## Migration Plan

No data migration. Rollout is a single code change; if it regresses menu
behavior, revert the two touched files (`menubar.py`, `recorder.py`) — no
schema, config, or on-disk format changes are involved.

## Open Questions

None.
