## Why

Transcript and summary Markdown files are named `<timestamp> - <title-slug>.md`, so a meeting
is easy to find by name in the output folders. The recorded audio is not: `~/MeetRecordings/`
holds only `2026-07-09_14-30-00.wav` files, so finding the audio for a given meeting means
cross-referencing timestamps by hand. Since the pipeline already resolves the calendar event
for a recording, the same title can be applied to the `.wav` at save time.

## What Changes

- When a recording is merged and saved, the system resolves the matching calendar event for the
  recording's start timestamp and names the file `<timestamp> - <title-slug>.wav`, using the same
  timestamp prefix and the same slugification rules already used for transcript/summary files.
- When no calendar event matches (calendar disabled, lookup failure, or no candidate in the match
  window), the file keeps today's plain `<timestamp>.wav` name. No LLM-generated title is used at
  save time, because that would require transcribing first.
- The audio is merged to disk under its plain timestamp name *first*, and the title is then applied by an
  atomic rename in the same directory. Titling is cosmetic and must never stand between the user pressing
  Stop and the recording becoming durable, so any fault in it leaves an intact untitled recording. The
  rename completes before the path is handed to any caller, so the path is stable for the
  transcription-retry ledger which is keyed by it.
- Timestamp resolution from a recording filename parses the leading timestamp prefix instead of
  requiring the whole stem to be a timestamp, so titled filenames still yield the true start time
  rather than falling back to the file's mtime.
- Existing untitled `<timestamp>.wav` recordings continue to work unchanged; this is not a breaking
  change and no migration or renaming of existing files is performed.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `audio-capture`: the "Recording file naming" requirement gains the calendar-title slug suffix and
  the no-event fallback.
- `transcription`: timestamp resolution from a recording filename must accept a titled filename by
  parsing its timestamp prefix, and only fall back to mtime when no prefix parses.
- `test-suite`: coverage for the new naming helper and for prefix-based timestamp resolution.

## Impact

- `meet_recorder/recorder.py`: `_build_output_path` / `merge_and_cleanup` gain title resolution.
- `meet_recorder/transcriber.py`: `_resolve_timestamp` parses the timestamp prefix of the stem.
- `meet_recorder/calendar.py`: no change; `find_event` is reused (already non-fatal on failure).
- `meet_recorder/menubar.py`, `meet_recorder/handlers.py`: no change; they pass through whatever path
  `merge_and_cleanup` / `stop_recording_and_save` returns.
- `tests/`: new cases for recording filename construction and prefix timestamp parsing.
- No new dependencies (`python-slugify` is already used).
