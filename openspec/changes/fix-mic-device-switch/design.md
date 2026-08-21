## Context

Two independent capture pipelines feed one recording:

```
mic  ──► sd.InputStream (PortAudio) ──► mic_queue ──► writer thread ──► mic.wav
sys  ──► sck_capture (ScreenCaptureKit) ──► sys_queue ──► writer thread ──► sys.wav
                                                                            │
                              _merge_to_stereo() zips both by BLOCK INDEX ──┘
```

Three properties of the existing code drive every decision below.

1. **The stream is pinned to a device index.** `_find_default_mic_device()` reads `sd.default.device` once (`recorder.py:89`), and PortAudio's `InputStream` does not follow "current system default input" afterwards.

2. **Refreshing the device list destroys live streams.** `_refresh_audio_devices()` (`recorder.py:81`) calls the private `sd._terminate()` / `sd._initialize()` pair to force PortAudio to re-enumerate CoreAudio. Any open `InputStream` is invalidated by that. This is not incidental — it is the only mechanism the project has for seeing devices connected after process start, and the common case (AirPods connected mid-call) is precisely a device absent from the startup snapshot.

3. **The merge is positional, not timestamped.** `_merge_to_stereo` (`recorder.py:302`) reads a block from each temporary file and zips them by index, and stops at `n = min(...) == 0`. Two consequences: a gap of N frames on one channel does not produce a gap in the output, it shifts everything after it by N frames permanently; and the output is truncated to the length of the *shorter* channel, discarding the tail of the longer one. The existing drop-on-full path in `_enqueue` (`recorder.py:130`) already desynchronizes channels today, and a ScreenCaptureKit stream that stops early already discards every subsequent minute of microphone audio that was successfully written to disk.

The writer threads are decoupled from their sources: `_writer_loop` consumes a queue and knows nothing about where chunks originated. That is what makes a device swap cheap.

## Goals / Non-Goals

**Goals:**
- Surface a dead or wrong microphone to the user during the recording, not after.
- Let the user switch the microphone mid-recording without losing system audio and without desynchronizing the output file.
- Keep both channels frame-aligned regardless of which one falls behind, so neither a paused microphone nor a dead system-audio stream shifts or truncates the saved recording.
- Reuse the existing silence-monitor, icon-state, and background-thread patterns rather than introducing new ones.

