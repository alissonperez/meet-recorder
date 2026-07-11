## MODIFIED Requirements

### Requirement: Title generation
The system SHALL resolve a recording's title from a matching calendar event when one is found, and otherwise generate a short title (at most 60 characters) via a dedicated LLM chat call using the configured title model and prompt, independent of the summary generation call.

#### Scenario: Matching calendar event provides the title
- **WHEN** a calendar event matches the recording's start time
- **THEN** the event's title is used as the recording's title and the LLM title generation call is skipped

#### Scenario: No matching event, generated title fits the length limit
- **WHEN** no calendar event matches (or calendar is unconfigured) and the title generation call returns a title of 60 characters or fewer
- **THEN** that generated title is used as-is for naming output files

#### Scenario: No matching event, generated title exceeds the length limit
- **WHEN** no calendar event matches and the title generation call returns a title longer than 60 characters
- **THEN** the system retries the call up to a bounded number of attempts asking for a shorter title, and truncates to 60 characters as a final fallback if the limit is still exceeded

### Requirement: Summary generation
The system SHALL generate a structured Markdown summary of the full transcript via a dedicated LLM chat call using the configured summary model and prompt, without attributing speech to specific speakers, optionally prepending matched calendar event context (event title and attendee names) to the summary input.

#### Scenario: Summary generated without a calendar match
- **WHEN** the full transcript text is available and no calendar event matched
- **THEN** a summary is generated via a single LLM chat call from the transcript alone, unchanged from prior behavior

#### Scenario: Summary enriched with calendar context
- **WHEN** the full transcript text is available and a calendar event matched the recording
- **THEN** the event's title and attendee names are prepended to the summary user input while the summary system prompt is unchanged, and speech is still not attributed to specific speakers

## ADDED Requirements

### Requirement: Calendar enrichment is non-fatal and optional
The system SHALL treat calendar lookup during transcription as optional and non-fatal, producing identical output to the pre-calendar behavior whenever calendar is unconfigured, no event matches, or the lookup fails.

#### Scenario: Calendar lookup fails during transcription
- **WHEN** the calendar lookup raises an error or times out while transcribing
- **THEN** the failure is logged as a warning and transcription completes using the LLM-generated title and an unenriched summary, with no output files lost

### Requirement: Calendar fields in output frontmatter
The system SHALL include calendar-derived fields (source calendar, event start, event end, and attendees) in the transcript and summary frontmatter when a calendar event matched the recording, and SHALL omit those fields otherwise.

#### Scenario: Frontmatter includes calendar fields on a match
- **WHEN** a calendar event matched the recording
- **THEN** the transcript and summary frontmatter include the event's source calendar, start, end, and attendee list alongside the title

#### Scenario: Frontmatter omits calendar fields without a match
- **WHEN** no calendar event matched (or calendar is unconfigured)
- **THEN** the frontmatter contains only the fields it did before this change, with no empty calendar keys
