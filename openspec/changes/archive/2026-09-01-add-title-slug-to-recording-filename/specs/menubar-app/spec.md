## MODIFIED Requirements

### Requirement: Deferred retry for failed menu bar transcriptions
The system SHALL, when a transcription started by the menu bar app fails after its immediate per-request retries are exhausted or bypassed as non-retryable, record that recording's `.wav` path in a persistent deferred-retry ledger rather than treating the failure as terminal, and SHALL later retry the full transcription pipeline (preprocessing through output-file writing) for that file on a fixed one-hour retry interval. Deferral SHALL apply identically to transcriptions started from the normal stop-recording flow and from the crash-recovery process action. A deferred entry SHALL remain identified by the recording's path as it was when the entry was created; because a successful run may rename the recording as its final step, the system SHALL clear a succeeding retry's entry under that original path, so a rename can never strand an entry that would otherwise be retried until its budget ran out.

#### Scenario: Transcription deferred after a failed attempt
- **WHEN** a menu-bar-initiated transcription run fails after immediate retries are exhausted, or because the failure was non-retryable
- **THEN** the recording's `.wav` path is recorded in the persistent deferred-retry ledger with its attempt count incremented, and no user-facing failure notification is shown yet

#### Scenario: Deferred retry survives an application restart
- **WHEN** the menu bar application is quit and relaunched (or the machine restarts) while a transcription is still deferred and not yet due for its next retry
- **THEN** the deferred entry is still present after relaunch and is retried once its one-hour interval has elapsed

#### Scenario: Deferred retry succeeds
- **WHEN** a deferred transcription is retried and the full pipeline (preprocessing through output-file writing) completes successfully
- **THEN** the transcript and summary output files are written as usual, and the deferred-retry entry is marked done so it is not retried again

#### Scenario: Deferred retry that renames the recording still clears its entry
- **WHEN** a deferred transcription is retried, succeeds, and its final step renames the recording to carry the run's title
- **THEN** the deferred-retry entry created under the recording's pre-rename path is marked done, so neither the old nor the new path is ever retried again

#### Scenario: Crash-recovered transcriptions use the same deferred-retry flow
- **WHEN** a transcription started from the crash-recovery "Processar" action fails after immediate retries are exhausted or bypassed
- **THEN** it is deferred and later retried the same way as a transcription started from the normal "Parar" flow, rather than immediately notifying the user

#### Scenario: A deleted recording ends its retry loop
- **WHEN** a deferred entry's `.wav` file no longer exists on disk at the time of a scan
- **THEN** the entry is dropped from the ledger without being retried or counted as a further failed attempt
