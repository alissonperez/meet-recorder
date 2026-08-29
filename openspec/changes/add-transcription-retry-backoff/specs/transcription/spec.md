## MODIFIED Requirements

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

### Requirement: Manual CLI transcription
The system SHALL expose a CLI command that runs the full transcription pipeline against an existing `.wav` file, independent of the menu bar app. A CLI run SHALL benefit from the immediate per-request retries, but SHALL NOT be deferred for a later automatic retry, since the deferred-retry scan requires the long-running menu bar process.

#### Scenario: Transcribing an existing recording via CLI
- **WHEN** the `transcribe` CLI command is invoked with the path to an existing `.wav` file
- **THEN** the same transcription pipeline used by the menu bar app runs against that file and produces the same transcript and summary output files

#### Scenario: A failed CLI transcription is terminal
- **WHEN** a `transcribe` CLI run fails after its immediate retries are exhausted or bypassed as non-retryable
- **THEN** the command reports the failure and exits without scheduling any deferred retry, and the source `.wav` is left untouched for a manual rerun
