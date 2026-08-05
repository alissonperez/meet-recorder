## Context

Transcription runs (`transcriber.transcribe`) call an STT endpoint per audio chunk (`_transcribe_chunk` in `meet_recorder/transcriber.py`), currently with a single 120s httpx timeout and zero retry — a design choice made explicitly out of scope in the original transcription change. Any failure (network blip, transient 5xx, or a hard config error like a bad API key) is caught by the menu bar app (`_transcribe_in_background`, `_recover_in_background` in `meet_recorder/menubar.py`), logged, and surfaced as a native notification. The source `.wav` is preserved, and the only recovery path today is the user noticing the notification and manually re-running the `transcribe` CLI command (`handlers.py:handler_transcribe`).

Separately, `meet_recorder/meet_ingest.py` already has a working deferred-retry pattern for a different failure mode (Google Drive access errors when exporting Meet transcript docs): `meet_recorder/ledger.py` persists per-event status (`done`/`deferred`/`abandoned`), attempt count, and last-attempt timestamp as a JSON file in the config directory, with atomic writes, a threading lock for cross-thread/process safety, and time-based pruning. This proposal reuses that mechanism instead of building a second one.

## Goals / Non-Goals

**Goals:**
- Absorb transient transcription failures (timeouts, connection errors, 5xx/429) automatically, without user intervention, via a small number of immediate retries.
- For failures unlikely to resolve on an immediate retry (auth errors, etc.), skip straight to a longer-horizon deferred retry instead of wasting the immediate-retry budget.
- Survive app restarts: a deferred transcription must still be picked up after the menu bar app is quit and relaunched (or the machine sleeps/reboots), not just while a single process is alive.
- Bound the total retry effort: give up automatically after a configurable window (default 7 days) and notify the user then, once.
- Reuse the existing ledger engine rather than introduce a second persistence mechanism, without changing Meet-ingest's current behavior or its spec.

**Non-Goals:**
- Per-chunk resumability across layer-2 retries. A deferred retry reprocesses the whole `.wav` from scratch (preprocess → chunk → transcribe → summarize → title), matching the existing "no partial output" invariant. Chunk-level resume is not implemented.
- Retrying `_generate_summary`/`_generate_title` (`_chat_completion`) failures with the same classification/backoff logic. Those already fail into the same layer-2 deferral (the whole `transcribe()` call is the retry unit), but this change does not add a separate immediate-retry layer for the chat-completion calls — only the STT request (`_transcribe_chunk`) gets layer-1 retry, per the proposal's scope. A chat-completion failure skips layer 1 (nothing to skip — it never had one) and goes straight to layer 2.
- Surfacing deferred/in-progress retry state in the menu bar UI beyond the existing transcribing-icon state. No new menu items or per-file status list.
- Changing `meet_ingest.py`'s retry semantics (interval, retention, notification behavior) — the ledger generalization must be behavior-preserving for that caller.

## Decisions

### 1. Layer 1: retry lives inside `_transcribe_chunk`, not `_transcribe_audio`
Retrying at the single-request level (inside `_transcribe_chunk`) rather than around the whole chunk loop keeps a partial success within one `transcribe()` call cheap — e.g. chunk 2 of 5 hitting a timeout doesn't force chunks 1 and 3-5 to redo work within the *same* run. (Layer 2, when it kicks in, still redoes the whole file — see Non-Goals — but layer 1 avoids unnecessary duplicate work for the common transient case.)

Retry loop: up to 3 total attempts, light backoff between attempts (e.g. 2s, then 5s — short enough not to block the background thread noticeably, long enough to ride out a brief blip). Implemented as a plain loop with `time.sleep`, no new dependency.

### 2. Error classification: retryable vs. non-retryable
`_transcribe_chunk` currently catches `httpx.HTTPError` broadly. This change classifies:
- **Retryable**: `httpx.TimeoutException` (covers connect/read/write/pool timeouts), `httpx.ConnectError`/`httpx.NetworkError`, and HTTP responses with status 429 or 5xx (via `httpx.HTTPStatusError.response.status_code`).
- **Non-retryable**: everything else raised as `httpx.HTTPError` (4xx other than 429 — e.g. 401 invalid API key, 400 bad request) and the pre-flight `TranscriptionError` from `_api_key()` (missing env var).

Non-retryable errors skip the layer-1 loop entirely (0 wasted attempts) and propagate to the caller (`transcribe()`), which routes to layer 2. This mirrors the proposal's requirement that an invalid API key doesn't burn immediate retries it can't succeed at short-term but is still deferred in case the user fixes it before the 7-day window elapses.

Alternative considered: retry-then-classify (always attempt once, inspect the error, decide whether to keep retrying). Rejected because classification is available from the exception itself before making a request — no need to spend an attempt to learn the error is non-retryable.

### 3. Layer 2 ledger: generalize `ledger.py` with a namespace + pluggable schedule
`ledger.py` today hardcodes: the ledger filename (`processed_meet.json`), the retention window (`LEDGER_RETENTION_DAYS = 2`), the retry interval (`ACCESS_RETRY_INTERVAL_HOURS = 1`, flat), and the key semantics (event id).

