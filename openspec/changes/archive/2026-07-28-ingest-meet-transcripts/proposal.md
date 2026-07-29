## Why

When a Google Meet meeting is transcribed by Meet itself (a Workspace feature), the transcript — and often a "Anotações do Gemini" notes doc — is attached to the calendar event afterward as Google Docs. Today `meet-recorder` ignores this entirely: to get a summary of such a meeting the user has to record its audio and run it through the STT pipeline, duplicating work Meet already did (and often better, since Meet's transcript carries speaker attribution).

This change adds a new flow that, for meetings that already ended, pulls the Meet transcript and Gemini notes straight from the calendar event's attachments and produces the same transcript + summary Markdown files the recording pipeline produces. It **complements** — never replaces — the recording pipeline: the user typically does not record meetings that Meet transcribes, and when both happen the Meet-sourced output is allowed to overwrite the recording-sourced one for the same meeting.

The flow runs two ways, mirroring how auto-record already works: on demand via a new CLI handler, and periodically as a background thread in the menu bar app.

## What Changes

- Add a `meet_recorder/drive.py` module that exports a Google Doc (by file id) to Markdown via the Drive API (`files.export`, `text/markdown`), reusing the existing per-account OAuth credential machinery in `calendar.py`.
- Broaden the Google OAuth scope from `calendar.readonly` to also include `drive.readonly`. **This invalidates existing tokens** — every account must be re-authorized with `calendar_auth`. When a token lacks the Drive scope, Drive export fails non-fatally with a clear "re-run calendar_auth" error.
- Add a past-events lookup to `meet_recorder/calendar.py`: query each account for event occurrences that **ended** within a configurable look-back window `[now - lookback_hours, now]`, reusing the existing decline/ignore filtering, and expose each event's Doc attachments (title + Drive file id extracted from the attachment `fileUrl`).
- Add attachment classification that distinguishes a **Transcript** doc (`fileUrl` carries `usp=drive_web`; title ends in `- Transcript`/`- Transcript N`) from a **Gemini notes** doc (`fileUrl` carries `usp=meet_tnfm_calendar`; title `Anotações do Gemini`), independent of UI language.
- Handle the recurring-event attachment-accumulation trap: a recurring occurrence carries Transcript attachments from **all** past occurrences (including under former event names). Bind a Transcript attachment to an occurrence only when the date embedded in its title matches that occurrence's start date; merge multiple same-date transcripts ("Transcript" + "Transcript 2") in order.
- Add a new `meet_transcripts` processing pipeline that, per eligible past occurrence not already processed: exports its Transcript doc(s) and/or Gemini notes doc to Markdown, generates a summary via a **new, speaker-aware `meet_summary_prompt`** (feeding the transcript plus the Gemini notes as extra context), uses the event title as the title, and writes transcript + summary Markdown files with the existing `transcriber` output layout and frontmatter. When only Gemini notes exist (no transcript), still produce output using the notes as the base content.
- Add a persistent dedup ledger: a CSV file in `~/.config/meet-recorder/` keyed by occurrence event id, appended only after a meeting is successfully processed, with rows older than a module-level constant (2 days) pruned on each run for rotation.
- Add a `meet_transcripts` CLI handler (`handler_meet_transcripts`) that runs the flow once over the look-back window.
- Add a background poller to the menu bar app that runs the same flow every `poll_interval_minutes` (configurable) in a daemon thread, reusing the auto-record timer/thread/`active_transcriptions` patterns, gated on an opt-in config section.
- Add a `meet_transcripts` section to `config.yaml` / `config.example.yaml`: `enabled`, `poll_interval_minutes`, `lookback_hours`, and `meet_summary_prompt`.

## Capabilities

### New Capabilities
- `meet-transcript-ingest`: post-meeting ingestion of Google Meet transcript and Gemini notes docs from calendar-event attachments into transcript + summary Markdown files, with attachment classification, recurring-event occurrence binding, a persistent dedup ledger, a CLI entrypoint, and a periodic menu bar poller.

### Modified Capabilities
- `calendar-integration`: OAuth scope broadened to include `drive.readonly`; adds a past-events (ended-within-window) lookup and exposure of event Doc attachments.
- `menubar-app`: adds an opt-in background poller thread that periodically ingests Meet transcripts, reflected in the existing transcribing icon state.

## Impact

- New file: `meet_recorder/drive.py` (Google Doc → Markdown export).
- New file: `meet_recorder/meet_ingest.py` (or similar) — orchestration + ledger for the new flow.
- Modified: `meet_recorder/calendar.py` — Drive scope, past-events lookup, attachment extraction/classification, occurrence binding.
- Modified: `meet_recorder/transcriber.py` — reuse `_generate_summary`/`_write_markdown`/`_frontmatter`; accept a Meet-sourced transcript + Gemini-notes context and a distinct summary prompt.
- Modified: `meet_recorder/config.py` — `meet_transcripts` config section and `meet_summary_prompt`.
- Modified: `meet_recorder/menubar.py` — new poller timer + daemon thread, gated on config.
- Modified: `meet_recorder/handlers.py` — new `handler_meet_transcripts`.
- Modified: `config.example.yaml`, `README.md` — document the new section, the `drive.readonly` re-auth requirement, and the Workspace prerequisite.
- New user-level file: `~/.config/meet-recorder/<ledger>.csv` (dedup ledger, auto-created).
- **Breaking for existing calendar users**: the added Drive scope requires re-running `calendar_auth` for every configured account.
