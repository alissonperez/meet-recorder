# transcription Specification

## Purpose
TBD - created by syncing change add-transcription. Update Purpose after archive.

## Requirements

### Requirement: YAML configuration for transcription
The system SHALL load transcription settings (transcription model, summary model, title model, transcription prompt, summary prompt, title prompt, transcript output directory, summary output directory, chunk duration, and API base URL) from a YAML file at `~/.config/meet-recorder/config.yaml`, and SHALL NOT read the OpenRouter API key from this file.

#### Scenario: Config file loaded successfully
- **WHEN** transcription is triggered and `~/.config/meet-recorder/config.yaml` exists with all required fields
- **THEN** the configured models, prompts, output directories, chunk duration, and base URL are used for that transcription run

#### Scenario: Config file missing or malformed
- **WHEN** transcription is triggered and `~/.config/meet-recorder/config.yaml` is missing or fails to parse/validate
- **THEN** the transcription fails fast with a clear error, no partial output files are written, and the source recording is left untouched

#### Scenario: API key is never read from the YAML config
- **WHEN** the OpenRouter API key is needed for any request
- **THEN** it is read from the `OPENROUTER_API_KEY` environment variable (via `.env`), never from `config.yaml`

### Requirement: Audio preprocessing before transcription
The system SHALL convert a recording's stereo `.wav` file to a mono, compressed mp3 via `ffmpeg` before sending it for transcription.

#### Scenario: Stereo recording is downmixed and compressed
- **WHEN** a `.wav` recording with separate microphone and system-audio channels is prepared for transcription
- **THEN** `ffmpeg` produces a mono mp3 at a reduced bitrate/sample rate suitable for the transcription API payload

#### Scenario: ffmpeg is unavailable
- **WHEN** the `ffmpeg` binary is not found on `PATH`
- **THEN** transcription fails with a clear error, the source `.wav` is left untouched, and no partial output files are written

### Requirement: Chunking for long recordings
The system SHALL split audio exceeding a configured chunk duration into sequential, non-overlapping chunks, transcribe each chunk independently, and concatenate the resulting text in order.

#### Scenario: Recording shorter than the chunk duration
- **WHEN** the preprocessed audio duration is less than or equal to the configured chunk duration
- **THEN** it is transcribed as a single request without chunking

#### Scenario: Recording longer than the chunk duration
- **WHEN** the preprocessed audio duration exceeds the configured chunk duration
- **THEN** the audio is split into sequential chunks of that duration, each is transcribed independently via a separate request, and the resulting texts are concatenated in chronological order with no overlap or deduplication between chunk boundaries

### Requirement: Speech-to-text transcription
The system SHALL transcribe the preprocessed audio (or each chunk) by sending a JSON request with base64-encoded audio to an OpenAI-compatible `/audio/transcriptions` endpoint, using the configured transcription model and base URL, SHALL prepend matched calendar event context (event title, description, and attendee names) to the configured transcription prompt when a calendar event matched the recording, and SHALL retry a failed request immediately, up to a bounded limit of 3 total attempts, when the failure is classified as retryable.

#### Scenario: Successful transcription request
- **WHEN** a preprocessed audio chunk is sent to the transcription endpoint with the configured model and prompt
- **THEN** the returned text is captured and included in the final concatenated transcript

#### Scenario: Transcription request fails
- **WHEN** a request to the transcription endpoint fails (network error or non-success response) and no permitted immediate retry succeeds
- **THEN** the transcription run fails, is logged, and the source `.wav` is left untouched with no partial output files written

#### Scenario: Transcription prompt enriched with calendar context
- **WHEN** a calendar event matched the recording
- **THEN** the event's title, description (when present), and attendee names are prepended to the configured `transcription_prompt` before it is sent as the `prompt` hint on every chunk's transcription request

#### Scenario: Transcription prompt unchanged without a calendar match
- **WHEN** no calendar event matched (or calendar is unconfigured)
- **THEN** the configured `transcription_prompt` is sent as-is when it is non-empty and the `prompt` hint is omitted when it is empty, both unchanged from prior behavior

