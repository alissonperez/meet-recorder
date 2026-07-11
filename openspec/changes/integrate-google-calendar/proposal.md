## Why

Recordings today are named and enriched purely from the audio: the title is always LLM-generated, and the app has no idea what meeting a recording belongs to. Meanwhile the user's Google Calendar already knows the real meeting title, when it starts, and who's attending. This change wires Google Calendar into `meet-recorder` for two complementary purposes:

1. **Reactive enrichment** — when a recording is transcribed, match it to the calendar event it belongs to (by start time, tolerant of starting the recording late) and use the *event's* title for the transcript/summary filenames and frontmatter instead of an LLM-invented one.
2. **Proactive meeting prompt** — the menu bar app watches upcoming accepted events, shows a heads-up notification ahead of the next meeting, and at its start time shows a **modal dialog** naming the meeting and asking whether to start recording. Recording only starts if the user confirms in that dialog — the app never starts it silently on the user's behalf.

Both share one calendar client, one multi-account config, and one OAuth setup flow. This is the same integration the prior `obs-transcript` project (see `pipeline-transcricao.md`) proved out, ported to this project's config conventions and split across three phases so each layer lands independently.

## What Changes

Delivered in three phases (see `tasks.md`):

**Phase 1 — Calendar foundation (`calendar-integration`, new)**
- Add a `meet_recorder/calendar.py` module: multi-account Google Calendar client using `calendar.readonly` scope.
- Extend `~/.config/meet-recorder/config.yaml` (the existing config dir) with an **optional** `calendars:` list (logical account names) plus calendar-matching and ignore-slug settings. Absence of this section keeps the app working exactly as today.
- Store OAuth client credentials and per-account tokens as **files under the config dir** (`~/.config/meet-recorder/credentials/{name}.json`, `~/.config/meet-recorder/tokens/{name}.json`), not in `.env`. Refreshed tokens are persisted back to disk (fixing a known wart of the old project where refreshed tokens were never saved).
- Add a `calendar-auth` CLI handler that runs the one-time OAuth browser flow per account and writes the token file.
- Implement event lookup: query all configured accounts over an asymmetric window anchored on a recording's start time, drop events the user has `declined`, drop events whose slugified title contains any configured ignore-slug, and pick the closest event by start-time distance across all accounts.
- Add `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2` dependencies.

**Phase 2 — Title/summary enrichment (`transcription`, modified)**
- Before generating a title, `transcriber.transcribe` looks up the calendar event matching the recording's timestamp. If one is found, the **event title replaces the LLM title call** (saving a call), and the event context (title + attendee names) is prepended to the summary prompt. If no event is found or calendar isn't configured, behavior is unchanged (LLM title, plain summary).
- Output filenames and frontmatter use the resolved title (event title when matched); frontmatter gains optional calendar fields (source calendar, event start/end, attendees) when an event matched.
- Calendar-lookup failure is non-fatal — a warning is logged and transcription proceeds without enrichment.

**Phase 3 — Meeting-prompt scheduler (`meeting-autorecord`, new)**
- The menu bar app polls upcoming accepted events on a background timer, and shows a notification announcing the next meeting ahead of time.
- At an event's start time it shows a **modal dialog** naming the meeting (title + start time) with the choice to start recording now or dismiss. Events matching an ignore-slug are skipped.
- If the user chooses to start recording, the app calls `recorder.start_recording()` via the same path as the manual "Iniciar" action. If the user dismisses/declines, no recording is started and the app takes no further action for that event.
- The prompt is opt-in via config and degrades to a no-op when calendar isn't configured.

## Capabilities

### New Capabilities
- `calendar-integration`: multi-account Google Calendar client, config-dir-based credential/token storage, one-time OAuth setup command, automatic token refresh + persistence, and recording-anchored event lookup with RSVP and ignore-slug filtering.
- `meeting-autorecord`: menu-bar background scheduler that notifies of upcoming accepted meetings ahead of time, then at their start time shows a modal dialog offering to start recording; the app only starts a recording when the user confirms in that dialog.

### Modified Capabilities
- `transcription`: title generation becomes conditional — a matched calendar event's title replaces the LLM-generated title; summary generation is optionally enriched with event context; output frontmatter gains optional calendar fields. All calendar behavior is skipped (unchanged output) when no event matches or calendar is unconfigured.

## Impact

- New file: `meet_recorder/calendar.py` (client, auth, lookup).
- New CLI handler: `handler_calendar_auth` in `meet_recorder/handlers.py`.
- Modified: `meet_recorder/config.py` (optional `calendars`/matching/ignore/autorecord settings; calendar section is optional, not in `REQUIRED_FIELDS`).
- Modified: `meet_recorder/transcriber.py` (conditional title, enriched summary context, calendar frontmatter).
- Modified: `meet_recorder/menubar.py` (background poll timer, upcoming-meeting notification, start-time modal dialog with an explicit user-confirmed call into `recorder.start_recording()`).
- New dependencies: `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2` (pyproject.toml, poetry.lock).
- New user-level files (not in repo): `~/.config/meet-recorder/credentials/{name}.json`, `~/.config/meet-recorder/tokens/{name}.json`.
- Updated: `config.example.yaml` (calendar + autorecord fields), `.env.example` (note: no calendar secrets go in `.env`), `README.md` (calendar setup, OAuth flow, meeting prompt).
- No changes to `meet_recorder/recorder.py` (audio capture untouched; `start_recording()` is only ever called either by the manual "Iniciar" action or by the user confirming the meeting-start modal — never silently by the poller itself).
- No recording-metadata sidecar is introduced — transcription re-derives the event from the recording's own start timestamp, keeping recorder/crash-recovery untouched (see design.md).
