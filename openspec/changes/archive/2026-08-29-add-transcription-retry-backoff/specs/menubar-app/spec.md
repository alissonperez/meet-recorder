## ADDED Requirements

### Requirement: Deferred retry for failed menu bar transcriptions
The system SHALL, when a transcription started by the menu bar app fails after its immediate per-request retries are exhausted or bypassed as non-retryable, record that recording's `.wav` path in a persistent deferred-retry ledger rather than treating the failure as terminal, and SHALL later retry the full transcription pipeline (preprocessing through output-file writing) for that file on a fixed one-hour retry interval. Deferral SHALL apply identically to transcriptions started from the normal stop-recording flow and from the crash-recovery process action.

#### Scenario: Transcription deferred after a failed attempt
- **WHEN** a menu-bar-initiated transcription run fails after immediate retries are exhausted, or because the failure was non-retryable
- **THEN** the recording's `.wav` path is recorded in the persistent deferred-retry ledger with its attempt count incremented, and no user-facing failure notification is shown yet

#### Scenario: Deferred retry survives an application restart
- **WHEN** the menu bar application is quit and relaunched (or the machine restarts) while a transcription is still deferred and not yet due for its next retry
- **THEN** the deferred entry is still present after relaunch and is retried once its one-hour interval has elapsed

#### Scenario: Deferred retry succeeds
- **WHEN** a deferred transcription is retried and the full pipeline (preprocessing through output-file writing) completes successfully
- **THEN** the transcript and summary output files are written as usual, and the deferred-retry entry is marked done so it is not retried again

#### Scenario: Crash-recovered transcriptions use the same deferred-retry flow
- **WHEN** a transcription started from the crash-recovery "Processar" action fails after immediate retries are exhausted or bypassed
- **THEN** it is deferred and later retried the same way as a transcription started from the normal "Parar" flow, rather than immediately notifying the user

#### Scenario: A deleted recording ends its retry loop
- **WHEN** a deferred entry's `.wav` file no longer exists on disk at the time of a scan
- **THEN** the entry is dropped from the ledger without being retried or counted as a further failed attempt

### Requirement: Periodic deferred-transcription retry scan
The system SHALL run a background timer in the menu bar app that periodically scans the deferred-retry ledger for entries whose one-hour retry interval has elapsed and retries each of them in a background thread, reflecting an in-progress retry in the existing transcribing icon state. The system SHALL keep an in-memory record of the recordings currently being transcribed and SHALL skip any due entry already in progress, so the same `.wav` is never transcribed concurrently by two attempts.

#### Scenario: Scan retries a due deferred transcription
- **WHEN** the periodic scan runs and a deferred transcription's retry interval has elapsed
- **THEN** the full transcription pipeline is retried for that recording in a background thread, with the menu bar icon showing the transcribing state for the duration of the attempt

#### Scenario: Scan skips deferred transcriptions not yet due
- **WHEN** the periodic scan runs and a deferred transcription's retry interval has not yet elapsed
- **THEN** that transcription is left untouched until a later scan

#### Scenario: Scan skips a retry that is still running
- **WHEN** the periodic scan runs and a due entry's recording is already being transcribed (by an earlier scan's retry, or by the original stop-recording or crash-recovery attempt that has not finished unwinding)
- **THEN** no second attempt is started for that recording, and it remains eligible for a later scan once the in-progress attempt finishes

### Requirement: Bounded transcription retries and failure notification
The system SHALL bound deferred transcription retries by a configurable maximum number of attempts (`transcription_max_retries`, default 72, which at the fixed one-hour interval spans roughly three days), SHALL abandon a deferred transcription once that count is reached, and SHALL show the transcription-failure notification exactly once, at abandonment, without notifying on any earlier failed attempt.

#### Scenario: Deferred retries continue silently within the attempt budget
- **WHEN** a deferred transcription fails again and its attempt count is still below the configured maximum
- **THEN** the entry remains deferred with an updated attempt count and next-retry time, and no notification is shown

#### Scenario: Deferred retries abandoned once the attempt budget is spent
- **WHEN** a deferred transcription fails on the attempt that reaches the configured maximum
- **THEN** the entry is marked abandoned, no further automatic retries occur for it, and the transcription-failure notification is shown to the user once

#### Scenario: Maximum retry count is configurable
- **WHEN** `config.yaml` sets a value for `transcription_max_retries`
- **THEN** that value is used, within its supported bounds, instead of the default of 72 when determining abandonment for deferred transcriptions

#### Scenario: Source recording survives abandonment
- **WHEN** a deferred transcription is abandoned after exhausting its attempt budget
- **THEN** the source `.wav` file is still present and unmodified at its original path and can be reprocessed manually via the `transcribe` CLI command