#### Scenario: Event context sent when the configured prompt is empty
- **WHEN** a calendar event matched but `transcription_prompt` is empty
- **THEN** the event context (title, description when present, attendee names) is still sent as the `prompt` hint on each chunk's request

#### Scenario: Retryable transcription request failure succeeds on retry
- **WHEN** a request to the transcription endpoint fails with a retryable error (a timeout, a connection error, or an HTTP 429/5xx response) and a subsequent immediate retry, within the bounded limit of 3 total attempts, succeeds
- **THEN** the returned text from the successful attempt is used as if the earlier failed attempt(s) had not happened, and no failure is surfaced to the user

#### Scenario: Retryable transcription request failure exhausts immediate retries
- **WHEN** a request to the transcription endpoint fails with a retryable error on every attempt up to the bounded limit of 3 total attempts
- **THEN** the transcription run fails to its caller with no partial output files written, leaving the caller to decide whether the failure is terminal or deferred for a later retry

#### Scenario: Non-retryable transcription request failure skips immediate retries
- **WHEN** a request to the transcription endpoint fails with a non-retryable error (an HTTP 401 response indicating an invalid API key, any other 4xx response other than 429, or a missing API key detected before the request is sent)
- **THEN** no immediate retry is attempted, and the transcription run fails to its caller with no partial output files written

### Requirement: Title generation
The system SHALL resolve a recording's title from a matching calendar event when one is found, and otherwise generate a short title (at most 60 characters) via a dedicated LLM chat call using the configured title model and prompt, independent of the summary generation call.

#### Scenario: Matching calendar event provides the title
- **WHEN** a calendar event matches the recording's start time
- **THEN** the event's title is used as the recording's title and the LLM title generation call is skipped

#### Scenario: No matching event, generated title fits the length limit
- **WHEN** no calendar event matches (or calendar is unconfigured) and the title generation call returns a title of 60 characters or fewer
- **THEN** that generated title is used as-is for naming output files

#### Scenario: No matching event, generated title exceeds the length limit
- **WHEN** no calendar event matches and the title generation call returns a title longer than 60 characters
- **THEN** the system retries the call up to a bounded number of attempts asking for a shorter title, and truncates to 60 characters as a final fallback if the limit is still exceeded

### Requirement: Summary generation
The system SHALL generate a structured Markdown summary of the full transcript via a dedicated LLM chat call using the configured summary model and prompt, without attributing speech to specific speakers, optionally prepending matched calendar event context (event title, description, and attendee names) to the summary input.

#### Scenario: Summary generated without a calendar match
- **WHEN** the full transcript text is available and no calendar event matched
- **THEN** a summary is generated via a single LLM chat call from the transcript alone, unchanged from prior behavior

#### Scenario: Summary enriched with calendar context
- **WHEN** the full transcript text is available and a calendar event matched the recording
- **THEN** the event's title, description (when present), and attendee names are prepended to the summary user input while the summary system prompt is unchanged, and speech is still not attributed to specific speakers

### Requirement: Calendar enrichment is non-fatal and optional
The system SHALL treat calendar lookup during transcription as optional and non-fatal, producing identical output to the pre-calendar behavior whenever calendar is unconfigured, no event matches, or the lookup fails.

#### Scenario: Calendar lookup fails during transcription
- **WHEN** the calendar lookup raises an error or times out while transcribing
- **THEN** the failure is logged as a warning and transcription completes using the LLM-generated title and an unenriched summary, with no output files lost

### Requirement: Calendar fields in output frontmatter
The system SHALL include calendar-derived fields (source calendar, event start, event end, and attendees) in the transcript and summary frontmatter when a calendar event matched the recording, and SHALL omit those fields otherwise.

#### Scenario: Frontmatter includes calendar fields on a match
- **WHEN** a calendar event matched the recording
- **THEN** the transcript and summary frontmatter include the event's source calendar, start, end, and attendee list alongside the title

#### Scenario: Frontmatter omits calendar fields without a match
- **WHEN** no calendar event matched (or calendar is unconfigured)
- **THEN** the frontmatter contains only the fields it did before this change, with no empty calendar keys

### Requirement: Output file persistence
The system SHALL write the full transcript and the generated summary as two separate Markdown files, named using the recording's start timestamp and a slugified version of the generated title, organized under the configured output directories in per-month subfolders.

