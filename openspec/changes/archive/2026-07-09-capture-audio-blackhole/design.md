## Context

Meet Recorder is currently an empty `python-fire` CLI scaffold (see `CLAUDE.md`): `main.py` introspects `meet_recorder/handlers.py` for `handler_*` functions and exposes each as a CLI subcommand via `fire.Fire(...)`. The `@handler` decorator in `meet_recorder/tools.py` injects `verbose`/`dryrun` flags, sets up logging, and runs coroutine handlers via `asyncio.run(...)`. Side-effecting logic (HTTP, file I/O) lives in `meet_recorder/data.py`, separate from handlers.

This change introduces the first real feature: dual-source audio capture using BlackHole as a virtual audio driver (see `blackhole-python-guide.md` for the underlying technique — device discovery, `sounddevice` streams, threading). A menu bar UI is a known future direction (discussed but explicitly out of scope here), so the capture logic must not assume a CLI caller.

Implementation must follow DRY, KISS, 12-factor, and SOLID:
- **12-factor**: no hardcoded devices/paths/config in code — device selection is dynamic (system default mic, BlackHole by name lookup), output directory and any tunables come from environment/config following the existing `.env` + `load_dotenv()` pattern, not from constants buried in `recorder.py`.
- **SOLID / DRY**: `recorder.py` exposes a small set of pure-ish functions (start/stop/save, device switch, silence check) with no UI or CLI concerns, so the future menu bar can call the exact same functions the CLI handler calls today — no duplication, no rewrite.
- **KISS**: single stereo WAV output (no separate files, no real-time streaming/queueing) — the guide's chunked-streaming alternative (`queue.Queue`, live transcription) is explicitly not needed yet and is not built.

## Goals / Non-Goals

**Goals:**
- Record microphone and system audio simultaneously into one stereo WAV file (ch0 = mic, ch1 = system), at 44.1kHz.
- Automatically switch macOS audio output to the Multi-Output Device on record start, and restore the prior output on record stop — including on error/interruption.
- Warn (log) when the system-audio channel appears silent for a sustained period during recording.
- Expose this behavior through a UI-agnostic module (`recorder.py`) callable from a CLI test handler today and a menu bar app later.
- Provide a `handler_record(duration=...)` CLI command to manually exercise the whole flow end-to-end.

**Non-Goals:**
- Menu bar / tray UI (separate future proposal).
- Transcription, diarization, or any post-processing of the recording.
- Programmatically creating or detecting the Multi-Output Device — this remains a one-time manual Audio MIDI Setup step, documented in the README as onboarding.
- Real-time/streaming output (e.g. sending chunks to a transcription API) — out of scope until there's an actual consumer.
- Drift-correction beyond what macOS's own "Drift Correction" option (enabled manually in Audio MIDI Setup) provides.

## Decisions

