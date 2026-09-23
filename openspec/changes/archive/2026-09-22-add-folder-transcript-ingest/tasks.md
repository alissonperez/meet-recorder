## 1. Config

- [x] 1.1 Add a `FolderIngestConfig` (`enabled`, `directories`, `poll_interval_minutes`, `max_attempts` default 3) mirroring `MeetTranscriptsConfig`, absent/empty `directories` → disabled
- [x] 1.2 Expand `~` in each configured directory path (like `transcript_dir`/`summary_dir`)
- [x] 1.3 Document the `folder_ingest` section (`enabled`, `directories`, `poll_interval_minutes`, `max_attempts`) in `config.example.yaml`, including the `processed/`/`failed/` filesystem side effects and the fixed hourly retry interval
- [x] 1.4 Unit tests: config parsing with/without the section, defaults, empty-directories-disables

## 2. Retry ledger

- [x] 2.1 Add a `folder_ingest` ledger namespace over `~/.config/meet-recorder/processed_folder_ingest.json`, built the same way `transcription_retry._ledger` sizes itself (`retention_days = ceil(max_attempts / 24) + 1`, `retry_interval_hours=1`, `prune_missing_paths=True`)
- [x] 2.2 Unit tests: deferred/abandoned transitions, hourly throttle, pruning of entries whose path no longer exists

## 3. Transcriber: extract `ingest_text`

- [x] 3.1 Extract `ingest_doc`'s post-export tail into `transcriber.ingest_text(transcript_text, config, title=None, timestamp=None)` (default `timestamp=datetime.now()` so `ingest_doc`'s behavior is unchanged); `ingest_doc` becomes a thin wrapper calling it
- [x] 3.2 Unit tests: `ingest_text` with/without a given title, with/without a given timestamp; `ingest_doc` still behaves identically to before the extraction

## 4. Folder scan + orchestration

- [x] 4.1 Create `meet_recorder/folder_ingest.py` with a directory-scan helper: top-level-only listing of a directory, filtered to `.txt`/`.md` (case-insensitive), sorted by filename; missing/unreadable directory logs a warning and yields nothing
- [x] 4.2 Add `ingest_once(config, on_failure=None)` that, for each configured directory, scans candidates, skips paths where `ledger.should_skip(path)` is true, and for the rest: reads the file as UTF-8 text, calls `transcriber.ingest_text(text, config, timestamp=<file mtime>)`
- [x] 4.3 On success: move the file into `<directory>/processed/` (creating it if needed), with a numeric-suffix fallback on a destination name collision; no ledger write
- [x] 4.4 On failure (decode error or any exception from `ingest_text`): `ledger.record_failure(path, config.folder_ingest.max_attempts)`; if the resulting status is `abandoned`, move the file into `<directory>/failed/` (creating it if needed, same collision fallback) and invoke `on_failure(path, error)` once; if `deferred`, leave the file in place and log
- [x] 4.5 Return the list of `{transcript_path, summary_path}` written this run, for CLI/menu-bar logging
- [x] 4.6 Unit tests: success moves to `processed/`; throttled-deferred file is skipped and left in place; abandonment moves to `failed/` and calls `on_failure` once; collision-suffix fallback on both `processed/` and `failed/`; missing directory doesn't abort other directories; decode error goes through the same failure path as a pipeline exception

## 5. CLI handler

- [x] 5.1 Add `handler_folder_ingest` (`@handler`) to `handlers.py` calling `folder_ingest.ingest_once`, logging each written file and a "nothing to ingest" case
- [ ] 5.2 Manually verify `poetry run python main.py folder_ingest` processes a dropped `.txt` file, moves it to `processed/`, and is a no-op on a second run
- [x] 5.3 Unit test the handler wiring (mock `ingest_once`)

## 6. Menu bar poller

- [x] 6.1 Build a `folder_ingest` poll timer + immediate kickoff timer, started only when `folder_ingest.enabled` and `directories` is non-empty (mirror `_build_meet_poll_timer`/`_run_meet_poll_kickoff`)
- [x] 6.2 Poller callback launches a daemon thread running `folder_ingest.ingest_once`, wrapped in the existing `active_transcriptions` increment/decrement pattern so the transcribing icon reflects it
- [x] 6.3 Reuse the warn-then-notify-on-threshold behavior (mirroring `_on_meet_poll_failure`) for scan-level failures
- [x] 6.4 Log an activation summary line on startup (interval + directory count), mirroring the Meet-ingestion log
- [x] 6.5 Unit tests: poller gated off when disabled/no directories; thread increments/decrements the counter; failure path notifies at the threshold

## 7. Docs

- [x] 7.1 Update `README.md`: new flow (CLI + menu bar), what `.txt`/`.md` files are picked up, the `processed/`/`failed/` side effects, and the fixed hourly retry interval for failures
- [ ] 7.2 Run `make lint` and the test suite
