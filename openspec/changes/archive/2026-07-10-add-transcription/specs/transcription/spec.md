## ADDED Requirements

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
The system SHALL transcribe the preprocessed audio (or each chunk) by sending a JSON request with base64-encoded audio to an OpenAI-compatible `/audio/transcriptions` endpoint, using the configured transcription model and base URL.

#### Scenario: Successful transcription request
- **WHEN** a preprocessed audio chunk is sent to the transcription endpoint with the configured model and prompt
- **THEN** the returned text is captured and included in the final concatenated transcript

#### Scenario: Transcription request fails
- **WHEN** a request to the transcription endpoint fails (network error or non-success response)
- **THEN** the transcription run fails, is logged, and the source `.wav` is left untouched with no partial output files written

### Requirement: Title generation
The system SHALL generate a short title (at most 60 characters) for the recording via a dedicated LLM chat call, independent of the summary generation call, using the configured title model and prompt.

#### Scenario: Generated title fits the length limit
- **WHEN** the title generation call returns a title of 60 characters or fewer
- **THEN** that title is used as-is for naming output files

#### Scenario: Generated title exceeds the length limit
- **WHEN** the title generation call returns a title longer than 60 characters
- **THEN** the system retries the call up to a bounded number of attempts asking for a shorter title, and truncates to 60 characters as a final fallback if the limit is still exceeded

### Requirement: Summary generation
The system SHALL generate a structured Markdown summary of the full transcript via a dedicated LLM chat call, using the configured summary model and prompt, without attributing speech to specific speakers.

#### Scenario: Summary generated for a completed transcript
- **WHEN** the full transcript text is available
- **THEN** a summary is generated via a single LLM chat call and is not conditioned on any calendar or speaker-identity data

### Requirement: Output file persistence
The system SHALL write the full transcript and the generated summary as two separate Markdown files, named using the recording's timestamp and a slugified version of the generated title, organized under the configured output directories in per-month subfolders.

#### Scenario: Both output files are written on success
- **WHEN** transcription and summary generation both complete successfully
- **THEN** a transcript file is written to `transcript_dir/YYYY-MM/TIMESTAMP - Title-Slug.md` and a summary file is written to `summary_dir/YYYY-MM/TIMESTAMP - Title-Slug.md`, where `YYYY-MM` and `TIMESTAMP` are derived from the recording's own timestamp

### Requirement: Source recording is never deleted or renamed
The system SHALL leave the source `.wav` file unmodified and in place regardless of whether transcription succeeds or fails.

#### Scenario: Transcription succeeds
- **WHEN** transcription and output file writing complete successfully
- **THEN** the source `.wav` file still exists at its original path, unmodified

#### Scenario: Transcription fails at any step
- **WHEN** any step of transcription (preprocessing, chunking, STT, title generation, summary generation, or file writing) fails
- **THEN** the source `.wav` file still exists at its original path, unmodified, and can be reprocessed later

### Requirement: Manual CLI transcription
The system SHALL expose a CLI command that runs the full transcription pipeline against an existing `.wav` file, independent of the menu bar app.

#### Scenario: Transcribing an existing recording via CLI
- **WHEN** the `transcribe` CLI command is invoked with the path to an existing `.wav` file
- **THEN** the same transcription pipeline used by the menu bar app runs against that file and produces the same transcript and summary output files

### Requirement: Documented configuration setup
The system's documentation (`README.md`) SHALL describe every piece of configuration required for transcription to work: the `~/.config/meet-recorder/config.yaml` file and its required fields (transcription/summary/title models, the three prompts, `transcript_dir`, `summary_dir`, chunk duration, `base_url`), the `OPENROUTER_API_KEY` environment variable, and the `ffmpeg` system dependency.

#### Scenario: New user sets up transcription from the README alone
- **WHEN** a user with no prior context reads `README.md` to enable transcription
- **THEN** the README explains where to place `config.yaml`, lists every required/optional field with its purpose, states that `OPENROUTER_API_KEY` belongs in `.env` and not in `config.yaml`, and states that `ffmpeg` must be installed and on `PATH`

#### Scenario: Example config file is referenced from the README
- **WHEN** the README documents `config.yaml`
- **THEN** it references the example/template config file shipped in the repo (e.g. `config.example.yaml`) as the starting point for the user's own config
