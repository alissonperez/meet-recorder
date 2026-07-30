## 1. Ledger generalization

- [ ] 1.1 Add a `namespace` (filename) parameter to `ledger.py`'s path/read/write helpers so more than one ledger file can exist under the config directory, defaulting to the current `processed_meet.json` behavior for existing callers
- [ ] 1.2 Replace the hardcoded `ACCESS_RETRY_INTERVAL_HOURS` check in `should_skip` with a caller-supplied `schedule(attempts) -> timedelta` function; update `meet_ingest.py`'s call site to pass a schedule equivalent to the current fixed 1-hour interval (no behavior change)
- [ ] 1.3 Make the retention window (`LEDGER_RETENTION_DAYS`) a per-namespace parameter instead of a single module constant
- [ ] 1.4 Add a `first_attempt` timestamp to ledger entries (alongside existing `last_attempt`), set on the first failure and preserved across subsequent `record_access_failure`-equivalent calls
- [ ] 1.5 Update/extend `tests/test_ledger.py` to cover namespacing, pluggable schedules, per-namespace retention, and `first_attempt` tracking, while confirming existing Meet-ingest-shaped usage is unaffected

## 2. Layer 1: immediate retry in the transcription request

- [ ] 2.1 In `meet_recorder/transcriber.py`, classify `_transcribe_chunk`'s `httpx` failures into retryable (timeout, connection error, 429/5xx) vs. non-retryable (other 4xx, missing API key)
- [ ] 2.2 Wrap the retryable path in a bounded retry loop (3 total attempts) with a light backoff between attempts
- [ ] 2.3 Ensure non-retryable errors propagate immediately without consuming a retry attempt
- [ ] 2.4 Add/extend `tests/test_transcriber.py` covering: retry-then-succeed, retry-exhausted, and non-retryable-skips-retry, using a fake `httpx.post` that fails a controlled number of times

## 3. Layer 2: deferred retry via the generalized ledger

- [ ] 3.1 Add a `transcription_retry_max_days` field to `Config` in `meet_recorder/config.py`, defaulting to `DEFAULT_TRANSCRIPTION_RETRY_MAX_DAYS = 7`
- [ ] 3.2 Define the graduated backoff schedule (5min → 30min → 2h → 6h → 24h cap) as the schedule function passed to the transcription-retry ledger namespace
- [ ] 3.3 Add a helper (e.g. in `transcriber.py` or a new small module) that: attempts `transcriber.transcribe(path)`, and on failure records/updates a `pending_transcriptions.json` ledger entry keyed by the wav path instead of raising to the caller as a terminal failure
- [ ] 3.4 Implement abandonment: when an entry's time-since-`first_attempt` exceeds `transcription_retry_max_days`, mark it abandoned instead of scheduling another retry
- [ ] 3.5 Add/extend tests covering: deferral on exhausted/non-retryable failure, schedule progression, persistence across a simulated restart (re-reading the ledger file), and abandonment after the configured window

## 4. Menu bar integration

- [ ] 4.1 Add a new `rumps.Timer` in `meet_recorder/menubar.py`, following the existing `_meet_poll_kickoff_timer`/`_calendar_poll_kickoff_timer` pattern, that periodically scans the transcription-retry ledger for due entries
- [ ] 4.2 For each due entry, run the retry in a background thread using the existing `_begin_transcription`/`_end_transcription` icon-state helpers
- [ ] 4.3 On the helper's success, clear the ledger entry (already handled by 3.3/3.4 if the helper owns ledger writes); on abandonment, fire the existing `_notify('Transcription failed', ...)` exactly once
- [ ] 4.4 Extract the shared "attempt transcription, hand off to layer 2 on failure" logic from `_transcribe_in_background` and `_recover_in_background` into one helper both call, so crash-recovered recordings get the same retry flow
- [ ] 4.5 Add/extend `tests/test_menubar.py` covering: normal-flow failure defers instead of notifying immediately, crash-recovery failure defers the same way, and the scan timer retries a due entry

## 5. Config, docs, and example files

- [ ] 5.1 Document `transcription_retry_max_days` in `config.example.yaml` (as optional, with its default noted)
- [ ] 5.2 Update `README.md`'s transcription configuration section to mention the new optional field
- [ ] 5.3 Check whether `docs/prompts.md` needs updates (only if this change alters prompt-adjacent dynamic context — expected: no changes needed, confirm and leave as-is)

## 6. Verification

- [ ] 6.1 Run `poetry run pytest` and `make lint`, fix any failures
- [ ] 6.2 Manually exercise a simulated timeout (e.g. point `base_url` at an unreachable host) and confirm: 3 immediate attempts happen, the file lands in the deferred ledger, no notification fires yet, and a forced scan later retries and (once reachable again) succeeds and clears the entry
