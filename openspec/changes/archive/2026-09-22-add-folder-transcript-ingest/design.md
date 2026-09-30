## Context

`meet_recorder/transcriber.py` already has two ways to reach the standard
transcript + summary output layer: `transcribe(wav_path)` (from a
recording) and `ingest_doc(url, config, account, title=None)` (from a
standalone Google Doc, e.g. for an interview the user didn't attend — no
calendar event, so the title is either passed in or LLM-generated). Both
write through the same `_generate_summary`/`_write_markdown`/`_frontmatter`
helpers.

Separately, `meet_recorder/meet_ingest.py` established the app's pattern
for an opt-in, config-gated, periodic ingestion flow that runs both on
demand (CLI handler) and in the background (a menu bar `rumps.Timer` +
daemon thread, mirroring `autorecord`), backed by a persistent
`ledger.Ledger` for dedup/retry state, with a companion
`transcription_retry.py` showing the same `Ledger` used path-keyed
(`prune_missing_paths=True`) for a different kind of retry.

This change is the local-filesystem sibling of `meet_transcripts`: instead
of polling a calendar for Drive-attached transcripts, it polls one or more
directories for text files already sitting on disk, and pushes each
through the exact same standard pipe `ingest_doc` already uses.

## Goals / Non-Goals

**Goals:**
- Let the user register one or more local directories; periodically pick
  up new `.txt`/`.md` files dropped there and run each through the same
  transcript + summary output the rest of the app produces.
- Avoid reprocessing without a fragile in-memory or content-hash scheme:
  a processed file is moved out of the watched root, so the next scan
  simply never sees it again.
- Bound and eventually give up on a file that keeps failing (a stuck file
  must not block the ones after it, or poll forever).
- Reuse the standard-pipe tail (`ingest_doc`'s summary/title/output logic)
  rather than re-implementing it.
- Survive restarts via a persistent, ledger-backed retry state, consistent
  with every other poller in the app.

**Non-Goals:**
- Recursive subdirectory scanning. Root-level only for this change; a user
  who wants a nested directory watched registers it explicitly. (This also
  sidesteps ever having to filter the app's own `processed/`/`failed/`
  subdirectories out of a recursive walk.)
- OS-level file-system watching (inotify/FSEvents/watchdog). This reuses
  the existing timer-based polling model already used everywhere else in
  the app, not a new dependency or mechanism.
- Configurable file extensions/glob patterns. Fixed to `.txt`/`.md` for
  this change.
- Any interactive per-file override (title, prompt, account). This is a
  batch/unattended flow; there's no one to prompt. Matches `ingest_doc`'s
  no-title-given code path (LLM-generated title).
- Content-based dedup (hashing) — the move-to-`processed/` step is the
  dedup mechanism; a file is picked up at most once, full stop.

## Decisions

### 1. Directory scan: root-level only, files matching `.txt`/`.md`
Each configured directory is listed with `os.scandir`/`os.listdir` at its
top level only, filtering to regular files with a `.txt` or `.md`
extension (case-insensitive), sorted by filename for deterministic,
testable ordering. Non-recursive by design (see Non-Goals) — this also
means the `processed/`/`failed/` subdirectories the app creates inside the
same directory are never themselves scanned, with no extra exclusion logic
required.

### 2. Move-based idempotency: `processed/`/`failed/` subdirectories, created inside the watched directory
On success, the source file is moved (`shutil.move`, not copy+delete, for
an atomic same-filesystem rename) into `<directory>/processed/`. On final
failure (attempts exhausted), it is moved into `<directory>/failed/`.
Rationale:
- No extra "output directory" setting is needed — the destination is
  always relative to where the file was found, mirroring how
  `transcript_dir`/`summary_dir` are laid out in `YYYY-MM/` subfolders
  relative to a single configured root.
- It's visible and inspectable in the filesystem: the user can see at a
  glance what's pending (root), done (`processed/`), or stuck
  (`failed/`), without needing to read a ledger file.
- Combined with Decision 1 (non-recursive scan), the move alone is a
  complete dedup mechanism for the success path — **no ledger entry is
  written for a successfully processed file at all**. Only failures need
  persistent state (Decision 4), which keeps the ledger small and its
  purpose narrow: "what's currently retrying."
- Both subdirectories are created lazily (`os.makedirs(..., exist_ok=True)`)
  only when first needed, so an all-success run never creates `failed/`.

### 3. Filename collision on move: disambiguating suffix
If the destination path in `processed/` or `failed/` already exists (e.g.
the same filename was dropped, processed, and dropped again later), the
move appends `-1`, `-2`, ... before the extension until it finds a free
name, rather than overwriting (a silent overwrite could destroy an
existing processed file's paper trail) or skipping the move (which would
leave the file in the watched root and cause it to be rescanned every poll
indefinitely — a livelock, since Decision 2 relies on the move itself to
stop rescanning).

### 4. Failure ledger: keyed by absolute file path, reuses `ledger.Ledger`
A new namespace, `Ledger('processed_folder_ingest.json', retention_days=...,
retry_interval_hours=1, prune_missing_paths=True)`, built the same way
`transcription_retry._ledger(config)` sizes its own: `retention_days =
ceil(max_attempts / 24) + 1`, since the retry loop is a fixed hourly
interval regardless of the configured poll interval (a short
`poll_interval_minutes` must not make a failing file retry faster than
once an hour — consistent with every other retry ledger in this app).
`prune_missing_paths=True` because a path leaves the ledger's relevant
universe the moment it's moved to `processed/`/`failed/` (or deleted by
the user) — there is nothing further to retry for a path that no longer
exists at its original location.

