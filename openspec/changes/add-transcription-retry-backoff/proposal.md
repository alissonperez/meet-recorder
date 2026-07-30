## Why

Transcription failures today are terminal on the first attempt: a single retryable network hiccup (e.g. a read timeout on the STT request) fails the whole run, leaves the source `.wav` untouched, and requires the user to notice the failure notification and manually re-run the `transcribe` CLI command. This was triggered by a real occurrence — a one-off "read operation timed out" during a chunk upload — that required manual reprocessing. The original transcription design explicitly scoped out retry/backoff; this proposal adds it back in a bounded way so transient failures (a dropped connection, a brief outage) resolve themselves without manual intervention, while still failing loudly (via notification) once genuinely exhausted.

## What Changes

- Add immediate in-process retry (layer 1) to the transcription HTTP call in `_transcribe_chunk`: up to 3 attempts with a light backoff, but only for retryable errors (timeouts, connection errors, 5xx/429). Non-retryable errors (e.g. 401/invalid API key) skip straight to layer 2 instead of wasting retries.
- Add deferred retry (layer 2) for when layer 1 is exhausted or bypassed: the whole `.wav` is queued for a full reprocess later, with a graduated backoff (5min → 30min → 2h → 6h → 24h cap) driven by a new periodic scan timer in the menu bar app.
- Layer 2 gives up after a configurable total window (default 7 days), at which point the existing failure notification fires — exactly once, at final abandonment, not on every intermediate defer.
- Generalize the existing dedup/retry ledger (`meet_recorder/ledger.py`, currently hardcoded to Meet-ingest's event-id keys and fixed 1-hour interval) so it can also track wav-path-keyed transcription retries with a caller-supplied backoff schedule, without changing Meet-ingest's existing behavior.
- The crash-recovery path (`_recover_in_background`) is wired into the same layer-1/layer-2 flow as the normal stop-recording path, instead of failing immediately on any error.
- **BREAKING**: none — this is purely additive resilience around an existing failure path; a transcription that previously failed immediately and required a manual CLI rerun will now retry automatically before failing, but success/failure semantics of a fully-exhausted run are unchanged.

## Capabilities

### New Capabilities
(none — this extends existing capabilities rather than introducing a new one)

### Modified Capabilities
- `transcription`: adds retryable-vs-non-retryable classification and bounded in-process retry (layer 1) around the STT request; adds deferred, backoff-scheduled reprocessing (layer 2) as an alternative to immediate terminal failure; adds a configurable total retry window.
- `menubar-app`: adds a periodic timer that scans for due deferred transcriptions and reprocesses them; changes the failure-notification requirement so a deferred transcription notifies only on final abandonment, not on every failed attempt; the crash-recovery transcription path now goes through the same retry flow as the normal stop-recording path.

## Impact

- `meet_recorder/transcriber.py`: `_transcribe_chunk` gains retry-with-backoff and error classification.
- `meet_recorder/ledger.py`: generalized to support multiple ledgers/namespaces and caller-supplied backoff schedules instead of one hardcoded event-id ledger with a fixed interval.
- `meet_recorder/meet_ingest.py`: updated only to call the generalized ledger API (no behavior change).
- `meet_recorder/menubar.py`: new `rumps.Timer` for the deferred-retry scan; `_transcribe_in_background` and `_recover_in_background` updated to route failures through layers 1/2 instead of notifying immediately.
- `meet_recorder/config.py`: new configurable field for the layer-2 total retry window (default 7 days).
- `config.example.yaml` / `README.md` / `docs/prompts.md`: document the new config field if it affects documented setup.
- Tests: new coverage for retry classification, backoff scheduling, ledger generalization, and the deferred-scan timer's notify-once-on-abandonment behavior.
