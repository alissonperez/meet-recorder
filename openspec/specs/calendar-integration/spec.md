# calendar-integration Specification

## Purpose
TBD - created by syncing change integrate-google-calendar. Update Purpose after archive.

## Requirements

### Requirement: Optional multi-account calendar configuration
The system SHALL read an optional Google Calendar configuration from `~/.config/meet-recorder/config.yaml` consisting of a list of logical account names and calendar-matching/ignore settings, and SHALL treat the entire calendar feature as disabled when this configuration is absent, without affecting any existing behavior.

#### Scenario: Calendar configured
- **WHEN** `config.yaml` contains a `calendars` list with one or more account names
- **THEN** those accounts are used for event lookup and (when enabled) auto-record, using the configured match window and ignore-slug list

#### Scenario: Calendar not configured
- **WHEN** `config.yaml` contains no `calendars` list
- **THEN** the config still loads and validates, transcription runs with no calendar enrichment, the auto-record scheduler is a no-op, and no calendar credentials are required

### Requirement: Config-dir credential and token storage
The system SHALL load each account's OAuth client credentials from `~/.config/meet-recorder/credentials/{account}.json` and its token from `~/.config/meet-recorder/tokens/{account}.json`, and SHALL never read or write Google calendar secrets in `.env` or in `config.yaml`.

#### Scenario: Token stored as a file in the config dir
- **WHEN** an account's token is needed for a calendar request
- **THEN** it is read from that account's token file under the config dir, not from an environment variable or from `config.yaml`

#### Scenario: Credentials or token file missing or malformed
- **WHEN** an account's credentials or token file is missing or fails to parse
- **THEN** calendar operations for that account fail non-fatally, the failure is logged as a warning, and unrelated app behavior (recording, transcription without enrichment) continues

### Requirement: One-time OAuth setup command
The system SHALL provide a CLI command that runs the interactive Google OAuth flow for a named account using the `calendar.readonly` and `drive.readonly` scopes and writes the resulting token to that account's token file with owner-only permissions. Tokens authorized before the Drive scope was added SHALL be treated as insufficient for Drive operations and require re-running this command.

#### Scenario: Authorizing an account
- **WHEN** the user runs the calendar auth command for an account whose credentials file exists
- **THEN** a browser-based OAuth flow completes granting calendar and Drive read access, and the token is written to `~/.config/meet-recorder/tokens/{account}.json` with mode 0600

#### Scenario: Pre-Drive token needs re-authorization
- **WHEN** an account's token was authorized only for `calendar.readonly` and a Drive operation is attempted
- **THEN** the Drive operation fails non-fatally with a message instructing the user to re-run the calendar auth command for that account, while calendar-only operations continue to work

### Requirement: Automatic token refresh with persistence
The system SHALL refresh an expired token that has a refresh token before making calendar requests, and SHALL persist the refreshed token back to the account's token file.

#### Scenario: Expired token is refreshed and saved
- **WHEN** an account's token is expired but carries a refresh token
- **THEN** the token is refreshed for the current requests and the refreshed token is written back to the account's token file so subsequent runs do not repeat the refresh

### Requirement: Recording-anchored event lookup
The system SHALL find the calendar event matching a recording by querying all configured accounts over a window anchored on the recording's start time, SHALL prefer events the user has accepted ("Yes") over events the user has tentatively responded to ("Maybe") or left unanswered, and SHALL return the single qualifying event whose start time is closest to the recording's start time, or none when no event qualifies.

#### Scenario: Event found within the window
- **WHEN** a recording's start time falls within the configured match window of an accepted event on any configured account
- **THEN** that event (title, description, source account, start/end, and attendee display names) is returned as the match

#### Scenario: Recording started after the meeting began
- **WHEN** a recording is started up to the configured "before" window (e.g. ~30 minutes) after an event's start time
- **THEN** that event still falls within the window and is returned as the match

#### Scenario: Closest accepted event wins across accounts
- **WHEN** multiple accepted events across one or more accounts fall within the window
- **THEN** the accepted event whose start time has the smallest absolute distance to the recording's start time is returned, regardless of which account it came from

#### Scenario: Accepted event preferred over a closer tentative event
- **WHEN** both an accepted ("Yes") event and a tentative ("Maybe") event fall within the window, and the tentative event's start time is closer to the recording's start time than the accepted event's
- **THEN** the accepted event is returned as the match, not the closer tentative event

#### Scenario: Tentative event used when no accepted event qualifies
- **WHEN** no accepted event falls within the window but one or more tentative events do
- **THEN** the tentative event whose start time is closest to the recording's start time is returned as the match

#### Scenario: No qualifying event
- **WHEN** no event survives filtering within the window, or calendar is unconfigured, or the lookup errors
- **THEN** no match is returned and the caller proceeds without calendar data

#### Scenario: Event without a description
- **WHEN** a matched event's API payload has no `description` field
- **THEN** the returned event has no description (absent, not an empty string), and callers that build prompt context from it treat it the same as an event with no attendees

### Requirement: RSVP and ignore-slug filtering
The system SHALL exclude from candidacy any event the user has declined and any event whose slugified title contains a configured ignore-slug.

#### Scenario: Declined event excluded
- **WHEN** a candidate event lists the user as an attendee with response status "declined"
- **THEN** that event is excluded from matching

#### Scenario: Ignored title excluded
- **WHEN** a candidate event's slugified title contains any entry from the configured ignore-slug list
- **THEN** that event is excluded from matching

#### Scenario: Event without attendee response accepted
- **WHEN** a candidate event has no attendee list or no explicit response for the user
- **THEN** it is not excluded on RSVP grounds and remains a candidate

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