#### Scenario: Both output files are written on success
- **WHEN** transcription and summary generation both complete successfully
- **THEN** a transcript file is written to `transcript_dir/YYYY-MM/TIMESTAMP - Title-Slug.md` and a summary file is written to `summary_dir/YYYY-MM/TIMESTAMP - Title-Slug.md`, where `YYYY-MM` and `TIMESTAMP` are derived from the recording's start timestamp

#### Scenario: Long recording keeps its start-time filename
- **WHEN** a recording ran long enough that its start and stop fall in different months (or different days)
- **THEN** the transcript and summary are still filed under the `YYYY-MM` folder and `TIMESTAMP` matching when the recording started, not when it stopped

### Requirement: Source recording is never deleted or renamed
The system SHALL leave the source `.wav` file's contents unmodified and SHALL never delete or move it out of its directory, regardless of whether transcription succeeds or fails. The system SHALL NOT rename the source recording at any point during a transcription run, except as the final step of a fully successful run, where the recording is renamed in place to carry the meeting title, as specified in "Successful transcription renames the recording to its final title". A run that fails at any step SHALL leave the recording at exactly the path it was given.

#### Scenario: Transcription succeeds
- **WHEN** transcription and output file writing complete successfully
- **THEN** the source `.wav` file still exists in its original directory with its contents unmodified, under either its original name or the final-title name

#### Scenario: Transcription fails at any step
- **WHEN** any step of transcription (preprocessing, chunking, STT, title generation, summary generation, or file writing) fails
- **THEN** the source `.wav` file still exists at its original path, unmodified and not renamed, and can be reprocessed later

### Requirement: Successful transcription renames the recording to its final title
As the last step of a transcription run in which every output file was written successfully, the system SHALL rename the source recording so that it carries the same slugified meeting title its transcript and summary carry, using the same separator and slugification rules, so the audio and its transcript are findable under the same meeting name. The recording SHALL keep its own start-timestamp prefix and timestamp format; only the title portion is shared with the Markdown outputs, whose own filenames SHALL NOT change. The rename SHALL target whichever title the run actually used, whether it came from a matched calendar event or was generated from the summary.

#### Scenario: Untitled recording gains the title
- **WHEN** transcription of a recording named with a bare start timestamp completes successfully
- **THEN** the recording is renamed in its own directory to that start timestamp followed by ` - ` and the same title slug the transcript and summary use, keeping its `.wav` extension and its own timestamp format

#### Scenario: Recording already carrying the final title is left alone
- **WHEN** transcription completes successfully and the recording's filename already carries the run's title
- **THEN** no rename is performed and the recording keeps its filename

#### Scenario: Recording carrying a different title is brought in line
- **WHEN** transcription completes successfully with a title that differs from the one already in the recording's filename
- **THEN** the recording is renamed to the title the run used, so it matches the transcript and summary that were just written

#### Scenario: Output files are unaffected by the rename
- **WHEN** the recording is renamed after a successful run
- **THEN** the transcript and summary keep the names they were written under, and their contents are unchanged

### Requirement: The post-success rename never puts a recording or its outputs at risk
The system SHALL perform the rename only after every transcript and summary file has been written, and SHALL treat any failure in it as non-fatal: the failure is logged, the recording is left at its current path with its contents intact, and the run is still reported as successful, since its outputs are already written and valid. The system SHALL NOT overwrite an existing file when renaming.

#### Scenario: Rename failure does not fail the run
- **WHEN** the rename fails after the transcript and summary have been written
- **THEN** the failure is logged rather than propagated, the run is reported as successful, and the recording remains present and playable at its pre-rename path

#### Scenario: Rename never overwrites an existing file
- **WHEN** the filename the recording would be renamed to is already taken by another file
- **THEN** the rename is skipped, the recording keeps its current filename, and the existing file is left untouched

#### Scenario: A title that yields no usable slug leaves the name alone
- **WHEN** transcription completes successfully with a title that slugifies to nothing
- **THEN** no rename is performed and the recording keeps its current filename, with no trailing separator added

