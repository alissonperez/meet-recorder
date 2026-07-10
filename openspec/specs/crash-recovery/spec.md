# crash-recovery Specification

## Purpose
Recover recordings left behind when a process (menu bar app or CLI) dies mid-recording — crash, `kill -9`, forced restart/sleep — before it can merge and clean up the mono `mic.wav`/`sys.wav` pair it was streaming to `~/MeetRecordings/.in-progress/`. Without this, such recordings are orphaned indefinitely with no cleanup or recovery path.

## Requirements

### Requirement: Boot-time orphan scan
The system SHALL scan `~/MeetRecordings/.in-progress/` for orphaned recording subdirectories once when a process starts (menu bar app launch, or the `recover` CLI command), and SHALL NOT perform this scan at any other time during that process's lifetime.

#### Scenario: Orphans found at menu bar launch
- **WHEN** the menu bar app starts and one or more subdirectories exist under `~/MeetRecordings/.in-progress/`
- **THEN** the system evaluates each subdirectory as a candidate orphan

#### Scenario: No orphans present
- **WHEN** a process starts and `~/MeetRecordings/.in-progress/` is empty or does not exist
- **THEN** no recovery prompt is shown and startup proceeds normally

### Requirement: Automatic discard of invalid orphans
The system SHALL validate each candidate orphan by attempting to open its `mic.wav` and `sys.wav` files and confirming each contains at least one audio frame, and SHALL automatically delete (without prompting the user) any orphan where either file fails to open or contains zero frames.

#### Scenario: Corrupted file discarded silently
- **WHEN** a candidate orphan's `mic.wav` or `sys.wav` cannot be opened as a valid audio file
- **THEN** that orphan's directory is deleted automatically and it is not included in any user-facing prompt

#### Scenario: Empty file discarded silently
- **WHEN** a candidate orphan's `mic.wav` or `sys.wav` opens successfully but contains zero frames
- **THEN** that orphan's directory is deleted automatically and it is not included in any user-facing prompt

#### Scenario: Valid orphan is not discarded
- **WHEN** a candidate orphan's `mic.wav` and `sys.wav` both open successfully and each contain at least one frame
- **THEN** the orphan is retained as a candidate for the user-facing prompt

### Requirement: Batched user confirmation for valid orphans
The system SHALL present exactly one confirmation prompt covering all valid orphans found in a given scan (not one prompt per orphan), offering three actions — process, ignore, delete — whose chosen action applies uniformly to every valid orphan found in that scan.

#### Scenario: Single orphan prompt
- **WHEN** exactly one valid orphan is found
- **THEN** one confirmation prompt is shown describing the pending recording and offering process/ignore/delete

#### Scenario: Multiple orphans prompt
- **WHEN** more than one valid orphan is found
- **THEN** one confirmation prompt is shown describing the count of pending recordings, and the action the user selects is applied to all of them

#### Scenario: No valid orphans, no prompt
- **WHEN** all candidate orphans were discarded automatically as invalid
- **THEN** no confirmation prompt is shown

### Requirement: Process action merges and transcribes
The system SHALL, when the user selects the process action, merge each valid orphan's `mic.wav` and `sys.wav` into a final stereo `.wav` file in `~/MeetRecordings/` using the same merge logic used by a normal recording stop, then run automatic transcription for each resulting file using the existing transcription pipeline, handling orphans one at a time in series (not concurrently).

#### Scenario: Recovered recording is merged like a normal stop
- **WHEN** the user selects "Processar" for one or more valid orphans
- **THEN** each orphan's `mic.wav`/`sys.wav` pair is merged into a stereo `.wav` file in `~/MeetRecordings/`, indistinguishable in format from a normally stopped recording

#### Scenario: Recovered recordings are transcribed automatically
- **WHEN** the user selects "Processar"
- **THEN** each merged recording is submitted to the existing transcription pipeline automatically, without requiring a separate manual step

#### Scenario: Multiple recovered recordings process in series
- **WHEN** the user selects "Processar" and more than one valid orphan exists
- **THEN** the recordings are merged and transcribed one at a time, not in parallel

#### Scenario: Successful processing removes the orphan directory
- **WHEN** an orphan has been successfully merged into its final stereo `.wav`
- **THEN** that orphan's `.in-progress/<timestamp>/` directory is removed

### Requirement: Ignore action leaves orphans untouched
The system SHALL, when the user selects the ignore action, leave every valid orphan's directory and files exactly as they are, performing no merge, transcription, or deletion.

#### Scenario: Ignore preserves files for the next scan
- **WHEN** the user selects "Ignorar"
- **THEN** all valid orphans remain in `~/MeetRecordings/.in-progress/` unchanged, and will be evaluated again as candidates the next time a boot-time scan runs

### Requirement: Delete action discards orphans without processing
The system SHALL, when the user selects the delete action, remove every valid orphan's directory (and its contents) without merging or transcribing.

#### Scenario: Delete removes pending recordings
- **WHEN** the user selects "Apagar"
- **THEN** every valid orphan's `.in-progress/<timestamp>/` directory is deleted, and no stereo `.wav` or transcription is produced for any of them

### Requirement: Menu bar recovery prompt
The system SHALL trigger the boot-time orphan scan and, if applicable, show the batched confirmation as a native macOS modal alert after the menu bar app's run loop has started (not during initialization), so the alert renders correctly.

#### Scenario: Recovery prompt appears after menu bar launch
- **WHEN** the menu bar app is launched and valid orphans are found
- **THEN** a `rumps`-based modal alert is shown to the user once the app's event loop is running, offering process/ignore/delete

### Requirement: CLI recovery entrypoint
The system SHALL expose a `recover` CLI command that runs the boot-time orphan scan and, if applicable, prompts the user for the batched process/ignore/delete decision via a terminal prompt.

#### Scenario: Running recover via CLI with pending orphans
- **WHEN** the `recover` command is invoked and one or more valid orphans exist
- **THEN** a terminal prompt describes the pending recording(s) and asks the user to choose process, ignore, or delete, then performs the chosen action

#### Scenario: Running recover via CLI with no orphans
- **WHEN** the `recover` command is invoked and no valid orphans exist
- **THEN** the command reports that there is nothing to recover and exits without prompting
