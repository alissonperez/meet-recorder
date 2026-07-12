# Design: Migrate system-audio capture to ScreenCaptureKit

## Context

Today `recorder.py` captures two mono sources with `sounddevice` (PortAudio): the default microphone and the BlackHole 2ch virtual device. Capturing system audio through BlackHole requires switching the macOS output device to a Multi-Output Device at record start (via the external `SwitchAudioSource` binary) and restoring it at stop. While the Multi-Output Device is active, system volume cannot be adjusted. Each source is enqueued to a bounded queue, drained by a writer thread into a temp mono WAV (`.in-progress/<ts>/{mic,sys}.wav`), and merged into a stereo WAV at stop. A silence monitor watches the system channel's RMS to detect misrouted output.

ScreenCaptureKit (macOS 13+) can deliver system audio directly to the process without touching output routing. The integration approach is documented in `screencapture-guide.md` (pyobjc, delegate metadata gotcha, run-loop requirements, Float32 format).

Two entry points consume the recorder: the rumps menubar app (primary, runs the `NSApplication` main loop, launched via LaunchAgent `com.alisson.meet-recorder.plist`) and the CLI `record` handler (blocking sleep, no run loop).

## Goals / Non-Goals

**Goals:**

- Replace the system-audio source (BlackHole `InputStream`) with an `SCStream`, keeping the writer-queue/incremental-disk/merge pipeline byte-for-byte compatible (mono float32 chunks in, PCM_16 WAV out).
- Remove output-device switching and the `SwitchAudioSource`/BlackHole dependencies entirely.
- Move both channels to 16kHz.
- Keep both entry points (menubar and CLI `record`) working.

**Non-Goals:**

- Migrating microphone capture to ScreenCaptureKit (`captureMicrophone`, macOS 15+). Follow-up candidate once SCK bridging is proven in production.
- Core Audio Process Taps (macOS 14.2+). Reevaluate only if the app is ever distributed to others (see guide §10).
- App-specific capture filters (e.g. record only the browser). System-wide capture, same as today.
- Packaging as a `.app` bundle / fixing a stable `CFBundleIdentifier`.

## Decisions

### D1: SCK only for the system channel; mic stays on sounddevice

One stream swap with an identical contract (mono float32 chunks into the existing queue) is testable in isolation and keeps risk low. Unifying both channels into a single `SCStream` would eliminate the two-clock drift between mic and sys, but that drift exists today with two PortAudio streams and has never been a problem; the extra pyobjc bridging surface (`SCStreamOutputTypeMicrophone`) is less battle-tested. Rejected for now.

### D2: 16kHz for both channels

SCK guarantees only 8/16/24/48kHz — 44.1kHz is not in the supported set, so the current rate cannot be kept. 16kHz is chosen over 24/48kHz because the recordings exist to feed Whisper-family transcription (which resamples to 16kHz internally, so higher rates add zero transcription quality), and it cuts disk usage ~2.8x versus today. Trade-off: playback timbre is slightly dull (8kHz bandwidth) and any music-rich recording is degraded — acceptable for meeting audio. The mic channel moves to 16kHz too (CoreAudio resamples from hardware rate transparently) so `_merge_to_stereo` keeps its single-`SAMPLE_RATE` assumption.

### D3: Buffer conversion is a pure function

**Confirmed by spike** (2026-07-12, pyobjc 12.2.1 / macOS 26): despite `AudioStreamBasicDescription.mFormatFlags` reporting `kAudioFormatFlagIsNonInterleaved`, the `CMBlockBuffer` returned by `CMSampleBufferGetDataBuffer` is empirically interleaved — verified via `floatCount / CMSampleBufferGetNumSamples() == channelCount` exactly, across multiple buffers with real audio. Trust the empirical layout over the ASBD flag.

