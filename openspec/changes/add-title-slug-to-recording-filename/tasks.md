## 1. Shared slug helper

- [x] 1.1 Extract the title slugification used by `transcriber._build_base_filename` (`slugify(title, lowercase=False)` capped at 80 chars) into a single reusable helper, returning an empty string for a title that slugifies to nothing; verify `poetry run pytest` still passes with `_build_base_filename`'s existing tests unchanged.
- [x] 1.2 Add unit tests for the helper covering a normal title, an over-length title (truncated to the cap), a title with `/`, `:` and quotes (none present in the output), and an all-punctuation title (empty result); verify the new tests pass.

## 2. Timestamp prefix parsing

- [x] 2.1 Change `transcriber._resolve_timestamp` to `strptime` the leading `FILENAME_TIMESTAMP_FORMAT`-width prefix of the filename stem instead of the whole stem, keeping the mtime fallback for a prefix that does not parse; verify by unit test that a bare-timestamp stem, a `<timestamp> - Title` stem, and an unparseable stem each resolve as the `transcription` delta spec requires.
- [x] 2.2 Confirm no other caller depends on the wav stem being a bare timestamp (`grep -rn "FILENAME_TIMESTAMP_FORMAT\|_resolve_timestamp" meet_recorder/ tests/`); record the result in the commit message if anything unexpected turns up.

## 3. Titled recording filenames

- [x] 3.1 Add a helper in `meet_recorder/recorder.py` that takes the already-merged `<timestamp>.wav` path plus the start timestamp, resolves the matching calendar event via `calendar.find_event`, renames the file to `<timestamp> - <slug>.wav`, and returns the resulting path; it must return the input path unchanged — never raise — when there is no event, the slug is empty, the destination already exists, or the lookup or rename fails. Verify by unit test against real files in a temp dir, covering each of those branches and asserting the file still exists and is intact in every one.
- [x] 3.2 Call that helper from `merge_and_cleanup` after the merge and the temp-directory cleanup, returning its result, so both `stop_recording_and_save` and the orphan-recovery paths get titled names without their own changes; verify that `handlers.py` and `menubar.py` need no edits and that `poetry run pytest` passes.
- [x] 3.3 Parse the timestamp string carried by the in-progress temp directory name into a `datetime` for the calendar lookup, degrading to the untitled path rather than raising when it does not parse; verify by unit test with a malformed temp directory name.
- [x] 3.4 Confirm the ordering guarantee holds: assert in a test that the merged file exists at the untitled path *before* the calendar lookup runs (e.g. have the mocked `find_event` assert the file is present and complete when it is called).

## 4. Verification and docs

- [x] 4.1 Run `poetry run pytest` and `make lint`; verify both pass clean.
- [ ] 4.2 End-to-end check: record a short session while a matching calendar event exists, confirm the saved file in `~/MeetRecordings/` is `<timestamp> - <Title-Slug>.wav`, then run `poetry run python main.py transcribe --path="<that file>"` and confirm the transcript/summary land under the correct `YYYY-MM` folder with the start-time timestamp (not the stop time).
- [ ] 4.3 Repeat 4.2 with calendar integration disabled and confirm the file is saved as a bare `<timestamp>.wav` and transcribes exactly as before.
- [x] 4.4 Check whether `README.md` or `docs/` documents the recording filename format and update it if so; `docs/prompts.md` needs no change since no prompt context is affected.
