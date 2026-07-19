## 1. OAuth scope + Drive export

- [x] 1.1 Broaden `calendar.CALENDAR_SCOPES` to include `https://www.googleapis.com/auth/drive.readonly` alongside `calendar.readonly`
- [x] 1.2 Create `meet_recorder/drive.py` with `export_doc_markdown(account, file_id)` that builds a Drive `v3` service from `calendar.build_credentials(account)` and calls `files().export(fileId=file_id, mimeType='text/markdown')`, returning the text
- [x] 1.3 Add a `DriveError` (or reuse `CalendarError`) and map a missing-scope / 403 `insufficient permissions` response to a clear "re-run `calendar_auth --account <name>` to grant Drive access" message
- [x] 1.4 Add `drive.doc_id_from_url(file_url)` using `urllib.parse` to extract the id from a `/document/d/<ID>/...` URL (no regex); return `None` on non-Docs URLs
- [x] 1.5 Unit tests: `doc_id_from_url` for `drive_web`/`meet_tnfm_calendar` URLs and malformed input; export success and missing-scope error mapping (mock the Drive service)

## 2. Calendar: past-events lookup + attachment extraction

- [x] 2.1 Add `attachments` to `CalendarEvent` and populate it in `_extract_event` from the raw event `attachments` list
- [x] 2.2 Add `calendar.past_events(config, lookback_hours)` returning occurrences whose `end_dt` is within `[now - lookback_hours, now]` across all accounts, reusing `_eligible_events` and sorted by start time
- [x] 2.3 Add `classify_attachment(att)` returning `('transcript', doc_id, title_date)` / `('gemini', doc_id, None)` / `None`, keyed on the `fileUrl` `usp=` marker (`drive_web` vs `meet_tnfm_calendar`) with title as secondary signal
- [x] 2.4 Add title-date parsing for transcript attachments (`... - YYYY/MM/DD HH:MM GMT±HH:MM - Transcript[ N]`) returning the date and the trailing index
- [x] 2.5 Add `attachments_for_occurrence(event)` that returns the ordered transcript doc ids whose title date matches the occurrence start date (merging `Transcript`/`Transcript N` by index), plus the single Gemini notes doc id when exactly one is present (skip + warn if >1)
- [x] 2.6 Unit tests: past-events window filtering; recurring-accumulation case (only same-date transcripts bound); multi-segment ordering; classification by `usp=`; Gemini >1 skip

## 3. State ledger

- [x] 3.1 Create a state-ledger module over `~/.config/meet-recorder/processed_meet.json` (map keyed by occurrence event id; entry `{status, attempts, last_attempt}`), with helpers `get(event_id)`, `mark_done(event_id)`, `record_access_failure(event_id, max_retries)` (→ `deferred`/`abandoned`), and `should_skip(event_id, now)` (terminal, or `deferred` within `ACCESS_RETRY_INTERVAL_HOURS`); constants `LEDGER_RETENTION_DAYS = 2`, `ACCESS_RETRY_INTERVAL_HOURS = 1`
- [x] 3.2 Prune entries whose `last_attempt` is older than `LEDGER_RETENTION_DAYS` on each load; rewrite atomically (temp file + `os.replace`); guard access with a module-level `threading.Lock`; tolerate a missing/corrupt file
- [x] 3.3 Keep the ledger separate from `config.yaml` (app-managed state, not user config)
- [x] 3.4 Validate/clamp `lookback_hours ≤ 48h` and keep `max_access_retries × ACCESS_RETRY_INTERVAL_HOURS` well under the retention window
- [x] 3.5 Unit tests: done/deferred/abandoned transitions, hourly throttle skips a fresh `deferred`, retry after 1h, rotation drops old entries, corrupt/missing file tolerated, `lookback_hours` clamp

## 4. Config

- [x] 4.1 Add a `MeetTranscriptsConfig` (`enabled`, `poll_interval_minutes`, `lookback_hours`, `max_access_retries` default 3) mirroring `AutoRecordConfig`, absent → disabled
- [x] 4.2 Add `meet_summary_prompt` to `Config` (required only when the feature is used; provide a sensible default that permits speaker attribution)
- [x] 4.3 Document the `meet_transcripts` section (`enabled`, `poll_interval_minutes`, `lookback_hours`, `max_access_retries`) and `meet_summary_prompt` in `config.example.yaml`, including the `drive.readonly` re-auth note and the Workspace prerequisite
- [x] 4.4 Unit tests: config parsing with/without the section, defaults, clamps

