## MODIFIED Requirements

### Requirement: Speech-to-text transcription
The system SHALL transcribe the preprocessed audio (or each chunk) by sending a JSON request with base64-encoded audio to an OpenAI-compatible `/audio/transcriptions` endpoint, using the configured transcription model and base URL, and SHALL prepend matched calendar event context (event title, description, and attendee names) to the configured transcription prompt when a calendar event matched the recording.

#### Scenario: Successful transcription request
- **WHEN** a preprocessed audio chunk is sent to the transcription endpoint with the configured model and prompt
- **THEN** the returned text is captured and included in the final concatenated transcript

#### Scenario: Transcription request fails
- **WHEN** a request to the transcription endpoint fails (network error or non-success response)
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

### Requirement: Summary generation
The system SHALL generate a structured Markdown summary of the full transcript via a dedicated LLM chat call using the configured summary model and prompt, without attributing speech to specific speakers, optionally prepending matched calendar event context (event title, description, and attendee names) to the summary input.

#### Scenario: Summary generated without a calendar match
- **WHEN** the full transcript text is available and no calendar event matched
- **THEN** a summary is generated via a single LLM chat call from the transcript alone, unchanged from prior behavior

#### Scenario: Summary enriched with calendar context
- **WHEN** the full transcript text is available and a calendar event matched the recording
- **THEN** the event's title, description (when present), and attendee names are prepended to the summary user input while the summary system prompt is unchanged, and speech is still not attributed to specific speakers

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
