## Context

`meet-recorder` records audio and, via `meet_recorder/transcriber.py`, turns a `.wav` into transcript + summary Markdown, optionally enriched with a matched Google Calendar event (`meet_recorder/calendar.py`, `calendar.readonly` scope). The menu bar app (`meet_recorder/menubar.py`) already runs an opt-in auto-record scheduler: a `rumps.Timer` polls the calendar every N minutes and a daemon thread does the heavy work, with an `active_transcriptions` counter driving the icon.

Google Meet (a Workspace feature) can transcribe a meeting on its own and attach the result to the calendar event afterward. This change ingests those attachments directly, producing the same output files, so meetings the user did **not** record still get a transcript + summary. It reuses the transcriber's summary/output layer and the auto-record timer/thread pattern wholesale.

The attachment shapes below were confirmed against the user's real Workspace calendar (2026-07), not assumed.

## Goals / Non-Goals

**Goals:**
- Ingest Meet transcript and "Anotações do Gemini" docs from past calendar events into the existing transcript + summary Markdown layout, on demand (CLI) and periodically (menu bar thread).
- Bind attachments to the correct occurrence so recurring events don't reprocess months of history.
- Survive restarts via a persistent, self-rotating dedup ledger.
- Complement the recording pipeline; when both produce output for the same meeting, let the Meet-sourced files overwrite.
- Fail non-fatally and loudly when the OAuth token lacks the new Drive scope.

**Non-Goals:**
- Google Meet REST API (`conferenceRecords`) — explicitly out; attachments cover the need without an extra API/scope surface.
- Downloading the Meet *recording* video attachment (none observed; not needed for transcript/summary).
- Perfect occurrence binding for Gemini notes (they carry no date — see Decision 4).
- Retry/backoff beyond the existing single-attempt style; a not-yet-available transcript is simply retried on the next poll.
- Replacing or suppressing the recording pipeline for transcribed meetings.

## Empirical findings (user's real calendar, 2026-07)

Attachment objects on an event look like (via `events.list`):

| Kind | `title` | `fileUrl` query | Has date in title? |
|---|---|---|---|
| Transcript | `<meeting> - 2026/07/15 16:32 GMT-03:00 - Transcript` (also `- Transcript 2`) | `usp=drive_web` | **Yes** (≈ meeting start) |
| Gemini notes | `Anotações do Gemini` (localized!) | `usp=meet_tnfm_calendar` | No |

Critical facts:
- **`Transcript` is not localized; `Anotações do Gemini` is.** Classify by the `fileUrl` `usp=` marker (language-independent) as the primary signal, title as secondary.
- **`fileId`/`mimeType` came back null** from the tooling used to inspect; the Drive doc id is always recoverable from the `fileUrl` path (`/document/d/<ID>/`). Extract from `fileUrl` as the source of truth; treat `fileId` as a fallback only.
- **Recurring occurrences accumulate all past occurrences' Transcript attachments**, including under a previous event name (observed: an occurrence carried transcripts dated 07/15, 06/10, and 05/27). This is the central correctness hazard.
- **The user is often an attendee, not the organizer, and still sees the attachments** — so ingestion is not organizer-gated.
- Some events have only a transcript, some only Gemini notes, some (potentially) both.

## Decisions

### 1. Source: event attachments only, via Drive export (no Meet API)
For each eligible past occurrence, read its Doc attachments off the calendar event and export each doc with Drive `files.export(fileId, mimeType='text/markdown')`. Exporting to `text/markdown` (not HTML) means no markup parsing — consistent with the project's preference for stdlib parsers over regex-on-HTML, by avoiding HTML altogether. The Drive doc id is parsed from the attachment `fileUrl` with `urllib.parse` (path segment after `/document/d/`), not a regex.

### 2. Attachment classification by `usp=` marker
- **Transcript**: `fileUrl` contains `usp=drive_web` **and** title ends with `- Transcript` or `- Transcript <n>`.
- **Gemini notes**: `fileUrl` contains `usp=meet_tnfm_calendar` (title `Anotações do Gemini` as a secondary check).
- Anything else (e.g. a manually attached doc, a recording video) is ignored.
The `usp=` marker is the primary discriminator because it is language-independent, unlike the localized Gemini title.

### 3. Occurrence binding for transcripts by embedded date
A Transcript attachment is bound to an occurrence only when the date parsed from its title (`YYYY/MM/DD HH:MM GMT±HH:MM`) matches the occurrence's start **date** (day-level match; the title time drifts a minute or two from scheduled start, so time is not compared strictly). Multiple same-date transcripts (`- Transcript`, `- Transcript 2`, …) are segments of one meeting → sorted by their trailing index and concatenated in order. This is what prevents a recurring occurrence from reprocessing every historical transcript piled onto the series.

