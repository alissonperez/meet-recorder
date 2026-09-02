## 1. Shared slug helper

- [x] 1.1 Extract the title slugification used by `transcriber._build_base_filename` (`slugify(title, lowercase=False)` capped at 80 chars) into a single reusable helper in a new `meet_recorder/naming.py`, returning an empty string for a title that slugifies to nothing; verify `poetry run pytest` still passes with `_build_base_filename`'s existing tests unchanged.
- [x] 1.2 Add unit tests for the helper covering a normal title, an over-length title (truncated to the cap), a title with `/`, `:` and quotes (none present in the output), and an all-punctuation title (empty result); verify the new tests pass.

## 2. Timestamp prefix parsing

- [x] 2.1 Change `transcriber._resolve_timestamp` to `strptime` the leading `FILENAME_TIMESTAMP_FORMAT`-width prefix of the filename stem instead of the whole stem, keeping the mtime fallback for a prefix that does not parse; verify by unit test that a bare-timestamp stem, a `<timestamp> - Title` stem, and an unparseable stem each resolve as the `transcription` delta spec requires.
- [x] 2.2 Confirm no other caller depends on the wav stem being a bare timestamp (`grep -rn "FILENAME_TIMESTAMP_FORMAT\|_resolve_timestamp" meet_recorder/ tests/`); record the result in the commit message if anything unexpected turns up.

## 3. Guarded rename helper

- [x] 3.1 Add a helper in `meet_recorder/naming.py` that takes a `.wav` path and a title, builds `<the stem's own leading timestamp slice> - <slug>.wav` in the same directory, and renames the file there, returning the resulting path; it must return the input path unchanged — never raise — when the slug is empty, the stem's leading slice does not parse as a timestamp, the desired name equals the current one, the destination already exists, or the rename fails. Verify by unit test against real files in a temp dir, covering each branch and asserting the file still exists and is intact in every one.
- [x] 3.2 Remove the save-time titling added earlier on this branch — `recorder._apply_meeting_title`, its call from `merge_and_cleanup`, the `calendar`/`load_config` imports it needed, and its tests — so `recorder.py` is back to naming recordings by timestamp alone and the stop path makes no network call; verify `poetry run pytest` passes and that `recorder.py` no longer references `calendar` or `load_config`.

## 4. Rename after a successful transcription

- [x] 4.1 Call the helper from `transcriber.transcribe` as the last step before returning, using the title the run actually used, and add the resulting path to the returned dict as `recording_path`; verify by unit test (transcription/summary/title calls mocked) that a bare-timestamp recording is renamed to carry the run's title slug and that the returned `recording_path` is the new path.
- [x] 4.2 Verify by unit test that the rename is skipped and no exception escapes when the run's title already matches the filename, when the title slugifies to nothing, when the filename has no parseable timestamp prefix, when the destination is taken, and when the rename itself fails — asserting in each case that the run still returns its success result and that the recording, transcript and summary are all present and intact.
- [x] 4.3 Verify by unit test that a run failing before the output files are written leaves the recording at its original path with its original name.
- [x] 4.4 Verify by unit test that both output files are already complete on disk at the moment the rename runs (e.g. have the mocked rename assert the transcript and summary exist when it is called).
- [x] 4.5 Verify by unit test that `_resolve_timestamp` on a recording renamed by a previous run still returns the prefix timestamp, so re-transcribing files it under the same `YYYY-MM` folder and timestamp as the original run.

## 5. Deferred-retry interaction

- [x] 5.1 Add a comment at `menubar._transcribe_recording`'s `transcription_retry.mark_done(path, ...)` call recording that `path` is deliberately the pre-rename path, since it is the key the ledger entry was created under; verify no code change is needed by confirming `mark_done` is reached with the same value the retry was started with.
- [x] 5.2 Add a test that a deferred retry which succeeds and renames its recording still marks the entry done under the path the retry was started with, leaving nothing a later scan could retry.
- [x] 5.3 Confirm no other caller depends on `transcribe` leaving the `.wav` path valid (`grep -rn "transcribe(" meet_recorder/`); record the result in the commit message if anything unexpected turns up.

## 6. Documentation

- [x] 6.1 Update `meet_recorder/transcription_retry.py`'s module docstring, which currently claims the recording's `.wav` path is one "which the pipeline never renames"; verify the new wording states that a successful run may rename it and that entries stay keyed by the path they were deferred under.
- [x] 6.2 Update `README.md`: the Transcription section's "never deleted, moved, or renamed by this process" sentence, and the Recording files section added earlier on this branch, so both describe the post-success rename, the fact that an untitled recording gains its title once transcription completes, and that a recording which is never transcribed keeps its bare timestamp; `docs/prompts.md` needs no change since no prompt context is affected.

## 7. Verification

- [x] 7.1 Run `poetry run pytest` and `make lint`; verify both pass clean.
- [ ] 7.2 End-to-end check with no matching calendar event: record a short session, confirm it saves as a bare `<timestamp>.wav`, let transcription finish, then confirm the `.wav` has been renamed to `<timestamp> - <Title-Slug>.wav` carrying the same title slug as the generated transcript and summary files.
- [ ] 7.3 End-to-end check with a matching calendar event: confirm the recording is saved as a bare `<timestamp>.wav` and is then renamed to the event's title after transcription.
- [ ] 7.4 End-to-end check that re-running `poetry run python main.py transcribe --path="<a renamed file>"` files its outputs under the same `YYYY-MM` folder and timestamp as the first run, and leaves the recording's name unchanged.