Per-scan flow for a candidate file (mirrors `meet_ingest.ingest_once`'s use
of `ledger.MEET_LEDGER.should_skip`):
- `ledger.should_skip(path)` — true for a terminal `abandoned` entry (which
  shouldn't exist for long, since abandonment triggers the move in
  Decision 2, but the check stays as the same defensive pattern the Meet
  ledger uses) or a `deferred` entry not yet due for retry. Skip the file
  this scan.
- Otherwise, attempt ingestion. On success: move to `processed/`, no
  ledger write. On failure: `ledger.record_failure(path, max_attempts)`;
  if the resulting status is `abandoned`, move the file to `failed/` and
  log/notify (mirroring the Meet ledger's "notify once, on the failure
  that crosses the threshold" shape); if `deferred`, leave the file in
  place for a later, throttled retry.

### 5. Timestamp: file mtime, not "now"
`ingest_doc` timestamps its output with `datetime.now()` because it's an
ad hoc, user-triggered, right-now action. A folder-ingest file is
different: it can sit in the watched directory for a while before a poll
picks it up (the app was off, `poll_interval_minutes` is long, the file
was dropped hours ago). The file's mtime is a materially better proxy for
when the underlying meeting/notes actually happened, and this repo already
treats mtime as its fallback signal for "when did this actually start"
(`transcriber._resolve_timestamp` falls back to `os.path.getmtime` for a
recording with no parseable timestamp in its filename). `ingest_text`
therefore takes an optional `timestamp` parameter (default `datetime.now()`
so `ingest_doc`'s behavior is unchanged), and folder ingest always passes
the file's mtime explicitly.

### 6. Title & summary: reuse `ingest_doc`'s standard pipe unmodified
No new prompt is introduced. Summary uses the existing `summary_prompt`
(not the speaker-aware `meet_summary_prompt` — these are plain notes/
transcripts of unknown provenance, not guaranteed to carry Meet-style
speaker labels), and the title is always LLM-generated via `title_prompt`
(there is no per-file title input in an unattended scan — same code path
`ingest_doc` already takes when its own `title` argument is omitted).

### 7. Read/decode errors are just another failure
A file that fails to decode as UTF-8 text, or is empty, is treated as an
ordinary per-file failure through the same retry ledger (Decision 4) —
not a special-cased immediate move to `failed/`. This keeps the failure
handling to one path, and gives a fixable case (e.g. the user re-saves the
file with a different encoding, or simply removes a stray non-text file)
a chance to resolve itself before the file is finally parked in `failed/`.

### 8. `transcriber.ingest_text` extraction
`ingest_doc`'s current tail (everything after the Drive export) becomes a
new function:

```python
def ingest_text(transcript_text, config, title=None, timestamp=None):
    '''Run already-available transcript text through the standard
    summary/title/output pipeline (no calendar event, no audio).'''
    summary_text = _generate_summary(transcript_text, config)
    resolved_title = title or _generate_title(summary_text, config)
    ts = timestamp or datetime.now()
    transcript_path = _write_markdown(
        config.transcript_dir, ts, _build_base_filename(ts, resolved_title),
        _transcript_markdown(resolved_title, transcript_text),
    )
    summary_path = _write_markdown(
        config.summary_dir, ts, _build_base_filename(ts, resolved_title, suffix='RESUMO'),
        _summary_markdown(resolved_title, summary_text),
    )
    return {'transcript_path': transcript_path, 'summary_path': summary_path}


def ingest_doc(url, config, account, title=None):
    doc_id = drive.doc_id_from_url(url)
    if doc_id is None:
        raise TranscriptionError(f'Could not extract a Google Doc id from URL: {url}')
    transcript_text = drive.export_doc_markdown(account, doc_id)
    return ingest_text(transcript_text, config, title=title)
```

This removes duplication instead of adding a third parallel
implementation, and `ingest_doc`'s existing behavior (including its
`TranscriptionError`/`DriveError` handling in `handlers.py`) is unchanged.

### 9. Menu bar poller mirrors the Meet-ingestion poller exactly
Same shape as `_build_meet_poll_timer`/`_run_meet_poll_kickoff`/
`_run_meet_poll`/`_ingest_in_background`: a `rumps.Timer` at
`folder_ingest.poll_interval_minutes`, an immediate startup kickoff timer,
a daemon thread wrapping the scan in the existing
`active_transcriptions` increment/decrement (so the transcribing icon
state covers folder ingestion too), and a poll-failure counter that
notifies once it reaches the existing
`MEET_INGEST_FAILURE_NOTIFY_THRESHOLD`-style constant. Gated off entirely
when `folder_ingest.enabled` is false or `directories` is empty.

### 10. Missing/unreadable configured directory is a warning, not a crash
A configured directory that doesn't exist (typo, unmounted volume) is
logged as a warning and skipped for that scan; it does not abort scanning
the other configured directories, and does not stop the poller from
retrying on the next interval (the directory may come back, e.g. a
removable/synced volume).

## Risks / Open Questions

- **Non-text or binary files with a `.txt`/`.md` extension** land in the
  same failure-then-abandon path as a decode error (Decision 7) — no
  special detection is added beyond "can it be read as UTF-8 text."
- **A user editing a file while it's mid-scan** (e.g. still being synced
  by a cloud-storage client) could be read partially. Out of scope for
  this change; the fixed hourly retry (Decision 4) gives a sync a chance
  to finish before the next attempt, and a partial read is not
  distinguished from any other failure.
- **`poll_interval_minutes` vs. the fixed hourly failure-retry interval**
  can look surprising (a 5-minute poll interval still only retries a
  failing file once an hour) — this mirrors every other ledger in the
  app and is called out explicitly in `config.example.yaml`.
