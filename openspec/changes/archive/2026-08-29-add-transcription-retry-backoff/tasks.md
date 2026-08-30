## 1. Ledger generalization

- [x] 1.1 Turn `meet_recorder/ledger.py`'s module-level functions into a `Ledger` object constructed with `(filename, retention_days, retry_interval_hours)`, keeping `get`/`should_skip`/`mark_done`/`record_failure` (renamed from `record_access_failure`) as methods over the existing entry shape (`status`/`attempts`/`last_attempt`)
- [x] 1.2 Expose `MEET_LEDGER = Ledger('processed_meet.json', retention_days=2, retry_interval_hours=1)` reproducing today's constants exactly, and update `meet_ingest.py`'s three call sites to use it (no behavior change)
- [x] 1.3 Add `due_keys(now)` returning every `deferred` entry whose retry interval has elapsed — the accessor the periodic scan needs, since `get`/`should_skip` are key-lookup only
- [x] 1.4 Add opt-in pruning of entries whose key is a filesystem path that no longer exists (enabled for the transcription namespace, off for Meet-ingest's event-id keys)
- [x] 1.5 Update `tests/test_ledger.py` to cover the per-namespace construction, `due_keys`, missing-path pruning, and that Meet-ingest-shaped usage (filename, 2-day retention, hourly throttle, count-based abandonment) is unaffected

## 2. Layer 1: immediate retry in the transcription request

- [x] 2.1 In `meet_recorder/transcriber.py`, classify `_transcribe_chunk`'s failures into retryable (`httpx.TimeoutException`, `httpx.NetworkError`, HTTP 429/5xx) vs. non-retryable (other 4xx, and the pre-flight `TranscriptionError` from `_api_key()`)
- [x] 2.2 Wrap the retryable path in a bounded retry loop (3 total attempts) with a light `time.sleep` backoff between attempts
- [x] 2.3 Ensure non-retryable errors propagate immediately without consuming a retry attempt
- [x] 2.4 Add/extend `tests/test_transcriber.py` covering: retry-then-succeed, retry-exhausted, and non-retryable-skips-retry, using a fake `httpx.post` that fails a controlled number of times (patch `time.sleep` so the tests stay fast)

## 3. Layer 2: deferred retry helper

- [x] 3.1 Add `transcription_max_retries` to `Config` in `meet_recorder/config.py`, defaulting to `DEFAULT_TRANSCRIPTION_MAX_RETRIES = 72` and clamped like the other numeric fields (`min(MAX_TRANSCRIPTION_MAX_RETRIES, max(1, int(...)))`)
- [x] 3.2 Update the `MAX_MEET_LOOKBACK_HOURS`/`MAX_MEET_ACCESS_RETRIES` comment in `config.py`, which cites `ledger.LEDGER_RETENTION_DAYS` / `ACCESS_RETRY_INTERVAL_HOURS` as module constants that task 1.1 makes per-namespace
- [x] 3.3 Add `meet_recorder/transcription_retry.py` building the transcription `Ledger` (`pending_transcriptions.json`, hourly interval, retention `ceil(max_retries / 24) + 1` days) from config, with `defer(path, config)`, `due_paths(config)`, and `mark_done(path, config)`; `defer` returns the resulting entry so the caller can tell `deferred` from `abandoned`
- [x] 3.4 Make the helper tolerate `config is None` (menu bar's `_load_config_safe` failure path) by falling back to the default attempt limit — `config_dir()` needs no loaded config
- [x] 3.5 Add `tests/test_transcription_retry.py` covering: deferral on failure, attempt-count progression, abandonment at `transcription_max_retries`, persistence across a re-read of the ledger file (simulated restart), and the `config is None` fallback

## 4. Menu bar integration

- [x] 4.1 Extract the shared "attempt transcription, hand off to layer 2 on failure" logic from `_transcribe_in_background` and `_recover_in_background` into one helper both call, so crash-recovered recordings get the same retry flow
- [x] 4.2 Add an in-memory set of in-flight `.wav` paths guarded by a lock; add a path before starting its thread, remove it in the thread's `finally`, and skip any due entry already in the set
- [x] 4.3 Add a new `rumps.Timer` in `meet_recorder/menubar.py`, following the existing `_meet_poll_kickoff_timer`/`_calendar_poll_kickoff_timer` pattern, that periodically scans `transcription_retry.due_paths` and runs each due retry in a background thread using the existing `_begin_transcription`/`_end_transcription` icon-state helpers
- [x] 4.4 On retry success call `transcription_retry.mark_done`; on failure call `defer` and fire `_notify('Transcription failed', ...)` only when the returned entry is `abandoned`, so no notification is shown on intermediate attempts
- [x] 4.5 Add/extend `tests/test_menubar.py` covering: normal-flow failure defers instead of notifying immediately, crash-recovery failure defers the same way, the scan retries a due entry, the scan skips an in-flight one, and abandonment notifies exactly once

## 5. Config, docs, and example files

- [x] 5.1 Document `transcription_max_retries` in `config.example.yaml` (optional, with its default and the derived ~3-day window noted)
- [x] 5.2 Update `README.md`'s transcription configuration section to mention the new optional field and the retry behavior (immediate retries everywhere; deferred retries only in the menu bar app)
- [x] 5.3 Confirm `docs/prompts.md` needs no update (this change does not alter prompt-adjacent dynamic context) and leave it as-is

## 6. Verification

- [x] 6.1 Run `openspec validate add-transcription-retry-backoff --strict`, `poetry run pytest`, and `make lint`, fixing any failures
- [x] 6.2 Manually exercise a simulated timeout (e.g. point `base_url` at an unreachable host) and confirm: 3 immediate attempts happen, the file lands in `pending_transcriptions.json` as `deferred`, no notification fires yet, and a forced scan later retries and (once reachable again) succeeds and marks the entry done
