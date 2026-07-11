## 1. Test infrastructure

- [x] 1.1 Add `pytest` and `pytest-cov` to the Poetry dev group in `pyproject.toml`, run `poetry lock` / `poetry install`
- [x] 1.2 Create `tests/` directory with `tests/__init__.py` (if needed) mirroring `meet_recorder/` module layout
- [x] 1.3 Add a `test` target to `Makefile` running `poetry run pytest`
- [x] 1.4 Verify `make test` runs (even with zero tests) before adding test files

## 2. Config loading tests (`tests/test_config.py`)

- [x] 2.1 Test `load_config` raises `ConfigError` when the file path does not exist
- [x] 2.2 Test `load_config` raises `ConfigError` on malformed YAML
- [x] 2.3 Test `load_config` raises `ConfigError` listing missing required fields
- [x] 2.4 Test `load_config` applies `DEFAULT_CHUNK_DURATION_SECONDS` and `DEFAULT_BASE_URL` when omitted
- [x] 2.5 Test `load_config` expands `~` in `transcript_dir`/`summary_dir`

## 3. Transcriber tests (`tests/test_transcriber.py`)

- [x] 3.1 Test `_resolve_timestamp` parses a filename matching `FILENAME_TIMESTAMP_FORMAT`
- [x] 3.2 Test `_resolve_timestamp` falls back to file mtime for a non-matching filename
- [x] 3.3 Test `_build_base_filename` embeds timestamp, slugified title, and optional suffix
- [x] 3.4 Test `_transcript_markdown`/`_summary_markdown` produce expected frontmatter + content
- [x] 3.5 Test `_generate_title` returns immediately when mocked `_chat_completion` returns a title within `TITLE_MAX_LENGTH`
- [x] 3.6 Test `_generate_title` retries up to `TITLE_MAX_ATTEMPTS` then truncates when every attempt is too long
- [x] 3.7 Test `_split_into_chunks` returns the original path unchanged when duration is under `chunk_duration` (mock `subprocess.run` for `ffprobe` duration)
- [x] 3.8 Test `_split_into_chunks` invokes `ffmpeg` once per chunk and returns one path per chunk when duration exceeds `chunk_duration`

## 4. Recorder pure-logic tests (`tests/test_recorder.py`)

- [x] 4.1 Add a small helper to write synthetic mono WAV files (via `soundfile.SoundFile`) into `tmp_path`
- [x] 4.2 Test `_rms` returns 0.0 for an empty array and a correct RMS value for known sample data
- [x] 4.3 Test `_merge_to_stereo` produces a stereo WAV with mic samples on channel 0 and sys samples on channel 1 for equal-length inputs
- [x] 4.4 Test `_merge_to_stereo` truncates output length to the shorter of the two input streams
- [x] 4.5 Test `list_orphan_candidates` returns sorted subdirectories of `.in-progress/` and `[]` when the directory doesn't exist
- [x] 4.6 Test `_is_valid_orphan` returns `True` for non-empty, readable `mic.wav`/`sys.wav`
- [x] 4.7 Test `_is_valid_orphan` returns `False` for a zero-frame WAV
- [x] 4.8 Test `_is_valid_orphan` returns `False` for an unreadable/corrupted file
- [x] 4.9 Test `discard_invalid_orphans` deletes invalid orphan directories from disk and returns only valid ones
- [x] 4.10 Test `delete_orphan` removes the given directory
- [x] 4.11 Test `merge_and_cleanup` returns a merged output path and removes the temp directory

## 5. Handler decorator tests (`tests/test_tools.py`)

- [x] 5.1 Test `verbose`/`dryrun` passed as keywords are stripped from `kwargs` before the wrapped function is called
- [x] 5.2 Test `verbose`/`dryrun` passed positionally do not leak into the wrapped function's positional args
- [x] 5.3 Test `dryrun=True` logs a warning
- [x] 5.4 Test a decorated async function is run via `asyncio.run` and its return value is passed through
- [x] 5.5 Test a wrapped function that already declares `verbose`/`dryrun` in its own signature is not double-injected

## 6. CLI discovery tests (`tests/test_main.py`)

- [x] 6.1 Test the handler-discovery logic (imported or replicated from `main.py`) maps each `handler_*` function in `meet_recorder.handlers` to a `handler_`-stripped key
- [x] 6.2 Test non-`handler_`-prefixed module members (e.g. `logger`) are excluded from the resulting mapping

## 7. Recovery handler tests (`tests/test_handlers.py`)

- [x] 7.1 Test `handler_recover` logs "nothing to recover" and does not call `input()` when no valid orphans are found
- [x] 7.2 Test `handler_recover` calls `merge_and_cleanup` and `transcribe` for each orphan when mocked `input()` returns `'p'`
- [x] 7.3 Test `handler_recover` calls `delete_orphan` for each orphan and skips transcription when mocked `input()` returns `'a'`
- [x] 7.4 Test `handler_recover` leaves orphans untouched when mocked `input()` returns `'i'` (or any other value)

## 8. Wrap-up

- [x] 8.1 Run `make test` and `make lint` and confirm both pass cleanly
- [x] 8.2 Review test file naming/structure for consistency with `meet_recorder/` module layout
