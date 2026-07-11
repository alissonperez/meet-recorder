## Why

The project has no test suite. The pure/deterministic logic that carries the most risk today — WAV merging and crash-recovery orphan handling, transcript/summary filename and title generation, config loading/validation, and the CLI's dynamic handler wiring — is exercised only by manual runs. A regression in any of these (e.g. `_merge_to_stereo` truncating a channel, `_is_valid_orphan` mis-classifying a corrupt file, `load_config` silently accepting a malformed YAML) would only surface after a real recording is lost or a transcription fails.

## What Changes

- Add `pytest` (and `pytest-cov` for local/optional coverage reporting, no gate) to the Poetry dev group.
- Add a `tests/` directory mirroring `meet_recorder/` module layout, plus a `make test` target running `poetry run pytest`.
- Add unit tests for the deterministic/pure logic in:
  - `meet_recorder/config.py` — `load_config` (missing file, invalid YAML, missing required fields, defaults, `~` expansion).
  - `meet_recorder/transcriber.py` — filename/timestamp helpers, markdown builders, and `_generate_title`'s retry/truncate loop (with `_chat_completion` mocked); `_split_into_chunks`/`_transcribe_audio`/`_preprocess_audio` with `subprocess.run` mocked (no real `ffmpeg`/`ffprobe` invocations).
  - `meet_recorder/recorder.py` — the pure/file-based subset only: `_rms`, `_merge_to_stereo` (using small real WAV files written via `soundfile` in a tmp dir), `list_orphan_candidates`, `_is_valid_orphan`, `discard_invalid_orphans`, `delete_orphan`, `merge_and_cleanup`. Stream lifecycle (`start_recording`/`stop_recording_and_save`, which depend on `sounddevice` + `SwitchAudioSource`) is explicitly out of scope.
  - `meet_recorder/tools.py` — the `@handler` decorator: `verbose`/`dryrun` injection and stripping via positional and keyword args, `dryrun` warning log, sync and async handler dispatch.
  - `main.py` — `handler_` prefix discovery and name-stripping used to build the Fire command dict.
  - `meet_recorder/handlers.py` — `handler_recover` only, with `recorder`/`transcriber` mocked and `input()` mocked to cover the process/ignore/delete (p/i/a) branches and the "nothing to recover" short-circuit.
- Explicitly out of scope: `meet_recorder/menubar.py` (rumps/AppKit UI), `meet_recorder/data.py` (unrelated to current focus, low value), and any test relying on real audio hardware, `ffmpeg`/`ffprobe` binaries, or network calls.
- No production code behavior changes; this is test-only, dev-dependency-only.

## Capabilities

### New Capabilities
- `test-suite`: Establishes the project's unit test suite — infrastructure (pytest, `make test`) and the specific behavioral guarantees verified for `config`, `transcriber`, `recorder` (pure subset), `tools`, `main`, and `handler_recover`.

### Modified Capabilities
(none — no product-facing requirements change; this only adds test coverage for existing behavior)

## Impact

- `pyproject.toml` / `poetry.lock`: new dev dependency (`pytest`, `pytest-cov`).
- `Makefile`: new `test` target.
- New `tests/` directory tree, no existing source files modified.
- No runtime/production behavior change; CI or local dev workflow gains a `make test` step (not wired into any existing CI since none exists in this repo currently).
