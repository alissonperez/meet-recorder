## Context

`meet-recorder` records mic + system audio to a stereo `.wav` (`recorder.py`), then `transcriber.py` produces a transcript + LLM title + LLM summary, named `TIMESTAMP - Title-Slug.md` under per-month folders. Config lives in `~/.config/meet-recorder/config.yaml` (non-secret) with `OPENROUTER_API_KEY` in `.env` (secret). The menu bar app (`menubar.py`, `rumps`) already runs background work via `rumps.Timer` (recovery scan) and daemon threads (silence monitor, transcription), and already emits `rumps.notification(...)`.

The prior `obs-transcript` project (`pipeline-transcricao.md`) proved out the Google Calendar pieces we're porting: multi-account config referencing per-account credentials/tokens, `calendar.readonly` OAuth, automatic refresh, and an asymmetric lookup window anchored on the recording's start time picking the closest event by distance. We reuse that logic and its filters (declined-RSVP drop, ignored-title list) but adapt storage to this project's config-dir convention and add a forward-looking scheduler the old batch project never had.

Note: the existing `menubar-autostart` capability is unrelated — it's launchd login-start of the app, not calendar-triggered recording. This change introduces a separate `meeting-autorecord` capability.

## Goals / Non-Goals

**Goals:**
- One shared calendar client/config/auth serving both reactive enrichment and proactive scheduling.
- Keep all calendar configuration in the existing config dir; store OAuth tokens as files there (chmod 600) and persist refreshed tokens.
- Reactive: use the matched event's title for filenames + frontmatter, tolerant of the user starting the recording up to ~30 min late.
- Proactive: notify of the next accepted meeting and auto-start recording at its start time, with a start notification.
- All calendar behavior optional and non-fatal: unconfigured or lookup-failure paths behave exactly like today.

**Non-Goals:**
- Auto-stopping a recording at the event's end (user chose notify-only; meetings run over).
- A recording-metadata sidecar file passed from recorder → transcriber (see Decision 4).
- Writing to the calendar (create/modify events) — scope is `calendar.readonly`.
- Speaker diarization / attendee-to-speech attribution (summary prompt still instructs against attribution).
- Bundling an OAuth client secret in the repo — the user supplies their own Google Cloud OAuth client.
- Cross-account priority rules — winner is purely closest-by-time across all accounts, as in the old project.

## Decisions

### 1. Tokens and credentials as files in the config dir
OAuth client credentials go in `~/.config/meet-recorder/credentials/{account}.json` and tokens (which contain the refresh token) in `~/.config/meet-recorder/tokens/{account}.json`, written mode `0600`. `config.yaml` lists only logical account **names**; the file paths are derived by convention. This satisfies "keep all config in the config dir," avoids bloating `.env` with large JSON blobs, and — because we own a writable file — lets us **persist the refreshed token** after `creds.refresh(...)`, fixing the old project's wart where a refreshed token lived only in memory. `.env` continues to hold only `OPENROUTER_API_KEY`; no calendar secret ever enters `.env` or `config.yaml`.

### 2. Calendar config is an optional, additive section
`config.py` gains optional fields (`calendars`, match-window minutes, `ignored_event_slugs`, `autorecord`) that are **not** added to `REQUIRED_FIELDS`. A config with no `calendars:` list loads and runs exactly as today; transcription simply skips enrichment and the scheduler is a no-op. This keeps existing users unbroken and makes the feature opt-in.

### 3. Lookup window and matching (reactive)
Anchored solely on the recording's **start** timestamp (already encoded in the `.wav` filename), not its duration. Window `[start − before_minutes, start + after_minutes]` with configurable minutes (defaults ~60 before / ~15 after, matching the old project). The larger *before* value is exactly what absorbs "I forgot and started the recording up to 30 min late" — an event that began before the recording still falls inside the window. Google's Calendar API filters `timeMin` by event *end* and `timeMax` by event *start*, so this asymmetry is intentional. Across all accounts, candidates surviving the filters are ranked by absolute distance between event start and recording start; the single closest wins. Filters, in order: drop if the user's own `attendee.self.responseStatus == "declined"`; drop if `slugify(title)` contains any configured ignore-slug.

### 4. No recording-metadata sidecar — transcription re-derives the event
An auto-started recording knows its event, so a tempting design is to write a sidecar `{timestamp}.json` next to the `.wav` and have the transcriber read it. We deliberately **don't**: it would force `recorder.py`, the `.in-progress` layout, crash-recovery, and the stereo merge to all carry and preserve an extra file, for no correctness gain. Because the reactive lookup is anchored on the recording's start timestamp, an auto-started recording (which begins exactly at event start) is matched precisely by the same code path a manual recording uses. One mechanism, keyed on the timestamp, serves both — recorder and crash-recovery stay untouched.

