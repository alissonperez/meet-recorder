## Context

Transcription runs (`transcriber.transcribe`) call an STT endpoint per audio chunk (`_transcribe_chunk` in `meet_recorder/transcriber.py`), currently with a single 120s httpx timeout and zero retry — a design choice made explicitly out of scope in the original transcription change. Any failure (network blip, transient 5xx, or a hard config error like a bad API key) is caught by the menu bar app (`_transcribe_in_background`, `_recover_in_background` in `meet_recorder/menubar.py`), logged, and surfaced as a native notification. The source `.wav` is preserved, and the only recovery path today is the user noticing the notification and manually re-running the `transcribe` CLI command (`handlers.py:handler_transcribe`).

Separately, `meet_recorder/meet_ingest.py` already has a working deferred-retry pattern for a different failure mode (Google Drive access errors when exporting Meet transcript docs): `meet_recorder/ledger.py` persists per-event status (`done`/`deferred`/`abandoned`), attempt count, and last-attempt timestamp as a JSON file in the config directory, with atomic writes, a threading lock for cross-thread/process safety, and time-based pruning. It retries on a fixed hourly interval and abandons after `max_access_retries` attempts. This proposal reuses that mechanism — including its counting semantics — instead of building a second one.

## Goals / Non-Goals

**Goals:**
- Absorb transient transcription failures (timeouts, connection errors, 5xx/429) automatically, without user intervention, via a small number of immediate retries.
- For failures unlikely to resolve on an immediate retry (auth errors, etc.), skip straight to a longer-horizon deferred retry instead of wasting the immediate-retry budget.
- Survive app restarts: a deferred transcription must still be picked up after the menu bar app is quit and relaunched (or the machine sleeps/reboots), not just while a single process is alive.
- Bound the total retry effort by a configurable **attempt count**, and notify the user once, when that count is exhausted.
- Reuse the existing ledger engine rather than introduce a second persistence mechanism, without changing Meet-ingest's current behavior or its spec.

**Non-Goals:**
- Deferred retry for the `transcribe` CLI command. Layer 2 needs a long-running process to fire its scan timer; the CLI has none, so a CLI run that exhausts layer 1 still fails terminally, exactly as today (Decision 6).
- Per-chunk resumability across layer-2 retries. A deferred retry reprocesses the whole `.wav` from scratch (preprocess → chunk → transcribe → summarize → title), matching the existing "no partial output" invariant. Chunk-level resume is not implemented.
- Retrying `_generate_summary`/`_generate_title` (`_chat_completion`) failures with the same classification/backoff logic. Those already fail into the same layer-2 deferral (the whole `transcribe()` call is the retry unit), but this change does not add a separate immediate-retry layer for the chat-completion calls — only the STT request (`_transcribe_chunk`) gets layer-1 retry. A chat-completion failure skips layer 1 (nothing to skip — it never had one) and goes straight to layer 2.
- A wall-clock retry budget. The total retry window is derived (`attempts × 1h`), never measured against a first-failure timestamp (Decision 4).
- Surfacing deferred/in-progress retry state in the menu bar UI beyond the existing transcribing-icon state. No new menu items or per-file status list.
- Changing `meet_ingest.py`'s retry semantics (interval, retention, notification behavior) — the ledger generalization must be behavior-preserving for that caller.

## Decisions

### 1. Layer 1: retry lives inside `_transcribe_chunk`, not `_transcribe_audio`
Retrying at the single-request level (inside `_transcribe_chunk`) rather than around the whole chunk loop keeps a partial success within one `transcribe()` call cheap — e.g. chunk 2 of 5 hitting a timeout doesn't force chunks 1 and 3-5 to redo work within the *same* run. (Layer 2, when it kicks in, still redoes the whole file — see Non-Goals — but layer 1 avoids unnecessary duplicate work for the common transient case.)

Retry loop: up to 3 total attempts, light backoff between attempts (e.g. 2s, then 5s — short enough not to block the background thread noticeably, long enough to ride out a brief blip). Implemented as a plain loop with `time.sleep`, no new dependency. Worst case a single chunk now takes ~3 × the 120s timeout plus backoff before failing; acceptable for a background thread.

### 2. Error classification: retryable vs. non-retryable
`_transcribe_chunk` currently catches `httpx.HTTPError` broadly. This change classifies:
- **Retryable**: `httpx.TimeoutException` (covers connect/read/write/pool timeouts), `httpx.NetworkError` (`ConnectError`/`ReadError`/`WriteError`/`CloseError`), and HTTP responses with status 429 or 5xx (via `httpx.HTTPStatusError.response.status_code`).
- **Non-retryable**: everything else raised as `httpx.HTTPError` (4xx other than 429 — e.g. 401 invalid API key, 400 bad request) and the pre-flight `TranscriptionError` from `_api_key()` (missing env var, raised before any request is made).