#### Scenario: Outputs are already written before the rename is attempted
- **WHEN** the run is interrupted at any point after the transcript and summary are written but before the recording has been renamed
- **THEN** both output files are complete on disk and the recording is complete at its pre-rename path, and re-running transcription on it produces the same outputs

### Requirement: Recording start timestamp resolved from a renamed filename
The system SHALL determine a recording's start timestamp by parsing the timestamp that prefixes the recording filename, whether or not a meeting-title suffix follows it, and SHALL fall back to the file's modification time only when no timestamp can be parsed from the prefix. This start timestamp drives calendar matching and the transcript/summary filenames, so a renamed recording must yield the same timestamp it did before the rename. The system SHALL NOT rename a recording whose filename carries no parseable timestamp prefix, so that a start time the system does not know is never asserted in a filename.

#### Scenario: Re-transcribing a renamed recording
- **WHEN** transcription is re-run on a recording that a previous successful run renamed to carry its title
- **THEN** the start timestamp is parsed from the filename's timestamp prefix, the file's modification time is not consulted, and the transcript and summary are filed under the same `YYYY-MM` folder and timestamp as the original run

#### Scenario: Untitled recording filename still works
- **WHEN** transcription runs on a recording whose filename is a bare start timestamp
- **THEN** the parsed start timestamp is used exactly as it was before, with no change in behavior

#### Scenario: Unparseable filename falls back to modification time
- **WHEN** transcription runs on a recording whose filename does not begin with a parseable timestamp
- **THEN** the start timestamp is derived from the file's modification time

#### Scenario: Recording with no parseable timestamp prefix is not renamed
- **WHEN** a transcription run completes successfully for a recording whose filename does not begin with a parseable timestamp
- **THEN** no rename is performed and the recording keeps the filename it had, rather than being given a filename built from its modification time

### Requirement: Manual CLI transcription
The system SHALL expose a CLI command that runs the full transcription pipeline against an existing `.wav` file, independent of the menu bar app. A CLI run SHALL benefit from the immediate per-request retries, but SHALL NOT be deferred for a later automatic retry, since the deferred-retry scan requires the long-running menu bar process.

#### Scenario: Transcribing an existing recording via CLI
- **WHEN** the `transcribe` CLI command is invoked with the path to an existing `.wav` file
- **THEN** the same transcription pipeline used by the menu bar app runs against that file and produces the same transcript and summary output files

#### Scenario: A failed CLI transcription is terminal
- **WHEN** a `transcribe` CLI run fails after its immediate retries are exhausted or bypassed as non-retryable
- **THEN** the command reports the failure and exits without scheduling any deferred retry, and the source `.wav` is left untouched for a manual rerun

### Requirement: Documented configuration setup
The system's documentation (`README.md`) SHALL describe every piece of configuration required for transcription to work: the `~/.config/meet-recorder/config.yaml` file and its required fields (transcription/summary/title models, the three prompts, `transcript_dir`, `summary_dir`, chunk duration, `base_url`), the `OPENROUTER_API_KEY` environment variable, and the `ffmpeg` system dependency. It SHALL additionally provide `docs/prompts.md`, documenting each of the three configurable prompts (transcription, summary, title), the dynamic context prepended to each (and under what conditions), and an example of the resulting output frontmatter.

#### Scenario: New user sets up transcription from the README alone
- **WHEN** a user with no prior context reads `README.md` to enable transcription
- **THEN** the README explains where to place `config.yaml`, lists every required/optional field with its purpose, states that `OPENROUTER_API_KEY` belongs in `.env` and not in `config.yaml`, and states that `ffmpeg` must be installed and on `PATH`

#### Scenario: Example config file is referenced from the README
- **WHEN** the README documents `config.yaml`
- **THEN** it references the example/template config file shipped in the repo (e.g. `config.example.yaml`) as the starting point for the user's own config

#### Scenario: Prompt behavior documented in docs/prompts.md
- **WHEN** a reader wants to know what context is fed into the transcription, summary, or title prompt and when
- **THEN** `docs/prompts.md` describes each of the three prompts, the dynamic calendar-event context (if any) prepended to it and the condition under which that happens, and shows an example of the frontmatter emitted on transcript/summary output files