Extraction uses different APIs than the guide's example (see Risks: `screencapture-guide.md` had 3 bridging mismatches on this pyobjc version):
- `CMAudioFormatDescriptionGetStreamBasicDescription(format_desc)` returns a **raw tuple**, not an object with named attributes: `(sampleRate, formatID, formatFlags, bytesPerPacket, framesPerPacket, bytesPerFrame, channelsPerFrame, bitsPerChannel, reserved)`. Index by position (`asbd[0]`, `asbd[6]`, ...), not `.mSampleRate`.
- `CMBlockBufferCopyDataBytes(block_buffer, offset, length, None)` returns `(status, bytes)`; `CMBlockBufferRef` has no `getBytesWithLengthAtOffset_length_` method on this bridge.

Conversion to the pipeline's shape — `np.frombuffer(raw_bytes, dtype=np.float32).reshape(-1, channels)` → mean across axis 1 → `(n, 1)` mono — lives in a standalone pure function so it is unit-testable without any framework mock. The callback itself only does: convert → `_enqueue` → `_append_to_silence_buffer`, mirroring today's `sys_callback`.

Configure the stream with `channelCount = 2` and downmix by averaging; log the `AudioStreamBasicDescription` from the first buffer (guide §7, corrected APIs above) at debug level to catch configuration drift — spike confirmed `sampleRate=16000.0, channelsPerFrame=2, bitsPerChannel=32` matches configuration exactly, no silent resampling by the OS.

### D4: no manual pyobjc delegate metadata registration; never decorate the callback with `@objc.python_method`

**Superseded by spike finding**, reversing the guide's guidance for this pyobjc version. The guide's §4 workaround (`objc.registerMetaDataForSelector` for `stream:didOutputSampleBuffer:ofType:`, combined with `@objc.python_method` on the callback) was tested exactly as documented and produced the documented symptom: capture starts with no error, but zero buffers ever arrive (audio *and* video, confirmed by also wiring up a screen output).

Root cause isolated by bisection: `@objc.python_method` marks a method as **callable only from Python, not from the Objective-C runtime** — so `SCStream` literally cannot invoke it as the delegate callback, regardless of any metadata registration. Removing the decorator alone fixed delivery (389 audio buffers / 8 video frames in an 8s test). Removing the manual `registerMetaDataForSelector` call *in addition* made no difference — pyobjc 12.2.1 already has correct built-in bridging metadata for this selector; the manual registration is redundant but harmless as long as the decorator is gone.

**Action**: do not port the guide's `@objc.python_method` usage on `stream_didOutputSampleBuffer_ofType_`/`stream_didStopWithError_` into `sck_capture.py`. Skip the manual metadata registration entirely (dead code for this pyobjc version) unless a future pyobjc downgrade/regression brings back the original symptom.

### D5: Explicit dispatch queue for the stream output

Pass a real `dispatch_queue_t` to `addStreamOutput_type_sampleHandlerQueue_error_` instead of `None` — `None` is rejected on some macOS versions (guide §8). One dedicated serial queue for audio buffers.

### D6: Synchronous start/stop wrappers over SCK's async API

`start_recording()`/`stop_recording_and_save()` are synchronous today and callers (menubar callbacks, CLI handler, tests) depend on that: errors must raise so `menubar.on_start` can show its alert, and `stop` must return the merged path. SCK's content enumeration, start, and stop are all completion-handler async. Bridge with `threading.Event` + captured result/error: fire the async call, wait on the event with a timeout (~10s), raise `RuntimeError` on error or timeout. Callbacks arrive on GCD threads, so this does not deadlock the main thread — but see D7 for the CLI caveat.

Alternative rejected: making the recorder API async — it would ripple through menubar, handlers, and tests for no user-visible benefit.

### D7: Run loop strategy per entry point

**Revised after implementation** — the originally planned `NSRunLoop` pumping for the CLI turned out to be unnecessary, verified empirically rather than assumed:

- **Menubar**: rumps runs the `NSApplication` main loop; GCD completion handlers and the dispatch-queue output callbacks are delivered independently of it. No change needed.
- **CLI `record`**: no change needed either. `sck_capture.start`/`stop` use an explicit dispatch queue (D5) for buffer delivery and a `threading.Event`-based sync bridge (D6) for the completion handlers, both of which run on GCD's own thread pool — neither depends on a `CFRunLoop`/`NSRunLoop` being pumped by the calling thread. This was verified directly: the real `recorder.start_recording()` → `time.sleep(N)` → `recorder.stop_recording_and_save()` sequence (i.e. `handler_record`'s existing implementation, unmodified) produced a valid 16kHz stereo WAV with real audio on both channels, with zero run-loop code anywhere in the process. `time.sleep()` is already Ctrl-C-interruptible and `handler_record`'s existing `try/finally` already saves on interrupt (locked in by a regression test). Net result: `handler_record` needed no code change at all.

