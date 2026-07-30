## ADDED Requirements

### Requirement: Periodic deferred-transcription retry scan
The system SHALL run a background timer in the menu bar app that periodically scans for deferred transcriptions (see the `transcription` capability's deferred-retry ledger) whose backoff wait has elapsed and retries them, reflecting an in-progress retry in the existing transcribing icon state, independent of whether the recording that originally failed was stopped normally or recovered from a crash.

#### Scenario: Scan retries a due deferred transcription
- **WHEN** the periodic scan runs and a deferred transcription's next-retry time has passed
- **THEN** the full transcription pipeline is retried for that recording in a background thread, with the menu bar icon showing the transcribing state for the duration of the attempt

#### Scenario: Scan skips deferred transcriptions not yet due
- **WHEN** the periodic scan runs and a deferred transcription's next-retry time has not yet passed
- **THEN** that transcription is left untouched until a later scan

#### Scenario: Crash-recovered transcriptions use the same deferred-retry flow
- **WHEN** a transcription started from the crash-recovery "Processar" action fails after immediate retries are exhausted or bypassed
- **THEN** it is deferred and later retried by the periodic scan the same way as a transcription started from the normal "Parar" flow, rather than immediately notifying the user
