## MODIFIED Requirements

### Requirement: One-time OAuth setup command
The system SHALL provide a CLI command that runs the interactive Google OAuth flow for a named account using the `calendar.readonly` and `drive.readonly` scopes and writes the resulting token to that account's token file with owner-only permissions. Tokens authorized before the Drive scope was added SHALL be treated as insufficient for Drive operations and require re-running this command.

#### Scenario: Authorizing an account
- **WHEN** the user runs the calendar auth command for an account whose credentials file exists
- **THEN** a browser-based OAuth flow completes granting calendar and Drive read access, and the token is written to `~/.config/meet-recorder/tokens/{account}.json` with mode 0600

#### Scenario: Pre-Drive token needs re-authorization
- **WHEN** an account's token was authorized only for `calendar.readonly` and a Drive operation is attempted
- **THEN** the Drive operation fails non-fatally with a message instructing the user to re-run the calendar auth command for that account, while calendar-only operations continue to work

## ADDED Requirements

### Requirement: Past-events lookup with attachments
The system SHALL provide a lookup that returns, across all configured accounts, the event occurrences whose end time falls within a look-back window ending at the current time, applying the same decline and ignore-slug filtering used elsewhere, and SHALL expose each returned occurrence's Google Doc attachments (title and the Drive file id recoverable from the attachment `fileUrl`).

#### Scenario: Occurrences ended within the window are returned
- **WHEN** the lookup is invoked with a look-back window
- **THEN** occurrences whose end time is within `[now - window, now]` on any configured account are returned, sorted by start time, excluding declined and ignore-slug-matched events

#### Scenario: Attachments exposed per occurrence
- **WHEN** a returned occurrence has Google Doc attachments
- **THEN** each attachment's title and Drive file id (parsed from its `fileUrl`) are available on the returned event for downstream classification

#### Scenario: Look-back lookup failure is non-fatal per account
- **WHEN** the calendar query fails for one account
- **THEN** that account is skipped with a logged warning and occurrences from other accounts are still returned
