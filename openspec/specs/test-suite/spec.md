# test-suite Specification

## Purpose
TBD - created by archiving change add-test-coverage. Update Purpose after archive.

## Requirements

### Requirement: Test runner infrastructure
The project SHALL provide a `pytest`-based test suite runnable via `make test`, with `pytest` (and `pytest-cov`) declared as Poetry dev dependencies, requiring no network access, audio hardware, or `ffmpeg`/`ffprobe`/`SwitchAudioSource` binaries to pass.

#### Scenario: Running the full suite
- **WHEN** a developer runs `make test` in a machine with only the Poetry dev dependencies installed (no ffmpeg, no audio hardware, no network)
- **THEN** the full test suite runs to completion and passes

### Requirement: Config loading is verified
The test suite SHALL verify `meet_recorder.config.load_config` behavior for a missing config file, invalid YAML, missing required fields, applied defaults (`chunk_duration`, `base_url`), and `~` expansion in `transcript_dir`/`summary_dir`.

#### Scenario: Missing config file
- **WHEN** `load_config` is called with a path that does not exist
- **THEN** it raises `ConfigError` referencing the missing path

#### Scenario: Invalid YAML content
- **WHEN** `load_config` is called on a file containing malformed YAML
- **THEN** it raises `ConfigError` referencing the parse failure

#### Scenario: Missing required fields
- **WHEN** `load_config` is called on a valid YAML mapping that omits one or more of `REQUIRED_FIELDS`
- **THEN** it raises `ConfigError` naming the missing fields

#### Scenario: Defaults applied
- **WHEN** `load_config` is called on a config that omits `chunk_duration` and `base_url`
- **THEN** the resulting `Config` uses `DEFAULT_CHUNK_DURATION_SECONDS` and `DEFAULT_BASE_URL`

#### Scenario: Home directory expansion
- **WHEN** `load_config` is called on a config where `transcript_dir`/`summary_dir` contain a `~`
- **THEN** the resulting `Config` stores the expanded absolute path

### Requirement: Transcript/summary filename and title generation is verified
The test suite SHALL verify `meet_recorder.transcriber`'s pure filename/timestamp/markdown helpers and `_generate_title`'s retry-until-short-enough-then-truncate behavior, with `_chat_completion` and `subprocess.run` mocked so no network or `ffmpeg`/`ffprobe` call occurs.

#### Scenario: Timestamp parsed from filename
- **WHEN** `_resolve_timestamp` is called on a path whose stem matches `FILENAME_TIMESTAMP_FORMAT`
- **THEN** it returns the parsed timestamp rather than falling back to file mtime

#### Scenario: Timestamp falls back to mtime
- **WHEN** `_resolve_timestamp` is called on a path whose stem does not match `FILENAME_TIMESTAMP_FORMAT`
- **THEN** it returns a timestamp derived from the file's modification time

#### Scenario: Base filename includes slugified title and optional suffix
- **WHEN** `_build_base_filename` is called with a timestamp, a title, and an optional suffix (e.g. `RESUMO`)
- **THEN** the returned filename embeds the ISO-ish timestamp, the slugified title, and the suffix when provided

#### Scenario: Title within length limit is accepted immediately
- **WHEN** `_generate_title` is called and the mocked `_chat_completion` returns a title at or under `TITLE_MAX_LENGTH` on the first attempt
- **THEN** that title is returned without further retries

#### Scenario: Title retried then truncated after max attempts
- **WHEN** `_generate_title` is called and the mocked `_chat_completion` returns a title over `TITLE_MAX_LENGTH` on every attempt up to `TITLE_MAX_ATTEMPTS`
- **THEN** `_chat_completion` is called exactly `TITLE_MAX_ATTEMPTS` times and the final returned title is truncated to `TITLE_MAX_LENGTH` characters

#### Scenario: Audio split into chunks when duration exceeds limit
- **WHEN** `_split_into_chunks` is called on audio whose mocked duration exceeds `chunk_duration`
- **THEN** it invokes `ffmpeg` (via mocked `subprocess.run`) once per chunk and returns one chunk path per segment

#### Scenario: Audio left as a single chunk when under the limit
- **WHEN** `_split_into_chunks` is called on audio whose mocked duration is at or under `chunk_duration`
- **THEN** it returns the original path unchanged without invoking `ffmpeg` to split

### Requirement: WAV merge and orphan recovery logic is verified
The test suite SHALL verify `meet_recorder.recorder`'s pure/file-based logic — `_rms`, `_merge_to_stereo`, `list_orphan_candidates`, `_is_valid_orphan`, `discard_invalid_orphans`, `delete_orphan`, and `merge_and_cleanup` — using real synthetic WAV files written to a temp directory, without exercising `start_recording`/`stop_recording_and_save` or any `sounddevice`/`SwitchAudioSource` call.

