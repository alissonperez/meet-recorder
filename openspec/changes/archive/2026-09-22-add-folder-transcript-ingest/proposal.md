## Why

Not every meeting transcript or note the user wants summarized comes from a
`.wav` recording or a Google Calendar event. Text sometimes just shows up on
disk — exported from another tool, dictated by hand, dropped in by a phone
shortcut, synced from a note-taking app. Today the only way to run such text
through meet-recorder's transcript + summary pipeline is
`ingest_transcript`, one Google Doc URL at a time, by hand.

This change adds a directory-polling flow: the user registers one or more
local directories in `config.yaml`, and meet-recorder periodically scans
each one for new `.txt`/`.md` files and runs each through the same standard
summary/title/output pipeline the rest of the app uses — mirroring how
`meet_transcripts` already polls Google Calendar for Meet-sourced
transcripts, but for local files instead of Drive-sourced ones.

## What Changes

- Add a `folder_ingest` config section: `enabled`, `directories` (a list of
  paths), `poll_interval_minutes`, `max_attempts`.
- Add `meet_recorder/folder_ingest.py`: scans each configured directory's
  top level (non-recursive) for `.txt`/`.md` files, skipping any file whose
  ledger entry is a throttled `deferred` or a terminal `abandoned`.
- Extract the reusable "ready transcript text -> summary + title + output
  files" tail already used by `transcriber.ingest_doc` into a shared
  `transcriber.ingest_text(transcript_text, config, title=None,
  timestamp=None)` entrypoint, so folder ingest and `ingest_doc` share one
  implementation instead of two.
- For each picked-up file: read its text, run it through
  `transcriber.ingest_text` (title LLM-generated, summary via the standard
  `summary_prompt`, transcript + summary Markdown written to
  `transcript_dir`/`summary_dir`), timestamped by the file's mtime.
- On success, move the source file into a `processed/` subdirectory of the
  directory it was found in.
- On failure, record the failure in a new persistent ledger keyed by the
  file's absolute path (mirrors the existing Meet-ingest and
  deferred-transcription ledgers): retried on a fixed hourly interval up to
  `max_attempts`, then moved into a `failed/` subdirectory and left there.
- Add a `folder_ingest` CLI command (`handler_folder_ingest`) that runs one
  scan over every configured directory on demand.
- Add a menu bar poller (timer + startup kickoff timer + daemon thread),
  gated on `folder_ingest.enabled`, mirroring the existing Meet-ingestion
  poller including transcribing-icon state and poll-failure notification.
- Document the new section in `config.example.yaml`.

## Capabilities

### New Capabilities
- `folder-transcript-ingest`: opt-in periodic scanning of configured local
  directories for `.txt`/`.md` transcript/notes files, running each through
  the standard transcript + summary pipeline, with move-based dedup
  (`processed/`/`failed/` subdirectories) and a persistent retry ledger for
  failures.

### Modified Capabilities
- `menubar-app`: adds an opt-in background poller thread that periodically
  ingests folder-sourced transcripts, reflected in the existing
  transcribing icon state.

## Impact

- New file: `meet_recorder/folder_ingest.py` — directory scan + per-file
  orchestration + move/ledger bookkeeping.
- Modified: `meet_recorder/transcriber.py` — extract `ingest_text(...)` out
  of `ingest_doc`'s tail; `ingest_doc` becomes a thin wrapper around it.
- Modified: `meet_recorder/config.py` — `FolderIngestConfig` + `folder_ingest`
  section, directory path expansion.
- Modified: `meet_recorder/menubar.py` — new poller timer + daemon thread,
  gated on config, mirroring `_build_meet_poll_timer`/`_run_meet_poll`.
- Modified: `meet_recorder/handlers.py` — new `handler_folder_ingest`.
- Modified: `config.example.yaml`, `README.md` — document the new section
  and the filesystem side effects (`processed/`/`failed/` subdirectories).
- New user-level file: `~/.config/meet-recorder/processed_folder_ingest.json`
  (retry ledger, auto-created).
- New filesystem side effect inside every configured directory: a
  `processed/` subdirectory (always) and a `failed/` subdirectory (only once
  a file is first abandoned) are created and populated by the app.
