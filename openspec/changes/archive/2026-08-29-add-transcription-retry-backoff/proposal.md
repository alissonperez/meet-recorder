## Why

Transcription failures today are terminal on the first attempt: a single retryable network hiccup (e.g. a read timeout on the STT request) fails the whole run, leaves the source `.wav` untouched, and requires the user to notice the failure notification and manually re-run the `transcribe` CLI command. This was triggered by a real occurrence — a one-off "read operation timed out" during a chunk upload — that required manual reprocessing. The original transcription design explicitly scoped out retry/backoff; this proposal adds it back in a bounded way so transient failures (a dropped connection, a brief outage) resolve themselves without manual intervention, while still failing loudly (via notification) once genuinely exhausted.

## What Changes

- Add immediate in-process retry (layer 1) to the transcription HTTP call in `_transcribe_chunk`: up to 3 attempts with a light backoff, but only for retryable errors (timeouts, connection errors, 5xx/429). Non-retryable errors (e.g. 401/invalid API key) skip straight to layer 2 instead of wasting retries. Layer 1 applies to every caller of the transcription pipeline, including the `transcribe` CLI command.
- Add deferred retry (layer 2) **in the menu bar app only** (the long-running process): when a menu-bar-initiated transcription fails, the whole `.wav` is queued for a full reprocess later and retried on a fixed hourly interval by a new periodic scan timer. The `transcribe` CLI command keeps its current terminal-failure behavior — there is no long-running process there to retry from.
- Layer 2 gives up after a configurable number of attempts (`transcription_max_retries`, default 72 — roughly 3 days at the fixed hourly interval), at which point the existing failure notification fires — exactly once, at final abandonment, not on every intermediate defer. The total retry window is *derived* from attempts × interval rather than tracked as a separate wall-clock budget.
- Guard against overlapping retries with an in-memory set of in-flight `.wav` paths, so a scan that fires while a previous attempt for the same file is still running skips it instead of transcribing it twice.
- Generalize the existing dedup/retry ledger (`meet_recorder/ledger.py`, currently hardcoded to Meet-ingest's filename, retention, and retry interval) so it can also track wav-path-keyed transcription retries, and add the enumeration accessor the periodic scan needs, without changing Meet-ingest's existing behavior.
- The crash-recovery path (`_recover_in_background`) is wired into the same layer-1/layer-2 flow as the normal stop-recording path, instead of failing immediately on any error.
- **BREAKING**: none — this is purely additive resilience around an existing failure path. The one user-visible change is timing: a menu-bar transcription that previously notified immediately on failure now notifies only once retries are exhausted.

## Capabilities

### New Capabilities
(none — this extends existing capabilities rather than introducing a new one)

### Modified Capabilities
- `transcription`: adds retryable-vs-non-retryable classification and bounded in-process retry (layer 1) around the STT request; a run whose immediate retries are exhausted (or that failed non-retryably) still fails to its caller, unchanged.
- `menubar-app`: adds a persistent deferred-retry ledger for failed transcriptions, a periodic timer that scans for due entries and reprocesses them, an in-flight guard against concurrent retries of the same file, a configurable attempt limit, and the transcription-failure notification fired exactly once at abandonment; the crash-recovery transcription path now goes through the same retry flow as the normal stop-recording path.

## Impact

- `meet_recorder/transcriber.py`: `_transcribe_chunk` gains retry-with-backoff and error classification.
- `meet_recorder/ledger.py`: generalized into a per-namespace ledger (filename, retention, retry interval) with an accessor that enumerates due deferred entries, plus pruning of entries whose keyed file no longer exists.
- `meet_recorder/meet_ingest.py`: updated only to call the generalized ledger API (no behavior change).
- `meet_recorder/transcription_retry.py` (new): the layer-2 helper — defers a failed `.wav`, lists due entries, and clears/abandons them.
- `meet_recorder/menubar.py`: new `rumps.Timer` for the deferred-retry scan; in-flight guard; `_transcribe_in_background` and `_recover_in_background` collapsed into one helper that routes failures through layer 2.
- `meet_recorder/config.py`: new `transcription_max_retries` field (bounded, like the other numeric fields); the `MAX_MEET_LOOKBACK_HOURS` comment referencing `ledger`'s module constants needs updating since those become per-namespace.
- `config.example.yaml` / `README.md`: document the new config field.
- Tests: new coverage for retry classification, ledger generalization and enumeration, deferral/abandonment, the in-flight guard, and the scan timer's notify-once-on-abandonment behavior.
