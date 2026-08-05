## MODIFIED Requirements

### Requirement: Speech-to-text transcription
The system SHALL transcribe the preprocessed audio (or each chunk) by sending a JSON request with base64-encoded audio to an OpenAI-compatible `/audio/transcriptions` endpoint, using the configured transcription model and base URL, SHALL prepend matched calendar event context (event title, description, and attendee names) to the configured transcription prompt when a calendar event matched the recording, and SHALL retry a failed request immediately, up to a bounded number of attempts, when the failure is classified as retryable.

#### Scenario: Successful transcription request
- **WHEN** a preprocessed audio chunk is sent to the transcription endpoint with the configured model and prompt
- **THEN** the returned text is captured and included in the final concatenated transcript

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
- **WHEN** a request to the transcription endpoint fails with a retryable error (a timeout, a connection error, or an HTTP 429/5xx response) and a subsequent immediate retry, within the bounded attempt limit of 3 total attempts, succeeds
- **THEN** the returned text from the successful attempt is used as if the earlier failed attempt(s) had not happened, and no failure is surfaced to the user

#### Scenario: Retryable transcription request failure exhausts immediate retries
- **WHEN** a request to the transcription endpoint fails with a retryable error on every attempt up to the bounded limit of 3 total attempts
- **THEN** the transcription run fails, no partial output files are written, and the failure is handed off for deferred retry instead of being surfaced immediately as a terminal failure

#### Scenario: Non-retryable transcription request failure skips immediate retries
- **WHEN** a request to the transcription endpoint fails with a non-retryable error (an HTTP 401 response indicating an invalid API key, or any other 4xx response other than 429)
- **THEN** no immediate retry is attempted, the transcription run fails, no partial output files are written, and the failure is handed off for deferred retry instead of being surfaced immediately as a terminal failure

## ADDED Requirements

### Requirement: Deferred retry for exhausted or non-retryable transcription failures
The system SHALL, when a transcription run fails after immediate retries are exhausted or bypassed as non-retryable, defer that recording's `.wav` file for a full pipeline reprocess later rather than treating the failure as terminal, persisting the deferred state so it survives an application restart, and SHALL retry the full transcription pipeline (preprocessing through output-file writing) for that file according to a graduated backoff schedule.

#### Scenario: Transcription deferred after exhausted or non-retryable failure
- **WHEN** a transcription run fails after immediate retries are exhausted, or is bypassed to deferral because the failure was non-retryable
- **THEN** the recording's `.wav` path is recorded in a persistent deferred-retry ledger with an initial backoff wait before the next attempt, and no user-facing failure notification is shown yet

#### Scenario: Deferred retry follows a graduated backoff schedule
- **WHEN** a deferred transcription's most recent retry attempt fails again
- **THEN** the wait before the next retry attempt increases according to a graduated schedule (approximately 5 minutes, 30 minutes, 2 hours, then 6 hours after successive failures, capping at 24 hours between any subsequent attempts)

#### Scenario: Deferred retry survives an application restart
- **WHEN** the menu bar application is quit and relaunched (or the machine restarts) while a transcription is still deferred and not yet due for its next retry
- **THEN** the deferred entry is still present after relaunch and is retried once its scheduled wait has elapsed

#### Scenario: Deferred retry succeeds
- **WHEN** a deferred transcription is retried and the full pipeline (preprocessing through output-file writing) completes successfully
- **THEN** the transcript and summary output files are written as usual, and the deferred-retry entry is cleared

### Requirement: Configurable total retry window and final abandonment notification
The system SHALL bound deferred retries by a configurable total time window (default 7 days) measured from the transcription's first failure, SHALL abandon a deferred transcription once that window elapses without a successful retry, and SHALL show the existing transcription-failure notification exactly once, at abandonment, without notifying on any intermediate deferred attempt.

#### Scenario: Deferred retries continue silently within the window
- **WHEN** a deferred transcription fails again but the time elapsed since its first failure is still within the configured total retry window
- **THEN** the entry remains deferred with an updated attempt count and next-retry time, and no notification is shown

#### Scenario: Deferred retries abandoned after the window elapses
- **WHEN** a deferred transcription's next scheduled retry check occurs and the time elapsed since its first failure exceeds the configured total retry window
- **THEN** the entry is marked abandoned, no further automatic retries occur for it, and the existing transcription-failure notification is shown to the user

#### Scenario: Total retry window is configurable
- **WHEN** `config.yaml` sets a value for the total transcription retry window, in days
- **THEN** that value is used instead of the default of 7 days when determining abandonment for deferred transcriptions