**1. Single stereo WAV, channels not mixed.**
Per explicit product decision, `mic` and `system` audio are written as channel 0 and channel 1 of one file rather than summed (as the guide's example does) or written to two separate files. Rationale: guarantees the two sources stay sample-aligned (same file, same clock reference at write time) while still keeping them separable for any future per-speaker processing, without the bookkeeping overhead of two independent files.
- Alternative considered: two mono files (mic.wav, system.wav) — rejected because it reintroduces the exact drift/alignment risk the guide warns about, and adds no benefit at this stage since there's no consumer needing per-source files yet.

**2. Device discovery: system default mic, name-based lookup for BlackHole.**
Microphone: resolved via `sounddevice`'s default input device at record time (`sd.query_devices(kind='input')` / `sd.default.device`) rather than a hardcoded name — matches whatever the user has selected as system input right now (e.g. built-in mic, Bluetooth headset), no config needed.
System audio: still resolved by matching `"BlackHole"` in the device name (per the guide's `find_device` helper), since there is no "default" concept for it — it's a fixed virtual driver name once installed.

**3. Output device switching lives in `recorder.py`, using `SwitchAudioSource` via `subprocess`.**
`start_recording()` reads the current default output device name (`SwitchAudioSource -c`), stores it in memory for the duration of the recording, and switches to `"Multi-Output (BlackHole)"`. `stop_recording_and_save()` (and any error/cleanup path) restores the stored original device. This is a straightforward wrapper, not a new abstraction layer — keeps with KISS.
- Alternative considered: leave output switching manual (as the guide's minimal version does) — rejected per explicit product decision to automate it for v1, since it's core to a "click a button to record" UX.

**4. Silence detection: RMS threshold check on the BlackHole channel, sampled periodically during recording.**
While recording, periodically compute RMS on recent frames of the system-audio channel; if RMS stays under a small threshold for a sustained window (e.g. tens of seconds), log a warning once (not spammed every check). This is a diagnostic aid, not a hard failure — recording continues regardless. Threshold/window are constants for now (documented, not over-engineered into config, per KISS) unless they prove to need tuning.

**5. Config via environment, following existing project convention.**
Anything that varies by environment/user — output directory (default `~/MeetRecordings`), Multi-Output Device name, silence-detection threshold/window if they need overriding — is read via `os.environ`/`.env` (consistent with `main.py`'s existing `load_dotenv()` and `data.py`'s use of env-configured endpoints), with sane defaults in code so nothing is required to run out of the box. This keeps `recorder.py` free of hardcoded environment-specific values (12-factor).

**6. New dependencies are installed at their latest available versions.**
When adding `sounddevice`, `numpy`, `soundfile` (and `switchaudio-osx`/`blackhole-2ch` via Homebrew) to the project, use the latest released versions at install time (e.g. `poetry add sounddevice numpy soundfile` without pinning to an older version) rather than pinning to an arbitrary older version. Poetry's default `^` caret constraint still applies for future installs, consistent with how existing dependencies (`fire`, `requests`, etc.) are declared in `pyproject.toml`.

**7. `recorder.py` is UI-agnostic; `handler_record` is a thin adapter.**
`recorder.py` exposes plain functions (e.g. `start_recording()`, `stop_recording_and_save(path)`) with no knowledge of CLI or Fire. `handler_record(duration=30)` in `handlers.py` just calls `start_recording()`, sleeps/waits for `duration`, then calls `stop_recording_and_save()`, and logs the result — mirroring the existing thin-handler style (`handler_quotation` delegates to `data.get_quotation`). This is what makes the future menu bar integration additive rather than a rewrite (SOLID: `recorder.py` has one reason to change — recording behavior — independent of any caller).

## Risks / Trade-offs

- **[Risk]** User forgets/hasn't created the Multi-Output Device → system-audio channel silently records silence, since there's no error, just zeros. → **Mitigation**: RMS-based silence warning (decision 4), plus README onboarding documentation making the manual setup step explicit and checkable.
- **[Risk]** `SwitchAudioSource` binary not installed or Multi-Output Device not named exactly as expected → switching silently no-ops or errors. → **Mitigation**: check the binary/device exist before switching and log a clear actionable error rather than failing deep inside a recording; document the exact required device name in README.
- **[Risk]** Mic and BlackHole streams are independent clocks (two separate `sounddevice` `InputStream`s); over long recordings this can drift, since we're not implementing app-level resampling/correction. → **Mitigation**: rely on macOS "Drift Correction" (manual, one-time Audio MIDI Setup setting, documented in onboarding) — acceptable for expected meeting lengths; no code-level mitigation planned now (KISS — revisit only if it proves to be a real problem).
- **[Risk]** If the process crashes/is killed mid-recording, the output device is left switched to Multi-Output and never restored. → **Mitigation**: best-effort restore in a `finally`/exception-handling path in `stop_recording_and_save`/cleanup; full crash-safety (e.g. a lock file recording the prior device) is not attempted in this pass — acceptable given `handler_record` is a bounded, manual test entrypoint, not the always-on menu bar app.
- **[Trade-off]** No config file/CLI flags for sample rate, output dir override beyond env var, etc. — intentional per KISS; can be added when there's an actual need (e.g. when menu bar settings appear).

## Migration Plan

No migration — purely additive. New module (`recorder.py`), new handler, new dependencies. No existing behavior changes. Rollback is simply not calling the new handler / removing the dependency additions if needed.

## Open Questions

- Exact silence-detection threshold/window values will likely need real-world tuning once tested against actual meeting audio — treated as a tunable default, not blocking implementation.
- Whether `SwitchAudioSource` failures should abort the recording entirely or just warn and proceed without switching — leaning toward "warn and proceed" (recording is still useful even if only from mic) but left to implementation/testing to confirm.