### D8: Silence monitor kept, reworded

The Multi-Output misrouting failure mode disappears, but the monitor remains the safety net for silent failure modes confirmed by the spike: Screen Recording permission missing/revoked under launchd surfaces as an explicit `SCStreamErrorDomain Code=-3801` at content-listing time (loud, easy to catch) — but any regression of the D4 callback-wiring bug (e.g. an accidental `@objc.python_method` reintroduced in a refactor) would silently produce zero buffers with no error at all. Log/notification text changes from "check Multi-Output routing" to "check Screen Recording permission". `menubar.on_silence_warning` text updated accordingly.

### D9: Minimal discarded video stream

SCK requires a configured video output. Use the guide's standard trick: 2x2 pixels, 1fps minimum frame interval, and never add a stream output for the `.screen` type, so video frames are dropped at the source.

### D11: `SYS_AUDIO_CHANNELS = 1` (native mono) — `channelCount=2` produces corrupted audio

**Found post-implementation, by ear, from real usage** (2026-07-12): recordings made with the shipped `channels=2` config sounded "robotic," with reports of "slow" pacing and "thin" voices on the system-audio channel specifically. Root-caused through a structured elimination:

1. Objective sample-to-sample discontinuity counts in real recordings were high, but this metric alone was a false lead — a true-silence capture (audio genuinely paused, not just muted) was perfectly clean (RMS 0.0, zero discontinuities), and a TTS-voice capture had thousands of "large jumps" that turned out to just be normal high-frequency speech content, not defects. Don't trust adjacent-sample-delta thresholds as a proxy for audio quality without a human listening to confirm — dense legitimate high-frequency content produces the same signature as glitches.
2. The only reliable signal was the user listening and comparing against a clean reference (`say -o` output never touched by SCK).
3. Bisected via controlled capture variants, each confirmed by ear: 16kHz stereo → robotic. 48kHz stereo → still robotic (rules out downsampling-quality as the cause). 48kHz mono (`channelCount=1`) → clean. 16kHz mono → clean.
4. Captured raw per-channel (pre-downmix) stereo data directly: the corruption was already present independently in the raw left and right channels before any processing of ours (our own `float32_stereo_to_mono` averaging was not the cause — confirmed innocent both by this raw-channel evidence and by the channels=1 case being a no-op pass-through of the same function).

Conclusion: `SCStreamConfiguration.setChannelCount_(2)` for audio-only capture is broken on this pyobjc/macOS combination — it's an upstream delivery defect, not something fixable in our downmix. Since the pipeline only ever needed mono for the sys channel anyway (D3's downmix target), the fix has no downside: request `channelCount=1` directly from ScreenCaptureKit. `sck_capture.start`'s default changed from `channels=2` to `channels=1` to make the safe value the path of least resistance for any future caller.

**Process note**: diagnosing this required starting a second, competing `SCStream` while the production LaunchAgent's own stream was potentially active, which produced `SCStreamErrorDomain -3805` ("connection interruption") — confirming ScreenCaptureKit (at least as configured here, both processes requesting display-audio capture) does not support two independent capturing consumers cleanly. Isolated diagnostics must run with any other SCK consumer (including this app's own LaunchAgent) fully stopped.

### D10: New module `meet_recorder/sck_capture.py`

The SCK plumbing (delegate class, dispatch queue, filter/config/stream assembly, sync bridge — no manual metadata registration, see D4) lives in a new module exposing a small interface: `start(on_chunk) -> handle`, `stop(handle)`. `recorder.py` keeps orchestration (queues, writers, silence monitor, merge) and stays importable/testable on any platform by mocking that interface — today's tests mock `sounddevice` the same way.

## Risks / Trade-offs