Generalize by:
- Adding a `namespace` parameter (or a small `Ledger` class/factory) so a second ledger — e.g. `pending_transcriptions.json` — can be created with its own filename, retention window, and schedule, while `meet_ingest.py` keeps calling with the existing namespace/filename and its existing 1-hour flat interval (behavior-preserving).
- Replacing the hardcoded `ACCESS_RETRY_INTERVAL_HOURS` check in `should_skip` with a caller-supplied **schedule function** `schedule(attempts) -> timedelta` that maps the 1-indexed attempt count to the wait before the next retry is due. Meet-ingest passes a schedule that always returns 1 hour (equivalent to today). Transcription-retry passes the graduated schedule: attempt 1 → 5min, 2 → 30min, 3 → 2h, 4 → 6h, 5+ → 24h (cap).
- The key stops being assumed to be an "event id" semantically — it's just a string key (wav path works as-is, since `str` paths are stable within a config unless the file moves).
- Retention: the transcription-retry ledger needs its own retention window ≥ the configurable max-days (default 7), since the shared `LEDGER_RETENTION_DAYS = 2` would prune a still-active deferred entry before it reaches abandonment. Retention becomes a per-namespace parameter instead of the current module constant.

Alternative considered: a second, independent module (`retry_ledger.py`) copy-pasted from `ledger.py` with the needed differences. Rejected — the user explicitly asked to generalize and reuse rather than duplicate, and the file formats/locking/atomic-write logic are identical; only the schedule and retention differ.

### 4. Abandonment and total-window semantics
"Give up after 7 days" is interpreted as: once an entry's *time since first failure* (not just since last attempt) exceeds `transcription_retry_max_days`, the next scheduled check marks it `abandoned` instead of retrying again, and the one-time notification fires. This requires tracking a `first_attempt` timestamp on the ledger entry in addition to `last_attempt` (today's `LedgerEntry` only has `status`/`attempts`; this change adds `first_attempt`). Meet-ingest's existing entries are unaffected since its abandonment logic (`attempts >= max_retries`) doesn't use `first_attempt`.

### 5. Menu bar scan timer
A new `rumps.Timer`, following the existing pattern (`_meet_poll_kickoff_timer`, `_calendar_poll_kickoff_timer`), fires at a fixed check interval (e.g. every few minutes — cheap, since it's just a ledger read; actual retries only happen when an entry's schedule says it's due) and, for each due `deferred` entry, runs `transcriber.transcribe(path)` in the same background-thread + `_begin_transcription`/`_end_transcription` pattern already used for icon state. On success: `ledger.mark_done`. On failure: reclassify (this failure also goes through layer 1 first, since it's the same `transcribe()` → `_transcribe_chunk` code path) and, if still failing, record another layer-2 attempt or abandon.

### 6. `_recover_in_background` shares the flow
Both `_transcribe_in_background` (normal stop) and `_recover_in_background` (crash recovery) call `transcriber.transcribe(path)` and handle its failure identically today (log + notify). This change extracts that shared "attempt transcription, and on failure hand off to layer 2" logic into one helper both call, so crash-recovered recordings get the same resilience as normal ones.

## Risks / Trade-offs

- **[Risk]** A wav path is used as the ledger key; if the file is renamed or moved (unlikely — the pipeline never renames the source `.wav`), the ledger entry would orphan silently. → Mitigation: non-goal to handle externally-moved files; matches the existing invariant that the source `.wav` is never renamed by the system itself. Optionally prune ledger entries whose path no longer exists on disk during a scan.
- **[Risk]** Layer 2 retries the *entire* file, including re-running `ffmpeg` preprocessing and possibly re-hitting a chat-completion call that already succeeded before an STT chunk failed later. This wastes some LLM-call cost on repeated attempts. → Mitigation: accepted per the proposal ("reprocess the entire file... simplest approach"); the alternative (persisting partial progress) is explicitly a non-goal.
- **[Risk]** Long-lived deferred entries (up to 7 days) mean `~/MeetRecordings/*.wav` files stick around unprocessed for up to a week before the user is ever notified of failure. → Mitigation: this is the explicit intent (resilience for e.g. multi-day internet outages); the existing "source `.wav` never deleted" guarantee means no data loss regardless.
- **[Trade-off]** Introducing a schedule-function parameter and namespacing to `ledger.py` adds a small amount of complexity to a previously single-purpose module. → Mitigation: kept the public API surface additive (existing `get`/`should_skip`/`mark_done`/`record_access_failure` calls from `meet_ingest.py` continue to work unchanged, or with a namespace defaulted to preserve current behavior).

## Migration Plan

- No data migration needed: `processed_meet.json` format is either left as-is or gains an unused `first_attempt` field (only meaningful for the new ledger) — existing entries continue to parse.
- New `transcription_retry_max_days` config field is optional with a default (`DEFAULT_TRANSCRIPTION_RETRY_MAX_DAYS = 7`), so existing `config.yaml` files keep working without edits.
- Rollout is a single deploy — no feature flag; this is default-on behavior once shipped, consistent with how transcription itself has no on/off switch.

## Open Questions

- Exact layer-1 backoff durations (e.g. 2s/5s) — left as an implementation detail to tune during development/testing rather than a spec-level commitment, since the spec only needs to guarantee "up to 3 attempts with backoff," not exact timings.
- Exact scan-timer check interval for layer 2 (e.g. every 5 minutes) — similarly an implementation detail; must be frequent enough to honor the 5-minute first-retry step reasonably promptly.