### 4. Gemini notes binding is best-effort
Gemini notes carry no date in the title, so they cannot be bound by date. Rule: attach a Gemini notes doc to the occurrence only when the event carries **exactly one** Gemini notes attachment (the observed norm — recurring events surface only the latest). If more than one is present, skip the Gemini notes (transcript still processes) and log a warning, rather than risk attaching the wrong occurrence's notes. Documented as a known limitation.

### 5. Output: reuse the transcriber layer, new speaker-aware summary prompt
Reuse `transcriber._generate_summary`, `_write_markdown`, `_build_base_filename`, `_frontmatter`, and the `transcript_dir`/`summary_dir`/`YYYY-MM/` layout unchanged. Differences from the recording pipeline:
- **Title** = the calendar event title (always available here), never LLM-generated.
- **Transcript content** = the exported Meet transcript Markdown (or, when absent, the Gemini notes — see Decision 7).
- **Summary** = one `chat.completions` call with a **new `meet_summary_prompt`** that, unlike the recording pipeline's prompt, *may* attribute speech to people (Meet transcripts carry speaker names) and is fed the transcript **plus the Gemini notes as extra context** (Decision from exploration: option A — Gemini enriches, never replaces, the generated summary).
- **Timestamp** for filename/frontmatter = the occurrence start time (from the event), not a `.wav` mtime.
- Frontmatter reuses the event fields (`calendar`, `event_start`, `event_end`, `attendees`) already emitted by `_frontmatter`.

### 6. Overwrite on collision, by design
Because the filename is `TIMESTAMP - Title-Slug.md` and both pipelines can target the same meeting, a Meet-sourced run may overwrite a recording-sourced file for the same event. This is the accepted resolution ("aceitar o que sobrescrever do processo da transcrição do meet") — the Meet transcript is preferred. No collision detection or suffixing is added.

### 7. Gemini-only meetings still produce output
When an occurrence has Gemini notes but no transcript, still produce both files: the Gemini notes Markdown becomes the transcript file's body, and the summary is generated from those notes. This realizes the user's decision to "generate output either way," so a meeting with transcription off but Gemini notes on is not silently dropped.

### 8. Persistent state ledger keyed by occurrence id, with per-event status
State lives in a JSON file under `~/.config/meet-recorder/` (e.g. `processed_meet.json`) — a map keyed by the **occurrence** event id (e.g. `msi..._20260715T193000Z`), unique per occurrence, so recurring series dedup correctly. JSON (not CSV) is chosen because entries are now structured and updated in place (read-modify-write), not append-only. Each entry carries:

```
"<occurrence_event_id>": {
  "status": "done" | "deferred" | "abandoned",
  "attempts": <int>,            # counts ACCESS failures only
  "last_attempt": "<ISO 8601>"
}
```

- `done` — files written successfully; terminal, always skipped.
- `deferred` — a transcript exists but could not be read (access error); will be retried, throttled (Decision 12).
- `abandoned` — access retries exhausted; terminal, treated as seen.
- A **not-yet-available** transcript (nothing attached yet) is left **unrecorded** — it is retried on every poll, silently, and is distinct from `deferred`.

An entry reaches `done`/`abandoned` only as described in Decision 12. On each run, entries whose `last_attempt` is older than a module-level `LEDGER_RETENTION_DAYS = 2` are pruned (rotation) and the file rewritten atomically (temp file + `os.replace`). Access is serialized with a module-level `threading.Lock` (like `calendar._token_lock`); cross-process races (CLI + menu bar simultaneously) are an accepted low-probability edge.

> **Constraint:** `LEDGER_RETENTION_DAYS` (2 days) must remain ≥ both the largest sane `lookback_hours` (clamped ≤ 48h) and the total access-retry span (`max_access_retries × ACCESS_RETRY_INTERVAL_HOURS`). Otherwise an entry could age out of the ledger while still relevant and be reprocessed. Enforced by clamping `lookback_hours ≤ 48` and keeping retry span well under 2 days.

> **State, not config:** this file is app-managed runtime state and is intentionally kept **separate from `config.yaml`** (which is user-edited) — mixing them would clobber user comments and blur config vs. state.

