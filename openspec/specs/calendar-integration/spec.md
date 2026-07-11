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
The system SHALL provide a CLI command that runs the interactive Google OAuth flow for a named account using the `calendar.readonly` scope and writes the resulting token to that account's token file with owner-only permissions.

#### Scenario: Authorizing an account
- **WHEN** the user runs the calendar auth command for an account whose credentials file exists
- **THEN** a browser-based OAuth flow completes and the token is written to `~/.config/meet-recorder/tokens/{account}.json` with mode 0600

### Requirement: Automatic token refresh with persistence
The system SHALL refresh an expired token that has a refresh token before making calendar requests, and SHALL persist the refreshed token back to the account's token file.

#### Scenario: Expired token is refreshed and saved
- **WHEN** an account's token is expired but carries a refresh token
- **THEN** the token is refreshed for the current requests and the refreshed token is written back to the account's token file so subsequent runs do not repeat the refresh

### Requirement: Recording-anchored event lookup
The system SHALL find the calendar event matching a recording by querying all configured accounts over a window anchored on the recording's start time, and SHALL return the single event whose start time is closest to the recording's start time, or none when no event qualifies.

#### Scenario: Event found within the window
- **WHEN** a recording's start time falls within the configured match window of an accepted event on any configured account
- **THEN** that event (title, source account, start/end, and attendee display names) is returned as the match

#### Scenario: Recording started after the meeting began
- **WHEN** a recording is started up to the configured "before" window (e.g. ~30 minutes) after an event's start time
- **THEN** that event still falls within the window and is returned as the match

#### Scenario: Closest event wins across accounts
- **WHEN** multiple accepted events across one or more accounts fall within the window
- **THEN** the event whose start time has the smallest absolute distance to the recording's start time is returned, regardless of which account it came from

#### Scenario: No qualifying event
- **WHEN** no event survives filtering within the window, or calendar is unconfigured, or the lookup errors
- **THEN** no match is returned and the caller proceeds without calendar data

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