## 5. Ingest orchestration

- [x] 5.1 Create `meet_recorder/meet_ingest.py::ingest_once(config, on_access_error=None)` that iterates `calendar.past_events`, skips occurrences per `ledger.should_skip`, and for each remaining occurrence resolves its transcript/Gemini doc ids
- [x] 5.2 For an occurrence with transcript doc(s): export + concatenate to a transcript Markdown; export Gemini notes when present for summary context
- [x] 5.3 For a Gemini-only occurrence: use the exported Gemini notes as the transcript body (Decision 7)
- [x] 5.4 Generate the summary via a new `transcriber` entrypoint that takes ready transcript text + optional Gemini context + `meet_summary_prompt` and reuses `_generate_summary`; title = event title
- [x] 5.5 Write transcript + summary files via `transcriber._write_markdown`/`_build_base_filename`/`_frontmatter`, timestamp = occurrence start; allow overwrite (Decision 6)
- [x] 5.6 Mark the occurrence `done` in the ledger only after both files are written; leave it unrecorded when no transcript/notes are attached yet
- [x] 5.7 Classify Drive errors: request-level missing-scope → abort the whole run with a re-auth message, no attempt counted; per-file access error → `ledger.record_access_failure` and invoke the `on_access_error(event)` callback (once per event — the ledger transition from absent/`deferred`-first-time gates it)
- [x] 5.8 Per-occurrence non-access errors are logged and do not abort the batch
- [x] 5.9 Unit tests: transcript+gemini path, transcript-only, gemini-only, nothing-available (not recorded), overwrite, `done` only on success, per-file access error → `deferred`+callback, missing-scope → run abort with no attempt counted, abandon after max retries

## 6. Transcriber reuse

- [x] 6.1 Refactor `transcriber` so summary/output can be driven from ready transcript text (extract or add an entrypoint alongside `transcribe(wav_path)`), without duplicating `_generate_summary`/`_write_markdown`/`_frontmatter`
- [x] 6.2 Thread `meet_summary_prompt` and Gemini-notes context into `_generate_summary` (extra `user_content` prefix, like `_event_context`)
- [x] 6.3 Unit tests: Meet-sourced summary uses the new prompt and includes Gemini context when provided

## 7. CLI handler

- [x] 7.1 Add `handler_meet_transcripts` (async, `@handler`) to `handlers.py` calling `meet_ingest.ingest_once`, logging each written file and a "nothing to ingest" case
- [ ] 7.2 Manually verify `poetry run python main.py meet_transcripts` produces files for a recent transcribed meeting and is idempotent on a second run
- [x] 7.3 Unit test the handler wiring (mock `ingest_once`)

## 8. Menu bar poller

- [x] 8.1 Build a `meet_transcripts` poll timer + immediate kickoff timer, started only when `meet_transcripts.enabled` and calendars are configured (mirror `_build_calendar_poll_timer`/`_run_calendar_poll_kickoff`)
- [x] 8.2 Poller callback launches a daemon thread running `ingest_once`, wrapped in the `active_transcriptions` increment / `_refresh_title` / decrement pattern so the ⏳ icon reflects ingestion
- [x] 8.3 Pass an `on_access_error(event)` callback that shows a once-per-event modal via `_show_alert` ("não foi possível acessar a transcrição de <título>; tentaremos novamente"); the run aborts + a re-auth alert on a missing-scope error
- [x] 8.4 Reuse the `_on_poll_failure` warn-then-notify-on-threshold behavior for ingest poll failures
- [x] 8.5 Log an activation summary line on startup (interval + lookback), mirroring the auto-record log
- [x] 8.6 Unit tests: poller gated off when disabled/no calendars; thread increments/decrements the counter; access-error callback shows the modal once per event; failure path

## 9. Docs

- [x] 9.1 Update `README.md`: new flow (CLI + menu bar), the `drive.readonly` re-auth requirement, the Workspace-transcription prerequisite, and the recurring-accumulation/Gemini-binding limitations
- [x] 9.2 Run `make lint` and the test suite; ensure `openspec validate ingest-meet-transcripts --strict` passes
