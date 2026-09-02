## MODIFIED Requirements

### Requirement: Transcript/summary filename and title generation is verified
The test suite SHALL verify `meet_recorder.transcriber`'s pure filename/timestamp/markdown helpers and `_generate_title`'s retry-until-short-enough-then-truncate behavior, with `_chat_completion` and `subprocess.run` mocked so no network or `ffmpeg`/`ffprobe` call occurs. Timestamp resolution SHALL be verified for both a bare-timestamp filename and a filename carrying a meeting-title suffix.

#### Scenario: Timestamp parsed from filename
- **WHEN** `_resolve_timestamp` is called on a path whose stem matches `FILENAME_TIMESTAMP_FORMAT`
- **THEN** it returns the parsed timestamp rather than falling back to file mtime

#### Scenario: Timestamp parsed from a titled filename
- **WHEN** `_resolve_timestamp` is called on a path whose stem is a `FILENAME_TIMESTAMP_FORMAT` timestamp followed by a meeting-title suffix
- **THEN** it returns the timestamp parsed from the prefix rather than falling back to file mtime

#### Scenario: Timestamp falls back to mtime
- **WHEN** `_resolve_timestamp` is called on a path whose stem does not begin with a value matching `FILENAME_TIMESTAMP_FORMAT`
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

## ADDED Requirements

### Requirement: Meeting title slugification is verified
The test suite SHALL verify the shared helper that turns a meeting title into the slug used in both the recording filename and the transcript/summary filenames, covering length capping, filesystem-unsafe characters, and titles that yield no usable slug.

#### Scenario: Normal title is slugified with its case preserved
- **WHEN** the helper is called with an ordinary multi-word title
- **THEN** it returns that title slugified with its capitalization preserved

#### Scenario: Overlong title is truncated to the cap
- **WHEN** the helper is called with a title longer than the slug length cap
- **THEN** the returned slug is exactly the cap in length

#### Scenario: Path-unsafe characters are stripped
- **WHEN** the helper is called with a title containing characters such as `/`, `:`, or quotes
- **THEN** none of those characters appear in the returned slug

#### Scenario: Title with no usable characters yields an empty slug
- **WHEN** the helper is called with an empty title, or one consisting only of punctuation
- **THEN** it returns an empty string, so callers can treat "no usable title" as a single case

### Requirement: Post-success recording rename is verified
The test suite SHALL verify the transcription pipeline's final rename step against real files in a temporary directory, with the transcription, summary, and title network calls mocked so no network call occurs. Every scenario SHALL assert that a complete recording remains on disk afterwards and that the transcript and summary files written by the run are present and unchanged, since the step runs after the run's real work is already done and must never put it at risk.

#### Scenario: Successful run renames the recording to the run's title
- **WHEN** a mocked-out transcription run completes successfully for a recording named with a bare start timestamp
- **THEN** the recording is renamed to that start timestamp, the ` - ` separator, the same title slug the transcript and summary carry, and the `.wav` extension, and its contents are unchanged

#### Scenario: Recording already carrying the title is not renamed
- **WHEN** a successful run's title matches the title already in the recording's filename
- **THEN** no rename occurs and the recording keeps its filename

#### Scenario: Rename failure leaves a successful run successful
- **WHEN** the rename itself fails after the output files have been written
- **THEN** no exception propagates, the run's result is returned as a success, and the recording is still present and intact at its pre-rename path

#### Scenario: Existing destination is not overwritten
- **WHEN** a file already occupies the path the recording would be renamed to
- **THEN** the recording keeps its current name and the pre-existing file's contents are unchanged

#### Scenario: Title that slugifies to nothing leaves the name alone
- **WHEN** a successful run's title slugifies to an empty string
- **THEN** no rename occurs and the recording keeps its filename, with no trailing separator added

#### Scenario: Recording with no parseable timestamp prefix is not renamed
- **WHEN** a successful run completes for a recording whose filename does not begin with a parseable timestamp
- **THEN** no rename occurs and the recording keeps the filename it had

#### Scenario: Failed run does not rename the recording
- **WHEN** a transcription run fails at any step before the output files are written
- **THEN** the recording is still at its original path with its original name

#### Scenario: Outputs are written before the rename is attempted
- **WHEN** a successful run is observed at the moment the rename is performed
- **THEN** the transcript and summary files are already present and complete on disk

### Requirement: Deferred retry over a renamed recording is verified
The test suite SHALL verify that a deferred transcription retry which succeeds and renames its recording still clears the ledger entry created under the recording's pre-rename path, with the transcription pipeline mocked so no network call occurs.

#### Scenario: Succeeding retry clears the entry it was keyed by
- **WHEN** a deferred retry runs for a recording, the mocked pipeline succeeds, and the recording is renamed as the run's final step
- **THEN** the deferred-retry entry is marked done under the path the retry was started with, leaving no entry that a later scan could retry