### 9. Past-events lookup, reusing existing filters
Add `calendar.past_events(config, lookback_hours)` returning occurrences whose `end_dt` is within `[now - lookback_hours, now]`, across all accounts, reusing `_eligible_events` (decline + ignore-slug + parseable-start filtering) and `_extract_event`. `CalendarEvent` gains an `attachments` field (list of raw attachment dicts, or pre-classified). This is the mirror image of the existing `upcoming_events`.

### 10. New Drive scope → forced re-auth, surfaced clearly
`CALENDAR_SCOPES` becomes `['.../calendar.readonly', '.../drive.readonly']`. Existing tokens (calendar-only) will refresh but Drive calls 403. Detect a request-level missing-scope error on export and raise a `CalendarError`/`DriveError` instructing the user to re-run `calendar_auth --account <name>`; this is a **run-level** abort (Decision 12), distinct from a per-file access error, and must not consume any occurrence's retry budget. `calendar_auth`, `README`, and `config.example.yaml` are updated to state the re-auth requirement. Non-calendar behavior (recording, STT) is unaffected by an un-upgraded token.

### 11. Menu bar poller mirrors auto-record
A second `rumps.Timer` (interval `meet_transcripts.poll_interval_minutes`) plus a kickoff timer (immediate first run, like `_calendar_poll_kickoff`) starts only when the `meet_transcripts` config section is enabled and calendars are configured. Its callback launches a daemon thread that runs the ingest flow, wrapping work in the existing `active_transcriptions` increment/`_refresh_title`/decrement pattern so the ⏳ icon reflects ingestion. Poll failures reuse the `_on_poll_failure` warn-then-notify-on-threshold approach. The CLI handler and the thread call the same orchestration function.

### 12. Access-error handling: throttled retry, then abandon
Reading a transcript doc can fail even though the doc is attached — most commonly because it was never shared with the user in Drive (a per-file permission problem). This is distinct from both "not attached yet" (Decision 8) and "token missing the Drive scope" (Decision 10), and each is handled differently:

| Failure | Scope | Handling |
|---|---|---|
| Transcript not attached yet | per-occurrence | not recorded; retried every poll, silent |
| **Doc attached but not readable** (per-file 403/404) | per-occurrence | `deferred`; retried **at most once per hour**; abandoned after `max_access_retries`; **modal shown once per event** |
| Token missing Drive scope (request-level 403 `insufficientPermissions`/scope) | whole run | abort the run, notify "re-run `calendar_auth`", **do not** consume any event's retry budget |

The classification matters because a scope error hits *every* event at once and must not burn each event's per-file retry budget.

Per-file access-error flow, keyed on the ledger entry (Decision 8):
- On access error, set/keep `status = deferred`, `attempts += 1`, `last_attempt = now`.
- Skip a `deferred` occurrence while `now - last_attempt < ACCESS_RETRY_INTERVAL_HOURS` (module constant = 1) — so even with a 5-minute poll interval, an unreadable doc is retried no more than hourly. This gives the organizer time (`max_access_retries` hours) to grant the share before we give up.
- When `attempts` reaches `max_access_retries` (config `meet_transcripts.max_access_retries`, default 3), set `status = abandoned` (terminal, treated as seen).

**Modal, once per event.** In the menu bar app, the *first* time an occurrence hits an access error, show a blocking alert via the existing `_show_alert` (raised above fullscreen apps, same as the auto-record prompt) explaining the transcript for "<event title>" could not be accessed and will be retried. Subsequent hourly retries for the same event only log — the modal is **not** re-shown per retry (that would block the menu bar every hour). A second (final) modal on `abandoned` is optional. Notifications would be less intrusive but are not reliably opening in this environment, so a once-per-event modal is used deliberately. In CLI mode there is no modal — access errors are logged and the ledger is updated the same way.

`ACCESS_RETRY_INTERVAL_HOURS` is a fixed module constant (the requirement is "no more often than hourly", not a tuning knob); only `max_access_retries` is user-configurable.

## Risks / Open Questions

- **`fileId`/`mimeType` null in inspection tooling.** Mitigated by parsing the doc id from `fileUrl`; the real `googleapiclient` `events.list` is expected to populate `fileId` too, but the code does not depend on it.
- **Attachment title/format drift.** Google could change the `- Transcript` suffix or the `usp=` markers. Classification is centralized in one function with both signals, so drift is a localized fix. Worth a debug log of unclassified attachments.
- **Gemini multi-note ambiguity** (Decision 4) — accepted limitation; skips notes rather than guessing.
- **Transcript availability latency.** Meet transcripts can appear minutes-to-hours post-meeting; `lookback_hours` must be wide enough to catch them on a later poll. Default suggested: 6–12h.
