## MODIFIED Requirements

### Requirement: Recording file output location
The system SHALL save completed recordings as `.wav` files in the `~/MeetRecordings` directory, named using a timestamp of when the recording started, not when it was stopped or saved. When a calendar event matches the recording's start timestamp, the filename SHALL also carry a slugified form of that event's title after the timestamp, using the same separator and slugification rules the transcript and summary files use, so a recording can be identified by meeting name without cross-referencing timestamps. The captured audio SHALL be written to disk under the plain start-timestamp filename before the meeting title is resolved, and the title SHALL then be applied by renaming that file within the recordings directory, so that no failure in title resolution can affect the integrity or availability of the recording. The filename SHALL be final by the time the save operation reports the recording's path to its caller, and SHALL NOT change afterwards.

#### Scenario: Recording saved with timestamped filename
- **WHEN** a recording is stopped and saved
- **THEN** the resulting file is written under `~/MeetRecordings/` with a filename that begins with the recording's start timestamp (e.g. `2026-07-09_14-30-00`)

#### Scenario: Matched meeting title is included in the filename
- **WHEN** a recording is stopped and saved and a calendar event matches its start timestamp
- **THEN** the saved filename is the start timestamp followed by ` - ` and the slugified event title (e.g. `2026-07-09_14-30-00 - Weekly-Planning.wav`)

#### Scenario: No matching event leaves the filename untitled
- **WHEN** a recording is stopped and saved and no calendar event matches — because calendar integration is disabled, the lookup fails, or no candidate falls in the match window
- **THEN** the saved filename is the plain start timestamp with no title suffix, and the save succeeds normally

#### Scenario: Calendar lookup failure never loses a recording
- **WHEN** resolving the meeting title raises an error while the recording is being saved
- **THEN** the complete recording is already on disk under its plain start-timestamp filename, that path is reported to the caller, and the failure is logged rather than propagated

#### Scenario: Audio is durable before the title is resolved
- **WHEN** the save operation is interrupted — by a crash, a kill, or a hung calendar lookup — at any point after the captured audio has been merged but before the file has been renamed
- **THEN** a complete, playable recording remains on disk under its plain start-timestamp filename, and it transcribes normally

#### Scenario: Rename never overwrites an existing recording
- **WHEN** the titled filename a recording would be renamed to is already taken by another file
- **THEN** the rename is skipped, the recording keeps its plain start-timestamp filename, and the existing file is left untouched

#### Scenario: Long recording keeps its start-time filename
- **WHEN** a recording runs long enough that the wall-clock time at stop differs from the wall-clock time at start (e.g. by more than an hour, or across midnight)
- **THEN** the saved filename still reflects the moment the recording started, not the moment it was stopped

#### Scenario: Recovered orphan recording is named the same way
- **WHEN** an interrupted recording's temporary files are recovered and merged into a final `.wav`
- **THEN** the recovered file is named by the same rules, using the interrupted recording's original start timestamp to both name the file and resolve the meeting title

## ADDED Requirements

### Requirement: Recording filenames remain filesystem-safe
The system SHALL bound the length of the title portion of a recording filename and SHALL strip or replace characters that are unsafe in a filename, so that a long or punctuation-heavy meeting title cannot produce an unwritable path.

#### Scenario: Long title is truncated
- **WHEN** a recording is saved for an event whose title is longer than the allowed title length
- **THEN** the title portion of the filename is truncated to that limit and the file is written successfully

#### Scenario: Title with path-unsafe characters
- **WHEN** a recording is saved for an event whose title contains characters such as `/`, `:`, or quotes
- **THEN** those characters do not appear in the filename, and the file is written successfully into the recordings directory rather than into a nested or unintended path