### 5. Title becomes conditional; summary gains optional context
The two LLM calls were intentionally kept separate in the transcription design precisely to allow this. Now: if an event matches, the **event title replaces** the `_generate_title` LLM call entirely (and its retry loop), and the event context (title + up to N attendee display names) is prepended to the summary user-content. If no event matches, both calls behave as today. The summary *prompt* is unchanged; only the user content is optionally prefixed. Frontmatter gains optional `calendar`, `event_start`, `event_end`, `attendees` fields when an event matched, and stays minimal otherwise.

### 6. Auto-record uses a rumps.Timer poll, not precise per-event timers
The scheduler polls upcoming events every `poll_interval_minutes` (default ~5) via a `rumps.Timer`, mirroring the existing recovery-scan timer, rather than scheduling a precise one-shot timer per event. Polling is simpler, self-healing across sleep/wake and calendar edits, and start-time granularity of a few minutes is acceptable for meeting recording. On each poll it: (a) if an accepted, non-ignored event starts within `notify_before_minutes`, shows a one-time "próxima reunião: X às HH:MM" notification; (b) if such an event's start time has arrived and we're not already recording, calls `recorder.start_recording()` and shows a "gravando: X" notification; (c) if a recording it auto-started passes the event's end time, shows a one-time "reunião terminou — ainda gravando" notification without stopping. De-duplication (notify/start/end each fire once per event) is tracked by event id in in-memory sets for the app's lifetime.

### 7. Reuse existing background/notification patterns
No new concurrency primitives: the scheduler lives on a `rumps.Timer` like the recovery scan; auto-started recordings flow through the same `recorder.start_recording()` / menu-state code the manual "Iniciar" uses, so the icon and manual "Parar" work identically. Calendar network calls made from the timer are wrapped so a transient API failure logs a warning and is retried on the next poll rather than killing the timer.

### 8. Auth setup as a CLI handler
`handler_calendar_auth(account, ...)` runs `InstalledAppFlow.from_client_secrets_file(...).run_local_server()` for the named account, then writes the resulting token JSON to `~/.config/meet-recorder/tokens/{account}.json` (mode 0600). Scope: `https://www.googleapis.com/auth/calendar.readonly`. This mirrors the old project's `setup_calendar_auth.py` but writes a file instead of printing a blob to paste into `.env`.

## Risks / Trade-offs

- **Poll granularity delays auto-start by up to one interval** → Mitigation: default interval small (~5 min) and a shorter effective start check; acceptable for meetings. Precise per-event timers rejected as over-engineered (Decision 6).
- **App must be running for auto-record** → Documented; pairs naturally with the existing launchd login-start (`menubar-autostart`). No auto-start when the app is closed.
- **Wrong event matched near back-to-back meetings** → Closest-by-start-distance is the same heuristic the old project ran in practice; ignore-slugs and the declined filter reduce noise. Accepted.
- **OAuth token expiry / revoked access** → Refresh is attempted and persisted; on hard failure the lookup is non-fatal (warning + unenriched output) and the scheduler logs + retries next poll. A `rumps.notification` surfaces persistent auth errors so headless login-start users notice.
- **Recording already in progress when an event starts** → Scheduler skips auto-start (never interrupts or double-records); the ongoing recording will still be enriched reactively by whichever event its own start time matches.
- **All-day / multi-hour events** → Anchored on start time; all-day events (`date` not `dateTime`) are effectively never "starting now" for auto-record and are low-distance only near midnight — acceptable, but validation during implementation should confirm all-day events don't spuriously trigger auto-record.

## Migration Plan

No data migration. Calendar is opt-in: existing installs keep working with no config change. To enable, a user (1) creates a Google Cloud OAuth client and drops its JSON at `~/.config/meet-recorder/credentials/{account}.json`, (2) adds a `calendars:` list to `config.yaml`, (3) runs `poetry run python main.py calendar_auth --account <name>` once per account, (4) optionally enables `autorecord`. Existing recordings are unaffected and, once calendar is configured, will be enriched on any future re-transcription because matching is purely timestamp-based.

## Open Questions

- Exact config field names and default window minutes / poll interval — finalized during implementation against `config.example.yaml`.
- Whether the upcoming-meeting reminder should fire once per event or repeat as start approaches — leaning once, tunable by `notify_before_minutes`.
- Whether to expose a menu toggle to enable/disable auto-record at runtime, or config-only for v1 — leaning config-only to keep the menu minimal.
