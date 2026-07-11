## Context

`meet_recorder` is a small python-fire CLI (~1200 LOC across 10 modules) with no test suite today. Most of the risk-carrying logic (WAV merging, orphan recovery, filename/title generation, config validation, the CLI handler-discovery/decorator machinery) is pure or file-based and cheap to test in isolation. The riskiest-to-test code (`sounddevice` streams, `SwitchAudioSource` subprocess calls, rumps/AppKit UI) is either hardware-dependent or UI-dependent and is deliberately excluded — unit tests there would be expensive to write and low-signal (they'd mostly test mocks calling mocks).

## Goals / Non-Goals

**Goals:**
- Stand up `pytest` as the test runner with a `tests/` tree mirroring `meet_recorder/`.
- Cover deterministic/file-based logic in `config`, `transcriber`, the pure subset of `recorder`, `tools`, `main`, and `handler_recover` with real assertions (not just "doesn't throw").
- Keep all subprocess calls (`ffmpeg`, `ffprobe`, `SwitchAudioSource`) and network calls (`httpx`, `OpenAI` client) mocked — no test requires binaries or network access to pass.
- Make `make test` the single entry point, matching the existing `make lint`/`make setup` pattern.

**Non-Goals:**
- No coverage quality gate (no minimum %, no CI wiring — this repo has no CI configured).
- No tests for `menubar.py` (rumps/AppKit) or the stream lifecycle in `recorder.py` (`start_recording`/`stop_recording_and_save`), both of which require real audio hardware or a live macOS UI session to exercise meaningfully.
- No tests for `data.py` (`get_quotation`/`read_csv`) — unrelated to the current focus area and low value (thin wrappers with no branching logic worth asserting on).
- No refactor of production code to make it "more testable" — the existing seams (module-level functions, env-var-read-at-call-time config) are already sufficient.

## Decisions

- **pytest over unittest**: fixtures (`tmp_path`, `monkeypatch`) map directly onto this codebase's needs (temp WAV files, env vars read via `os.environ.get` at call time, `CONFIG_PATH` override). Poetry dev group gets `pytest` (+ `pytest-cov` for optional local `--cov` runs, not wired to a gate).
- **Real WAV files over mocked `soundfile`**: for `_merge_to_stereo` and orphan validation (`_is_valid_orphan`), tests write small synthetic WAVs (a few dozen frames, mono, 44100Hz PCM_16) to `tmp_path` via `soundfile.SoundFile` directly, then assert on the actual merged output's shape/channel content. This exercises the real merge logic (including the truncate-to-shorter-stream behavior at the tail) rather than mocking the audio library, which would leave the actual bug surface (frame counting, channel interleaving) untested.
- **Mock all subprocess/network boundaries**: `subprocess.run` is mocked in `transcriber` tests (`ffmpeg`/`ffprobe`) per the user's explicit choice — trades a small amount of realism for speed/portability (no binary dependency in CI-less local runs). `_chat_completion` is mocked directly (rather than mocking `httpx`/`OpenAI` internals) so `_generate_title`'s retry-on-length loop can be tested by controlling the mock's return values across calls.
- **`input()` mocked via `monkeypatch.setattr('builtins.input', ...)`** in `handler_recover` tests, with `recorder`/`transcriber` module functions patched via `monkeypatch.setattr` on the `meet_recorder.handlers` module's imported names, to cover the p/i/a branches without touching real recordings.
- **No `conftest.py` fixtures shared across all test files initially** — each test module is self-contained (WAV-building helper duplicated where needed, or a small `tests/helpers.py` if duplication becomes annoying across `recorder` tests specifically). Avoids premature shared-fixture abstraction for a first test suite.
- **Global `_state` dict in `recorder.py` is untouched by these tests** — since `start_recording`/`stop_recording_and_save` are out of scope, no test needs to reset or interact with module-level state.

## Risks / Trade-offs

- [Mocking `subprocess.run` for ffmpeg/ffprobe means a real ffmpeg regression (e.g. a flag no longer supported) won't be caught] → Accepted trade-off per explicit user decision; this is a known gap, not an oversight.
- [Synthetic WAV files in tests are much smaller/simpler than real recordings (mono vs stereo source assumptions, no silence/clipping edge cases)] → Mitigate by testing the specific edge cases that matter: unequal-length streams, zero-frame files, corrupted/unreadable files — not by trying to simulate realistic audio content.
- [No shared `conftest.py` initially may lead to duplicated WAV-building helpers across `recorder` tests] → Acceptable for a first pass; a shared helper can be extracted later if duplication actually causes pain (YAGNI).

## Open Questions

None outstanding — scope, mocking strategy, and coverage philosophy were confirmed with the user during exploration.
