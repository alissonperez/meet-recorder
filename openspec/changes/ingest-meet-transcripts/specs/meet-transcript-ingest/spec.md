## ADDED Requirements

### Requirement: Opt-in Meet-transcript ingestion configuration
The system SHALL read an optional `meet_transcripts` configuration section from `~/.config/meet-recorder/config.yaml` consisting of `enabled`, `poll_interval_minutes`, `lookback_hours`, and `max_access_retries`, and SHALL treat the periodic ingestion feature as disabled when the section is absent or `enabled` is false, without affecting existing behavior. The system SHALL provide a `meet_summary_prompt` setting used to summarize Meet-sourced transcripts.

#### Scenario: Feature configured and enabled
- **WHEN** `config.yaml` contains a `meet_transcripts` section with `enabled: true` and at least one `calendars` account is configured
- **THEN** the periodic poller is eligible to run and the CLI ingestion command operates over the configured `lookback_hours`

#### Scenario: Feature absent or disabled
- **WHEN** `config.yaml` has no `meet_transcripts` section, or it has `enabled: false`
- **THEN** the config still loads and validates, the periodic poller is a no-op, and unrelated behavior (recording, STT transcription, auto-record) is unchanged

#### Scenario: Look-back bounded by ledger retention
- **WHEN** a configured `lookback_hours` exceeds the dedup ledger's retention window
- **THEN** the effective look-back is clamped to at most the retention window so a processed occurrence cannot age out of the ledger while still inside the query window

### Requirement: Google Doc attachment classification
The system SHALL classify a calendar event's Google Doc attachments into Meet **transcript** docs and **Gemini notes** docs using the attachment `fileUrl` `usp=` marker as the primary, language-independent signal (`usp=drive_web` for transcript, `usp=meet_tnfm_calendar` for Gemini notes), and SHALL ignore attachments that match neither.

#### Scenario: Transcript attachment recognized
- **WHEN** an attachment's `fileUrl` contains `usp=drive_web` and its title ends with `- Transcript` or `- Transcript <n>`
- **THEN** it is classified as a transcript doc and its Drive file id is extracted from the `fileUrl` path

#### Scenario: Gemini notes attachment recognized regardless of UI language
- **WHEN** an attachment's `fileUrl` contains `usp=meet_tnfm_calendar` (title such as `Anotações do Gemini`)
- **THEN** it is classified as a Gemini notes doc, independent of the interface language of the title

#### Scenario: Unrelated attachment ignored
- **WHEN** an attachment matches neither marker (e.g. a manually attached file or a recording video)
- **THEN** it is ignored and does not contribute to ingestion

### Requirement: Recurring-occurrence attachment binding
The system SHALL bind a transcript attachment to a specific event occurrence only when the date embedded in the attachment title matches that occurrence's start date, so that a recurring occurrence — which surfaces transcript attachments accumulated from all past occurrences, including under former event names — is not reprocessed against historical transcripts.

#### Scenario: Only same-date transcripts are bound
- **WHEN** a recurring occurrence starting on a given date carries transcript attachments dated on that date and on earlier dates
- **THEN** only the attachments whose title date matches the occurrence's start date are ingested for that occurrence

#### Scenario: Multiple same-date transcript segments merged
- **WHEN** an occurrence has more than one transcript attachment for its own date (e.g. `- Transcript` and `- Transcript 2`)
- **THEN** they are treated as segments of the same meeting and concatenated in trailing-index order

#### Scenario: Ambiguous Gemini notes skipped
- **WHEN** an event carries more than one Gemini notes attachment (which have no date to disambiguate)
- **THEN** the Gemini notes are skipped for that occurrence and a warning is logged, while transcript ingestion still proceeds

### Requirement: Doc export to Markdown via Drive
The system SHALL export each selected Google Doc attachment to Markdown text using the Drive API and the account's OAuth credentials, and SHALL fail non-fatally with a clear re-authorization message when the account's token lacks the Drive scope.

#### Scenario: Doc exported as Markdown
- **WHEN** a transcript or Gemini notes doc is selected for an occurrence and the account token grants Drive read access
- **THEN** the doc content is retrieved as Markdown text for downstream summary and file output

#### Scenario: Token missing Drive scope
- **WHEN** the account's token predates the Drive scope and a Drive export is attempted
- **THEN** the export fails non-fatally with a message instructing the user to re-run the calendar auth command for that account, and other occurrences/accounts continue