**Non-Goals:**
- Automatic detection of an OS default-input change (requires a CoreAudio `kAudioHardwarePropertyDefaultInputDevice` property listener; no PyObjC/ctypes precedent in this codebase, and the user-initiated switch covers the need).
- Automatic swap without user confirmation.
- Preserving the user's own voice during the switch window. Only the microphone channel pauses; the seconds lost are the seconds the user spends operating the menu.
- Pausing, retrying, or reconnecting the ScreenCaptureKit stream after an unexpected stop. Bidirectional padding is a prerequisite for that work, but the reconnection policy itself is a separate change (follow-up to `fix-sck-stream-interruption` / issue #22).
- Surfacing the existing unexpected-stop warning in the menu bar. `stop_recording_and_save` logs it, but `MenubarApp.on_stop` (`menubar.py:452`) discards everything but the path, so it is invisible under the menu bar app. Tracked separately.

## Decisions

### Warn + manual switch, not automatic reconnection

Change #23 established warn-only for an SCK stream that dies. Warn-only is the wrong ceiling here: switching microphones is a deliberate, routine user action mid-call, so "your recording is wrong, sorry" is a poor outcome. But full automation requires the CoreAudio listener.

The middle path is to let the user supply the detection that is expensive to automate — they know they switched — and have the app supply the mechanism. The silence warning is a prompt, not the only entry point: the switch action stays available for the whole recording, including the case where the old device keeps producing audio and nothing ever goes silent.

*Alternative rejected:* CoreAudio property listener with automatic swap. Larger surface, new dependency style, and it still needs every mechanism below.

### Enumerate devices only while the microphone is paused

Because enumeration invalidates live streams (constraint 2), ordering the operations correctly makes the conflict disappear entirely:

```
"Trocar microfone…"
   │
   ├─ 1. close current InputStream          ─┐
   ├─ 2. _refresh_audio_devices()            │  mic paused
   ├─ 3. enumerate inputs → selection dialog │  sys keeps recording
   │      (user reaction time: unbounded)    │  padding thread runs
   ├─ 4. open InputStream(chosen device)    ─┘
   └─ 5. same mic_callback → same mic_queue → same mic.wav
```

The system-audio side is untouched: ScreenCaptureKit is not PortAudio, so `sd._terminate()` does not affect it. The user keeps capturing what everyone else says throughout.

This is also why the UI is a **dialog rather than a static submenu**: the device list is only valid after step 1, and rumps offers no reliable "menu is about to open" hook to rebuild a submenu at click time.

`list_input_devices()` must therefore refuse (or be documented as invalid) when microphone capture is active. This needs an explicit comment in the same spirit as the one already on `_refresh_audio_devices` (`recorder.py:82`), because calling it at the wrong moment kills the recording in a way that is not obvious from the call site.

### Continuous bidirectional silence padding levelled by frame count

Whichever channel falls behind must be topped up with zeros. Three axes of choice:

*When to pad.* Padding at resume (compute elapsed time, enqueue one big block of zeros) is simpler, but the project has crash recovery — `list_orphan_candidates` / `.in-progress/` — and a crash during the pause window would leave a short `mic.wav`, so the recovered orphan would be desynchronized. A padding thread that tops the lagging channel up on a tick keeps both files frame-aligned at every instant, including at crash time. The tick loop mirrors `_silence_monitor_loop`, so it is a familiar shape, not a new pattern.

*How much to pad.* Wall-clock (`monotonic()` delta × `SAMPLE_RATE`) only corrects a known pause window. Counting frames actually enqueued per channel and levelling to the running maximum is self-correcting: it costs the same, needs no knowledge of *why* a channel is behind, and additionally repairs the desynchronization that dropped frames in `_enqueue` already cause today. Frame counting wins.

*Which direction.* Padding only the microphone up to the system-audio count would handle the pause but leave the reverse case untreated — and the reverse case already exists in production. When the ScreenCaptureKit stream stops unexpectedly (issue #22), `sys.wav` freezes while `mic.wav` keeps growing, and because the merge truncates to the shorter channel, every minute of microphone audio recorded after the failure is discarded even though it is sitting on disk:

```
SCK dies 10min into a 40min call

unidirectional          bidirectional
sys [==10min==]         sys [==10min==][##silence##]
mic [==10min==][=30min=] mic [==10min==][==30min===]
     ↓ min()                  ↓ max()
out [==10min==]         out [==10min==][==30min===]
    30min of the user's       user's own voice
    own voice discarded       preserved, sys channel silent
```

Levelling both channels to the running maximum is the same thread and the same counters, so the direction is free. It upgrades the outcome of an unexpected SCK stop from "truncated recording" to "complete recording with a silent channel", and it is the prerequisite for any future SCK reconnect: without it, a retry that takes three seconds would produce a short `sys.wav` and shift the rest of the recording, making the retry worse than the failure.

Padding is enqueued through the same per-channel queue as real audio, so ordering against real frames is handled by the queue rather than by locking against the writer. The system-audio path gains a padding route it did not have before; it must not interfere with `sck_capture`'s own chunk delivery when the stream is alive.

### Blink the existing icons instead of adding an asset

`_current_state_name()` (`menubar.py:389`) is a pure function over two booleans, rendered through a preloaded `_icons` dict. Adding an "attention" flag and a `rumps.Timer` that alternates which name resolves gives a blink with no new image assets and no change to the icon-loading path. The recording indicator is already a red circle, so blinking it reads as an alarm.

Both triggers — microphone silent, microphone paused for a switch — use the same blink. They are the same message to the user ("the microphone needs your attention"), and the menu text distinguishes them; a third icon state would add ambiguity rather than information.

### `on_silence_recovered` hook

The monitor already resets itself when audio returns (`recorder.py:179-181`, `warned = False`), but it only reports the *entry* into silence via `on_silence_warning()`. Without a matching recovery hook the blink would never stop once triggered, even after the microphone starts working again. The new hook defaults to a no-op, matching `_default_on_silence_warning` (`recorder.py:42`), so the CLI path is unchanged.

### Silence monitoring generalized to two channels

The monitor currently owns a single silence buffer fed only from `sys_on_chunk`. It needs to become per-channel (buffer, lock, `silent_since`/`warned` state, and hook payload identifying which channel). The system-audio warning text stays as-is — it points at Screen Recording permission — while the microphone warning points at the microphone device and the switch action.

## Risks / Trade-offs

- **`sd._terminate()` during an active recording kills capture.** → `list_input_devices()` is only reachable from the paused state; the pause/resume functions own the refresh call so no caller has to remember the ordering, and the constraint is commented at the definition.
- **A crash while the microphone is paused.** → Continuous padding keeps `mic.wav` aligned at every instant, so crash recovery produces a synchronized file rather than a shifted one.
- **The user abandons the selection dialog.** → Resume must reopen against the previous device (or the current default if the previous one is gone) rather than leaving the microphone paused indefinitely; the recording must never be left silently mic-less because a dialog was dismissed.
- **The chosen device rejects `SAMPLE_RATE` (16kHz) or mono.** → Opening the new stream can raise. Resume must treat this as a recoverable failure: report it, and fall back to a working device rather than aborting the recording.
- **Padding masks a real fault.** A microphone that dies and is never switched produces a long silent-but-aligned channel; a dead SCK stream now yields a full-length file with a silent channel instead of an obviously short one. → This is why the silence warning, the blink, and the existing unexpected-stop warning exist; alignment and detection are complementary, not substitutes. Padding must never suppress or replace a warning.
- **Padding races real audio on the system-audio channel.** If the SCK stream is alive but merely slow, the padder could inject silence that a late chunk then follows, inflating the channel. → Level against a running maximum with a tolerance rather than topping up on every tick, and treat the frame counters as the single source of truth for both padding and merge alignment.
- **The uncovered case remains uncovered.** Switching the OS default while the old device stays connected and audible triggers no warning at all. → Accepted and stated as a non-goal; the switch action is always available rather than warning-gated.
- **Blink is a shared signal for two causes.** → Menu text and notification carry the specific cause; the blink only claims "needs attention".

## Open Questions

- Should the blink also apply when the icon is in `recording_transcribing`, or does the combined state take precedence? Leaning toward blinking in both, alternating against `idle` either way.
- Blink interval: ~600ms is the starting assumption; worth a constant rather than a literal.
- Should a microphone-silence warning fire at all in the first seconds of a recording, or reuse an early-check grace period like `_start_early_buffer_check` does for system audio?