Non-retryable errors skip the layer-1 loop entirely (0 wasted attempts) and propagate to the caller (`transcribe()`), which — in the menu bar app — routes to layer 2. This mirrors the requirement that an invalid API key doesn't burn immediate retries it can't succeed at short-term but is still deferred in case the user fixes it before the attempt budget elapses.

Alternative considered: retry-then-classify (always attempt once, inspect the error, decide whether to keep retrying). Rejected because classification is available from the exception itself before making a request — no need to spend an attempt to learn the error is non-retryable.

### 3. Layer 2 ledger: generalize `ledger.py` into a per-namespace `Ledger`
`ledger.py` today hardcodes: the ledger filename (`processed_meet.json`), the retention window (`LEDGER_RETENTION_DAYS = 2`), the retry interval (`ACCESS_RETRY_INTERVAL_HOURS = 1`, flat), and the key semantics (event id).

Generalize into a small `Ledger` object constructed with `(filename, retention_days, retry_interval_hours)`, exposing the existing operations as methods:
- `MEET_LEDGER = Ledger('processed_meet.json', retention_days=2, retry_interval_hours=1)` reproduces today's behavior exactly; `meet_ingest.py` is updated to call through it (three call sites, no semantic change).
- The transcription-retry ledger is `Ledger('pending_transcriptions.json', retention_days=..., retry_interval_hours=1)`, built from config (see retention below).
- The key stops being assumed to be an "event id" semantically — it's just a string key. `record_access_failure` becomes `record_failure`; the wav path is the key (stable, since the pipeline never renames the source `.wav`).
- Both callers retry on the same flat hourly interval, so `should_skip`'s throttle check takes the interval from the instance rather than a module constant. **No schedule function and no graduated backoff**: a caller-supplied `schedule(attempts)` callable was considered and dropped — with both namespaces on a flat 1h interval it would be unused generality.
- **New**: `due_keys(now)` enumerating every `deferred` entry whose throttle interval has elapsed. `get`/`should_skip` are key-lookup only, so the periodic scan cannot work without this; it is the one genuinely new operation the ledger needs.
- **New**: entries whose key is a filesystem path that no longer exists are pruned during a scan, so a user deleting a failed `.wav` ends the retry loop instead of burning the full attempt budget. Opt-in per namespace (Meet-ingest's event-id keys are not paths).

Retention: pruning keys off `last_attempt`, which the hourly retry keeps fresh, so an actively-retried entry never prunes mid-flight. The risk is an *inactive* window — the app quit over a long weekend — pruning a still-live entry. The transcription namespace therefore takes a retention window comfortably wider than its maximum retry span: `ceil(transcription_max_retries / 24) + 1` days. Meet-ingest keeps 2 days.

Alternative considered: a second, independent module (`retry_ledger.py`) copy-pasted from `ledger.py`. Rejected — the file format, locking, and atomic-write logic are identical; only the filename, retention, and (now) the path-pruning flag differ.

### 4. Abandonment is counted, not timed
"Give up after a few days" is implemented purely as an attempt count: `record_failure(key, max_retries)` increments `attempts` and returns `abandoned` once `attempts >= max_retries`, exactly as Meet-ingest already does. With the fixed 1-hour interval, `transcription_max_retries` *is* the retry window in hours — the default of 72 is ~3 days — so no `first_attempt` timestamp and no wall-clock comparison are introduced. The ledger entry shape is unchanged, which also means no migration concern for `processed_meet.json`.

Alternative considered: a `transcription_retry_max_days` wall-clock budget measured from the first failure. Rejected — it needs a new `first_attempt` field on every entry and a second abandonment rule alongside the count-based one that Meet-ingest already relies on, for no behavioral gain over `attempts × interval`.

### 5. Menu bar scan timer and the in-flight guard
A new `rumps.Timer`, following the existing pattern (`_meet_poll_kickoff_timer`, `_calendar_poll_kickoff_timer`), fires every few minutes — cheap, since it's just a ledger read; actual retries only happen for entries `due_keys` returns — and for each due entry runs `asyncio.run(transcriber.transcribe(path))` in the same background-thread + `_begin_transcription`/`_end_transcription` pattern already used for icon state. On success: `mark_done`. On failure: `record_failure`, and if it comes back `abandoned`, notify once.

A full retry (ffmpeg preprocess + N chunks × up to 3 × 120s + two chat completions) can outlast the scan interval, so the app keeps an in-memory `set` of in-flight wav paths guarded by a lock. A due entry already in that set is skipped by the scan; the path is added before the thread starts and removed in the thread's `finally`. The set covers the just-failed normal/crash-recovery run too, so a scan cannot pick a file back up while its original attempt is still unwinding. In-memory is sufficient: after a restart nothing is in flight by definition, and the ledger's `last_attempt` throttle keeps a restarted app from immediately re-running an entry attempted moments before the crash.

### 6. Layer 2 is menu-bar-only; the CLI keeps failing terminally
Layer 2 needs a process that outlives the failed run to fire its scan timer. `handler_transcribe` exits as soon as `transcribe()` returns, so deferring from the CLI would write a ledger entry nothing ever picks up (until, coincidentally, the menu bar app happened to be running and scanned it — surprising behavior, and it would silently swallow a CLI failure the user is watching for at the terminal). So the deferral requirements live in the `menubar-app` capability, not `transcription`: `transcriber.transcribe` keeps raising on failure, the menu bar app is what catches and defers. Layer 1 is inside `transcribe` and therefore benefits the CLI too.

The helper itself lives in a new `meet_recorder/transcription_retry.py` (`defer`, `due_paths`, `mark_done`) so `menubar.py` stays thin and the logic is unit-testable without rumps. When `self.config` failed to load (`_load_config_safe` returned `None`), the helper falls back to the default attempt limit — `config_dir()` needs no loaded config, so deferral still works.

### 7. `_recover_in_background` shares the flow
Both `_transcribe_in_background` (normal stop) and `_recover_in_background` (crash recovery) call `transcriber.transcribe(path)` and handle its failure identically today (log + notify). This change extracts that shared "attempt transcription, and on failure hand off to layer 2" logic into one helper both call, so crash-recovered recordings get the same resilience as normal ones.

## Risks / Trade-offs

- **[Risk]** A wav path is used as the ledger key; if the file is renamed or moved (unlikely — the pipeline never renames the source `.wav`), the ledger entry would orphan. → Mitigation: path-existence pruning during a scan (Decision 3) drops the entry instead of retrying a missing file for days.
- **[Risk]** Layer 2 retries the *entire* file, including re-running `ffmpeg` preprocessing and possibly re-hitting a chat-completion call that already succeeded before an STT chunk failed later. This wastes some LLM-call cost on repeated attempts. → Mitigation: accepted; the alternative (persisting partial progress) is explicitly a non-goal. The attempt cap bounds the total waste, and the in-flight guard prevents the worst case of two concurrent retries of the same file.
- **[Risk]** With the default 72 attempts, a permanently-failing recording stays silent for ~3 days before the user is notified. → Mitigation: this is the explicit intent (resilience across multi-day outages), the limit is configurable downward, and the existing "source `.wav` is never deleted" guarantee means no data loss regardless.
- **[Risk]** The user-visible failure notification now arrives ~3 days late instead of immediately, which is a behavior change for the normal stop-recording flow. → Mitigation: intentional per the proposal; failures that would previously have needed a manual CLI rerun now mostly self-heal within the first hour or two.
- **[Trade-off]** Turning `ledger.py`'s module-level functions into a `Ledger` object touches every Meet-ingest call site for no Meet-ingest benefit. → Mitigation: three call sites, all mechanical, covered by the existing `tests/test_meet_ingest.py`; the alternative (threading three extra parameters through every module-level function) is worse at each call site.

## Migration Plan

- No data migration: the ledger entry shape (`status`/`attempts`/`last_attempt`) is unchanged, and `processed_meet.json` keeps its filename, retention, and interval. The new namespace starts empty.
- New `transcription_max_retries` config field is optional with a default (`DEFAULT_TRANSCRIPTION_MAX_RETRIES = 72`) and clamped like the other numeric fields, so existing `config.yaml` files keep working without edits.
- Rollout is a single deploy — no feature flag; this is default-on behavior once shipped, consistent with how transcription itself has no on/off switch.

## Open Questions

- Exact layer-1 backoff durations (e.g. 2s/5s) — left as an implementation detail to tune during development/testing rather than a spec-level commitment, since the spec only needs to guarantee "up to 3 attempts with backoff," not exact timings.
- Exact scan-timer check interval for layer 2 (e.g. every 5 minutes) — similarly an implementation detail; it only needs to be well under the 1-hour retry interval.
