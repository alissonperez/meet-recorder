## Why

Transcript and summary Markdown files are named `<timestamp> - <title-slug>.md`, so a meeting is
easy to find by name in the output folders. The recorded audio is not: `~/MeetRecordings/` holds
only `2026-07-09_14-30-00.wav` files, so finding the audio for a given meeting means
cross-referencing timestamps by hand.

## What Changes

- After a transcription completes successfully — every output file written — the system renames the
  source `.wav` to carry the same title slug its transcript and summary carry, so the audio and its
  transcript are findable under the same meeting name.
- The recording keeps its own `%Y-%m-%d_%H-%M-%S` timestamp prefix and the Markdown outputs keep
  their ISO-ish display timestamp. Only the title slug is shared, so the two filenames read as the
  same meeting without either format changing and every recording already on disk still parses.
- The title is whichever one the run actually used, whether it came from a matched calendar event or
  was generated from the summary. A recording already carrying that title is left alone.
- The rename is the last step and runs only on the success path. Any failure in it — a taken
  destination, a rename error, a title that slugifies to nothing — is logged and leaves the recording
  where it is, with the transcript and summary already written and valid. A failed transcription
  renames nothing.
- Nothing changes at save time: a recording is still written under its plain start timestamp, and the
  stop path still makes no network call. The title is applied once, at the end, when it is already
  final — rather than resolving a calendar event at save time and possibly superseding it minutes
  later with the title transcription actually used.
- Timestamp resolution from a recording filename parses the leading timestamp prefix instead of
  requiring the whole stem to be a timestamp, so a renamed recording still yields its true start time
  rather than falling back to the file's mtime.
- **BREAKING** (contract, not behavior for existing files): the guarantee that the transcription
  pipeline never renames the source recording is withdrawn and replaced by a narrower one — the
  recording is never *deleted* or modified in content, and is renamed only after a fully successful
  run. `transcription_retry.py`'s docstring, `README.md`, and the `transcription` spec all state the
  old guarantee today and must be updated together.
- Existing recordings continue to work unchanged; no migration or backfill renames anything already
  on disk.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `transcription`: the "Source recording is never deleted or renamed" requirement narrows to
  never-deleted/never-modified and gains the post-success rename, its no-op and failure fallbacks,
  and the rule that a failed run leaves the recording untouched. Timestamp resolution must accept a
  renamed filename by parsing its timestamp prefix, falling back to mtime only when none parses.
- `menubar-app`: the deferred-retry requirement gains the interaction with the rename — a retry that
  succeeds must still clear its ledger entry, which is keyed by the path as it was deferred, not by
  the post-rename path.
- `test-suite`: coverage for the slug helper, for prefix-based timestamp resolution, for the
  post-success rename step, and for a successful deferred retry that renames the recording it was
  keyed by.

`audio-capture` is deliberately **not** listed: recordings are still saved under a plain start
timestamp exactly as they are today, and `recorder.py` is not touched.

## Impact

- `meet_recorder/naming.py` *(new)*: the shared slug rule and the guarded in-directory rename.
- `meet_recorder/transcriber.py`: `_resolve_timestamp` parses the timestamp prefix of the stem;
  `transcribe` gains a final rename step after both output files are written and reports the
  recording's current path in its result.
- `meet_recorder/transcription_retry.py`: docstring only — the "which the pipeline never renames"
  claim is no longer true. The ledger itself needs no change: an entry exists only after a failure,
  and `mark_done` is called with the path the entry was created under.
- `meet_recorder/recorder.py`, `meet_recorder/menubar.py`, `meet_recorder/handlers.py`: no behavior
  change; `menubar` gains a comment on why `mark_done` keeps using the pre-rename path.
- `README.md`: the "never deleted, moved, or renamed by this process" sentence, plus a description of
  the recording filename format.
- `tests/`: new cases for the slug helper, prefix timestamp parsing, and the rename step.
- No new dependencies (`python-slugify` is already used).
