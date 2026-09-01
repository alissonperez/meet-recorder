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

### Requirement: Recording title rename is verified
The test suite SHALL verify the recorder's post-merge titling step against real files in a temporary directory, with the calendar lookup mocked so no network call occurs. Every scenario SHALL assert that a complete recording remains on disk afterwards, since the step's purpose is to never put a saved recording at risk.

#### Scenario: Matched event title renames the recording
- **WHEN** the titling step runs on a merged `<timestamp>.wav` while the mocked calendar lookup returns an event
- **THEN** the file is renamed to the start timestamp, the ` - ` separator, the slugified event title and the `.wav` extension, that path is returned, and the file's contents are unchanged

#### Scenario: No matched event leaves the file untouched
- **WHEN** the titling step runs while the mocked calendar lookup returns no event
- **THEN** the file keeps its bare `<timestamp>.wav` name, that path is returned, and no rename is attempted

#### Scenario: Calendar lookup error is absorbed
- **WHEN** the titling step runs while the mocked calendar lookup raises
- **THEN** no exception propagates, the untitled path is returned, and the recording is still present and intact

#### Scenario: Rename failure is absorbed
- **WHEN** the titling step runs and the rename itself fails
- **THEN** no exception propagates, the untitled path is returned, and the recording is still present and intact

#### Scenario: Existing destination is not overwritten
- **WHEN** the titling step runs and a file already occupies the titled destination path
- **THEN** the recording keeps its untitled name and the pre-existing file's contents are unchanged

#### Scenario: Audio is on disk before the calendar lookup runs
- **WHEN** a merge-and-save runs with the calendar lookup mocked to inspect the filesystem when it is called
- **THEN** the complete merged recording is already present at the untitled path at that moment

#### Scenario: Overlong or unsafe title is bounded
- **WHEN** the titling step runs for an event whose title exceeds the title length limit or contains path-unsafe characters
- **THEN** the resulting filename's title portion is truncated to the limit, contains no path separators or other unsafe characters, and the file lands in the recordings directory rather than a nested path
