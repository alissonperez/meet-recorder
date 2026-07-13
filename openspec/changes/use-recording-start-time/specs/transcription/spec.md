## MODIFIED Requirements

### Requirement: Output file persistence
The system SHALL write the full transcript and the generated summary as two separate Markdown files, named using the recording's start timestamp and a slugified version of the generated title, organized under the configured output directories in per-month subfolders.

#### Scenario: Both output files are written on success
- **WHEN** transcription and summary generation both complete successfully
- **THEN** a transcript file is written to `transcript_dir/YYYY-MM/TIMESTAMP - Title-Slug.md` and a summary file is written to `summary_dir/YYYY-MM/TIMESTAMP - Title-Slug.md`, where `YYYY-MM` and `TIMESTAMP` are derived from the recording's start timestamp

#### Scenario: Long recording keeps its start-time filename
- **WHEN** a recording ran long enough that its start and stop fall in different months (or different days)
- **THEN** the transcript and summary are still filed under the `YYYY-MM` folder and `TIMESTAMP` matching when the recording started, not when it stopped