### Requirement: Meet-sourced transcript and summary output
The system SHALL, for each eligible past occurrence, write a transcript Markdown file and a summary Markdown file using the existing transcription output layout (per-month directories, event-based filename, event frontmatter), using the calendar event title as the title and the occurrence start time as the timestamp. The summary SHALL be generated with the configured `meet_summary_prompt`, fed the transcript plus the Gemini notes as additional context when present.

#### Scenario: Transcript with Gemini notes
- **WHEN** an occurrence has both a transcript and Gemini notes
- **THEN** the transcript file contains the exported transcript and the summary is generated from the transcript with the Gemini notes supplied as extra context

#### Scenario: Transcript only
- **WHEN** an occurrence has a transcript but no Gemini notes
- **THEN** the transcript and summary are produced from the transcript alone

#### Scenario: Gemini notes only
- **WHEN** an occurrence has Gemini notes but no transcript
- **THEN** output is still produced, using the Gemini notes as the transcript body and generating the summary from those notes

#### Scenario: Overwrite on collision
- **WHEN** a Meet-sourced output file targets the same path as a recording-sourced file for the same meeting
- **THEN** the Meet-sourced file overwrites it

### Requirement: Persistent state ledger with per-occurrence status
The system SHALL maintain a persistent state ledger in the config directory, keyed by the occurrence event id, in which each entry carries a status (`done`, `deferred`, or `abandoned`), an access-failure attempt count, and a last-attempt timestamp. The ledger SHALL be app-managed runtime state stored separately from the user-edited `config.yaml`. The system SHALL skip occurrences whose status is terminal (`done` or `abandoned`), and SHALL prune entries whose last-attempt timestamp is older than a fixed retention window on each run.

#### Scenario: Completed occurrence not reprocessed
- **WHEN** an occurrence's transcript/summary files were written and its entry was set to `done`
- **THEN** a subsequent run within the look-back window skips that occurrence

#### Scenario: Abandoned occurrence not reprocessed
- **WHEN** an occurrence's access retries were exhausted and its entry was set to `abandoned`
- **THEN** subsequent runs skip that occurrence

#### Scenario: Unavailable transcript retried without a ledger entry
- **WHEN** a past occurrence has no transcript or Gemini notes attached yet
- **THEN** no ledger entry is created for it and it is retried on the next poll

#### Scenario: Ledger rotation
- **WHEN** a run loads the ledger and it contains entries whose last-attempt timestamp is older than the retention window
- **THEN** those entries are pruned and the ledger is rewritten

### Requirement: Access-error retry, throttling, and give-up
The system SHALL distinguish an attached-but-unreadable transcript/notes doc (a per-file access error) from both an not-yet-attached transcript and a request-level missing-scope error. On a per-file access error the system SHALL mark the occurrence `deferred`, retry it no more often than once per hour, and mark it `abandoned` after a configurable maximum number of access attempts. On a request-level missing-scope error the system SHALL abort the run and instruct re-authorization without consuming any occurrence's retry budget.

#### Scenario: Unreadable doc deferred and retried hourly
- **WHEN** an occurrence's transcript doc is attached but cannot be read due to a per-file permission error
- **THEN** the occurrence is marked `deferred`, its attempt count is incremented, and it is not retried again until at least one hour has elapsed since the last attempt, regardless of a shorter poll interval

#### Scenario: Give up after max retries
- **WHEN** a `deferred` occurrence's access attempts reach the configured maximum
- **THEN** it is marked `abandoned` and no longer retried

#### Scenario: Access error surfaced once per occurrence in the menu bar
- **WHEN** an occurrence first hits a per-file access error while the menu bar app is running
- **THEN** a single modal informs the user that the transcript for that meeting could not be accessed and will be retried, and later hourly retries for the same occurrence do not re-show the modal

#### Scenario: Missing scope aborts the run without penalizing events
- **WHEN** a Drive export fails because the account token lacks the Drive scope
- **THEN** the run is aborted with a re-authorization message and no occurrence's attempt count is incremented

### Requirement: On-demand CLI ingestion
The system SHALL provide a CLI command that runs Meet-transcript ingestion once over the configured look-back window, independent of the menu bar app.

#### Scenario: Running ingestion from the CLI
- **WHEN** the user runs the Meet-transcripts ingestion command
- **THEN** eligible past occurrences are ingested, written files are logged, and a run that finds nothing to ingest reports that plainly and exits successfully