- **[TCC under launchd — CONFIRMED, workable]** Spike (2026-07-12) verified the hypothesis directly: an interactive-shell process (iTerm2-attributed, permission already granted) got zero buffers with no error initially in one run — resolved once a *separate* disposable LaunchAgent (`com.alisson.sck-spike`, isolated from the real `com.alisson.meet-recorder` production agent, which was never touched) was bootstrapped. That launchd-spawned run failed first with an explicit, loud error — `SCStreamErrorDomain Code=-3801` ("O usuário recusou os TCCs") — then macOS presented a **separate permission prompt attributed to the `python3.13` binary itself**, distinct from the iTerm2 grant. After the user granted it, a `launchctl kickstart` re-run succeeded cleanly (402 audio buffers, valid 16kHz WAV). Conclusion: launchd attribution resolves to the invoking executable (not the terminal emulator), the failure mode is loud (explicit error code, not silent), and granting it once is a normal one-time System Settings interaction — no shim or stable-identifier workaround needed. Remaining unknown: whether the grant survives a Poetry venv rebuild (the production venv path includes a content hash, e.g. `meet-recorder-RBBEOZkh-py3.13`, which can change) — validate in task 6 (manual end-to-end) and document a re-grant step in the README regardless.
- **[Silent callback failure]** A wiring regression (see D4) manifests as "no buffers" with **no error at all** — unlike the TCC case above, which errors loudly. → D8 (silence monitor) is the only safety net for this specific failure mode, plus a startup check: if zero system-audio buffers arrive within the first N seconds, log a warning immediately rather than waiting for the 30s silence window.
- **[Format drift]** macOS may adjust the delivered format regardless of configuration. → D3's debug-log of the first buffer's ASBD; conversion function derives channel count from configuration, not hardcoded literals.
- **[Recording starts slower]** Content enumeration + stream start is async and takes noticeably longer than opening a PortAudio stream (typically well under a second, but not instant). → Accept; the D6 timeout converts a hang into a clear error. The first seconds of a meeting were already at risk today from manual start latency.
- **[Old orphans at 44.1kHz]** Orphan recovery merges temp files using the module-level `SAMPLE_RATE`; a pre-migration orphan recovered post-migration would be written with the wrong rate header (audio plays ~2.7x slow). → Read the actual samplerate from the temp WAV headers in `merge_and_cleanup` instead of trusting the constant. Small, removes the coupling permanently.
- **[16kHz is lossy for non-speech]** Accepted per D2; revisit to 24kHz only if listening quality ever becomes a complaint.

## Migration Plan

1. ~~Spike: validate SCK capture + TCC under both entry paths (Terminal, launchd) with the guide's standalone script. Gate: proceed only if permission attribution is workable.~~ **Done 2026-07-12** — see Risks (TCC under launchd) and D3/D4 for findings; gate passed.
2. Implement behind the existing interface (new `sck_capture.py`, `recorder.py` swap, 16kHz, device-switching removal).
3. Update tests, README, `.env.example`/config docs; mark `MULTI_OUTPUT_DEVICE_NAME` obsolete.
4. Manual end-to-end: CLI `record --duration=30` with volume changes mid-recording; menubar start/stop with transcription; kill -9 mid-recording and verify orphan recovery (including one pre-migration 44.1kHz orphan).
5. Rollback: single revert commit restores the BlackHole path; BlackHole driver stays installed on the machine until the migration has survived a few real meetings.

## Open Questions

- ~~Spike outcome: how is Screen Recording permission attributed under the LaunchAgent?~~ **Resolved**: attributed to the invoking executable (e.g. the venv's `python3.13`), distinct from and in addition to any interactive-shell grant; failure is a loud, explicit error, not silent. See Risks.
- Does the launchd TCC grant survive a Poetry venv rebuild (path/hash change)? Untested — the spike used a throwaway venv. Validate during task 6 manual end-to-end against the real `meet-recorder-<hash>-py3.13` venv; if it doesn't survive, document the re-grant step in the README (task 5.1).
- Should the recorder exclude any applications from capture (e.g. to avoid recording notification dings)? Default: no filter, system-wide, same behavior as BlackHole today.
