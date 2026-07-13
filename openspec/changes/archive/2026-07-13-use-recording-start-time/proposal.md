## Why

The `.wav` recording filename, the calendar event lookup, and the transcript/summary filenames are all currently anchored on the moment the recording was *stopped*, not when it *started*. For a long meeting this can put the file, the matched calendar event, and the transcript/summary in the wrong hour (or even the wrong day, for a recording that crosses midnight), and can shift the event match onto a later, unrelated meeting whose start time happens to sit closer to the stop time. There is also no preference for "Yes" (accepted) RSVP events over "Maybe" (tentative) ones during matching — they compete purely on time-distance today.

## What Changes

- **BREAKING**: The saved `.wav` recording filename is now derived from the recording's start time (when `start_recording()` was called) instead of `datetime.now()` captured at stop/merge time.
- The calendar event lookup anchor continues to be "closest event start time to the recording's start," but candidate events are now tiered by the user's RSVP: accepted ("Yes") events are preferred, and tentative ("Maybe") events are only considered when no accepted event qualifies within the window.
- Transcript and summary filenames (and their `YYYY-MM` folder placement) are derived from the same recording start time, since they currently piggyback on the `.wav` filename's timestamp.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `audio-capture`: recording file output location must be named using the recording's start timestamp, not the stop timestamp.
- `calendar-integration`: recording-anchored event lookup gains RSVP-tier preference (accepted before tentative) alongside the existing closest-start-time selection.
- `transcription`: output file persistence must use the recording's start timestamp (inherited from the renamed `.wav` file) for transcript/summary filenames and month folders.

## Impact

- `meet_recorder/recorder.py`: `_build_temp_paths`/`start_recording` already capture a start timestamp (embedded in the in-progress temp dir name); `_build_output_path`/`merge_and_cleanup`/`stop_recording_and_save` need to thread that same start timestamp through instead of calling `datetime.now()` again at stop time.
- `meet_recorder/calendar.py`: `_find_event`/`_accepted_events` need an RSVP-tier pass (accepted vs. tentative) before/alongside the closest-distance selection.
- `meet_recorder/transcriber.py`: `_resolve_timestamp` already parses the timestamp from the `.wav` filename, so it inherits the fix automatically once the filename itself carries the start time — no logic change expected there, but worth verifying.
- Existing recordings/transcripts already on disk are unaffected (no migration); only newly created recordings after this change use start-time naming.