#### Scenario: Merge produces interleaved stereo output
- **WHEN** `_merge_to_stereo` is called with a mic mono WAV and a sys mono WAV of equal length
- **THEN** the output WAV is stereo with the mic samples on channel 0 and the sys samples on channel 1

#### Scenario: Merge truncates to the shorter stream
- **WHEN** `_merge_to_stereo` is called with mic and sys WAVs of different lengths
- **THEN** the output WAV's length equals the shorter of the two input streams

#### Scenario: Valid orphan passes validation
- **WHEN** `_is_valid_orphan` is called on a directory containing non-empty, readable `mic.wav` and `sys.wav`
- **THEN** it returns `True`

#### Scenario: Empty-frame orphan fails validation
- **WHEN** `_is_valid_orphan` is called on a directory where `mic.wav` or `sys.wav` contains zero frames
- **THEN** it returns `False`

#### Scenario: Corrupted orphan fails validation
- **WHEN** `_is_valid_orphan` is called on a directory where `mic.wav` or `sys.wav` cannot be opened as audio
- **THEN** it returns `False`

#### Scenario: Invalid orphans are discarded from disk
- **WHEN** `discard_invalid_orphans` is called with a mix of valid and invalid orphan candidate directories
- **THEN** invalid orphan directories are deleted from disk and only valid orphans are returned

#### Scenario: Merge and cleanup removes the temp directory
- **WHEN** `merge_and_cleanup` is called with a mic path, sys path, and their containing temp directory
- **THEN** it returns the path to a merged output WAV and the temp directory no longer exists on disk

### Requirement: Handler decorator argument handling is verified
The test suite SHALL verify `meet_recorder.tools.handler`'s injection and stripping of `verbose`/`dryrun` across positional and keyword invocation styles, its `dryrun` warning log, and its dispatch of both sync and async wrapped functions.

#### Scenario: Verbose and dryrun passed as keywords are stripped before calling the wrapped function
- **WHEN** a decorated handler is called with `verbose=True, dryrun=True` as keyword arguments
- **THEN** the wrapped function receives neither `verbose` nor `dryrun` in its `kwargs`

#### Scenario: Verbose and dryrun passed positionally are stripped before calling the wrapped function
- **WHEN** a decorated handler is called with `verbose`/`dryrun` values passed positionally (matching the injected signature order)
- **THEN** the wrapped function is called without those positional values leaking into its own arguments

#### Scenario: Dryrun logs a warning
- **WHEN** a decorated handler is called with `dryrun=True`
- **THEN** a warning is logged indicating dryrun mode

#### Scenario: Async wrapped function is awaited via asyncio.run
- **WHEN** the decorated function is a coroutine function
- **THEN** calling the wrapper runs it to completion via `asyncio.run` and returns its result

#### Scenario: Handler that already declares verbose/dryrun is not double-injected
- **WHEN** the wrapped function's original signature already includes a `verbose` or `dryrun` parameter
- **THEN** the decorator does not add a duplicate parameter or strip a value the function itself declared

### Requirement: CLI command discovery is verified
The test suite SHALL verify that `main.py`'s handler-discovery logic collects every module-level `handler_`-prefixed function from `meet_recorder.handlers` into a `{name: func}` mapping with the `handler_` prefix stripped, and excludes non-`handler_`-prefixed module members.

#### Scenario: Handler functions are discovered and renamed
- **WHEN** the discovery logic runs against `meet_recorder.handlers`
- **THEN** the resulting mapping contains an entry for each `handler_*` function keyed by its name with the `handler_` prefix removed

#### Scenario: Non-handler module members are excluded
- **WHEN** the discovery logic runs against `meet_recorder.handlers`
- **THEN** module-level names that are not prefixed with `handler_` (e.g. `logger`, imported modules) do not appear in the resulting mapping

### Requirement: Recovery CLI handler branching is verified
The test suite SHALL verify `handler_recover`'s three user-choice branches (process/ignore/delete) and its no-op path when no valid orphans are found, with `recorder`, `transcriber`, and `input()` mocked.

#### Scenario: No orphans found
- **WHEN** `handler_recover` runs and `recorder.discard_invalid_orphans` returns an empty list
- **THEN** it logs that there is nothing to recover and does not prompt for input

#### Scenario: User chooses to process
- **WHEN** `handler_recover` runs with valid orphans present and the mocked `input()` returns `'p'`
- **THEN** it calls `recorder.merge_and_cleanup` and `transcriber.transcribe` for each valid orphan

#### Scenario: User chooses to delete
- **WHEN** `handler_recover` runs with valid orphans present and the mocked `input()` returns `'a'`
- **THEN** it calls `recorder.delete_orphan` for each valid orphan and does not call `transcriber.transcribe`

#### Scenario: User chooses to ignore
- **WHEN** `handler_recover` runs with valid orphans present and the mocked `input()` returns `'i'` (or any value other than `'p'`/`'a'`)
- **THEN** it leaves the orphan directories untouched and does not call `merge_and_cleanup`, `delete_orphan`, or `transcribe`
