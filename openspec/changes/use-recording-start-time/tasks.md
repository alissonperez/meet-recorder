## 1. Recorder: thread start timestamp into the final filename

- [x] 1.1 In `meet_recorder/recorder.py`, extract the shared timestamp format (`'%Y-%m-%d_%H-%M-%S'`) used by `_build_temp_paths` into a module-level constant so it isn't duplicated.
- [x] 1.2 Change `_build_output_path()` to accept a `timestamp` string parameter and build the output path from it, instead of calling `datetime.now()` itself.
- [x] 1.3 Change `merge_and_cleanup(mic_path, sys_path, temp_dir)` to derive the start timestamp from `os.path.basename(temp_dir)` and pass it to `_build_output_path()`.
- [x] 1.4 Update/add unit tests in `tests/test_recorder.py` asserting the final `.wav` filename matches the temp dir's start-time basename, including a case where `datetime.now()` at merge time differs from the start time (e.g. by mocking `datetime.now` to advance between start and stop).

## 2. Calendar: RSVP-tier preference in event matching

- [x] 2.1 In `meet_recorder/calendar.py`, add a helper to classify a non-declined event's RSVP tier for the current user (`accepted` vs. everything else — tentative, needsAction, or no response), based on the same `attendee.get('self')` lookup used by `_is_declined`.
- [x] 2.2 Update `_find_event` to first select the closest-start-time candidate among `accepted`-tier events within the window, falling back to the closest-start-time candidate among the remaining (non-declined, non-ignored) events only if no accepted-tier candidate exists.
- [x] 2.3 Update/add unit tests in `tests/test_calendar.py` covering: accepted-only match (existing behavior), accepted preferred over a closer tentative event, tentative used when no accepted event is in the window, and declined/ignored-slug events still excluded from both tiers.

## 3. Transcription: verify start-time inheritance

- [x] 3.1 Add/confirm a unit test in `tests/test_transcriber.py` that feeds `_resolve_timestamp` a `.wav` filename matching the new start-time format and asserts the transcript/summary filenames and month folder use that timestamp — no production code change expected here, this is a regression check that the fix in `recorder.py` is sufficient.

## 4. Crash-recovery / orphan path regression check

- [x] 4.1 Confirm (with a test in `tests/test_recorder.py` or `tests/test_handlers.py`) that `handler_recover()` (`handlers.py`) and the menubar crash-recovery flow (`menubar.py`) — both of which call `merge_and_cleanup(mic_path, sys_path, orphan_dir)` with `orphan_dir` being a `.in-progress/<timestamp>/` directory — produce a start-time-named `.wav` via the same fix from task 1.3, since both paths share `merge_and_cleanup` with no separate `datetime.now()` call of their own.

## 5. Docs

- [x] 5.1 Check `README.md` and any inline comments referencing recording filename semantics (e.g. "named using a timestamp of when the recording was made") and update wording to clarify it's the start time.
