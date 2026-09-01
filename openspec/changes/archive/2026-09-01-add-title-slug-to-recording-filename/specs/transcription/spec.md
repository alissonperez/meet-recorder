## MODIFIED Requirements

### Requirement: Source recording is never deleted or renamed
The system SHALL leave the source `.wav` file's contents unmodified and SHALL never delete or move it out of its directory, regardless of whether transcription succeeds or fails. The system SHALL NOT rename the source recording at any point during a transcription run, except as the final step of a fully successful run, where the recording is renamed in place to carry the meeting title, as specified in "Successful transcription renames the recording to its final title". A run that fails at any step SHALL leave the recording at exactly the path it was given.

#### Scenario: Transcription succeeds
- **WHEN** transcription and output file writing complete successfully
- **THEN** the source `.wav` file still exists in its original directory with its contents unmodified, under either its original name or the final-title name

#### Scenario: Transcription fails at any step
- **WHEN** any step of transcription (preprocessing, chunking, STT, title generation, summary generation, or file writing) fails
- **THEN** the source `.wav` file still exists at its original path, unmodified and not renamed, and can be reprocessed later

## ADDED Requirements

### Requirement: Successful transcription renames the recording to its final title
As the last step of a transcription run in which every output file was written successfully, the system SHALL rename the source recording so that it carries the same slugified meeting title its transcript and summary carry, using the same separator and slugification rules, so the audio and its transcript are findable under the same meeting name. The recording SHALL keep its own start-timestamp prefix and timestamp format; only the title portion is shared with the Markdown outputs, whose own filenames SHALL NOT change. The rename SHALL target whichever title the run actually used, whether it came from a matched calendar event or was generated from the summary.

#### Scenario: Untitled recording gains the title
- **WHEN** transcription of a recording named with a bare start timestamp completes successfully
- **THEN** the recording is renamed in its own directory to that start timestamp followed by ` - ` and the same title slug the transcript and summary use, keeping its `.wav` extension and its own timestamp format

#### Scenario: Recording already carrying the final title is left alone
- **WHEN** transcription completes successfully and the recording's filename already carries the run's title
- **THEN** no rename is performed and the recording keeps its filename

#### Scenario: Recording carrying a different title is brought in line
- **WHEN** transcription completes successfully with a title that differs from the one already in the recording's filename
- **THEN** the recording is renamed to the title the run used, so it matches the transcript and summary that were just written

#### Scenario: Output files are unaffected by the rename
- **WHEN** the recording is renamed after a successful run
- **THEN** the transcript and summary keep the names they were written under, and their contents are unchanged

### Requirement: The post-success rename never puts a recording or its outputs at risk
The system SHALL perform the rename only after every transcript and summary file has been written, and SHALL treat any failure in it as non-fatal: the failure is logged, the recording is left at its current path with its contents intact, and the run is still reported as successful, since its outputs are already written and valid. The system SHALL NOT overwrite an existing file when renaming.

#### Scenario: Rename failure does not fail the run
- **WHEN** the rename fails after the transcript and summary have been written
- **THEN** the failure is logged rather than propagated, the run is reported as successful, and the recording remains present and playable at its pre-rename path

#### Scenario: Rename never overwrites an existing file
- **WHEN** the filename the recording would be renamed to is already taken by another file
- **THEN** the rename is skipped, the recording keeps its current filename, and the existing file is left untouched

#### Scenario: A title that yields no usable slug leaves the name alone
- **WHEN** transcription completes successfully with a title that slugifies to nothing
- **THEN** no rename is performed and the recording keeps its current filename, with no trailing separator added

#### Scenario: Outputs are already written before the rename is attempted
- **WHEN** the run is interrupted at any point after the transcript and summary are written but before the recording has been renamed
- **THEN** both output files are complete on disk and the recording is complete at its pre-rename path, and re-running transcription on it produces the same outputs

### Requirement: Recording start timestamp resolved from a renamed filename
The system SHALL determine a recording's start timestamp by parsing the timestamp that prefixes the recording filename, whether or not a meeting-title suffix follows it, and SHALL fall back to the file's modification time only when no timestamp can be parsed from the prefix. This start timestamp drives calendar matching and the transcript/summary filenames, so a renamed recording must yield the same timestamp it did before the rename. The system SHALL NOT rename a recording whose filename carries no parseable timestamp prefix, so that a start time the system does not know is never asserted in a filename.

#### Scenario: Re-transcribing a renamed recording
- **WHEN** transcription is re-run on a recording that a previous successful run renamed to carry its title
- **THEN** the start timestamp is parsed from the filename's timestamp prefix, the file's modification time is not consulted, and the transcript and summary are filed under the same `YYYY-MM` folder and timestamp as the original run

#### Scenario: Untitled recording filename still works
- **WHEN** transcription runs on a recording whose filename is a bare start timestamp
- **THEN** the parsed start timestamp is used exactly as it was before, with no change in behavior

#### Scenario: Unparseable filename falls back to modification time
- **WHEN** transcription runs on a recording whose filename does not begin with a parseable timestamp
- **THEN** the start timestamp is derived from the file's modification time

#### Scenario: Recording with no parseable timestamp prefix is not renamed
- **WHEN** a transcription run completes successfully for a recording whose filename does not begin with a parseable timestamp
- **THEN** no rename is performed and the recording keeps the filename it had, rather than being given a filename built from its modification time
