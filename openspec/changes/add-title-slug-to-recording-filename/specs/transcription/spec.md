## ADDED Requirements

### Requirement: Recording start timestamp resolved from a titled filename
The system SHALL determine a recording's start timestamp by parsing the timestamp that prefixes the recording filename, whether or not a meeting-title suffix follows it, and SHALL fall back to the file's modification time only when no timestamp can be parsed from the prefix. This start timestamp drives calendar matching and the transcript/summary filenames, so a titled recording must yield the same timestamp an untitled one would.

#### Scenario: Titled recording filename yields the start timestamp
- **WHEN** transcription runs on a recording whose filename is a start timestamp followed by a meeting-title suffix
- **THEN** the parsed start timestamp is used for calendar matching and output naming, and the file's modification time is not consulted

#### Scenario: Untitled recording filename still works
- **WHEN** transcription runs on a recording saved before this change, whose filename is a bare start timestamp
- **THEN** the parsed start timestamp is used exactly as it was before, with no change in behavior

#### Scenario: Unparseable filename falls back to modification time
- **WHEN** transcription runs on a recording whose filename does not begin with a parseable timestamp
- **THEN** the start timestamp is derived from the file's modification time

#### Scenario: Output filenames are unaffected by the recording's own title suffix
- **WHEN** transcription runs on a titled recording and produces transcript and summary files
- **THEN** those files are named from the resolved timestamp and the title determined by the transcription pipeline, exactly as they are for an untitled recording — the recording's filename suffix is not concatenated into them
