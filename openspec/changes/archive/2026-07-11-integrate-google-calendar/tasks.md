# Phase 1 — Calendar foundation (`calendar-integration`)

## 1. Dependencies and config schema
- [x] 1.1 Add `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2` to `pyproject.toml` and run `poetry lock`
- [x] 1.2 Extend `meet_recorder/config.py` with an **optional** calendar section: `calendars` (list of `{name}`), `calendar_match_before_minutes` (default ~60), `calendar_match_after_minutes` (default ~15), `ignored_event_slugs` (list), and an `autorecord` block (`enabled`, `poll_interval_minutes`, `notify_before_minutes`). None of these go into `REQUIRED_FIELDS`; a config without `calendars` loads and behaves exactly as today
- [x] 1.3 Define config-dir path conventions: `~/.config/meet-recorder/credentials/{name}.json` and `~/.config/meet-recorder/tokens/{name}.json`
- [x] 1.4 Update `config.example.yaml` with a commented calendar + autorecord section, and `.env.example` with a note that calendar secrets are files in the config dir, never in `.env`

## 2. Credentials, tokens, and OAuth setup
- [x] 2.1 Implement `meet_recorder/calendar.py::build_credentials(account)` that loads the token file, and if expired-with-refresh-token, refreshes via `Request()` **and writes the refreshed token back** to the token file (mode 0600)
- [x] 2.2 Implement clear, catchable errors for missing/invalid credentials or token files (missing file, malformed JSON), surfaced as warnings by callers rather than crashes
- [x] 2.3 Add `handler_calendar_auth(account, ...)` in `handlers.py` running `InstalledAppFlow.from_client_secrets_file(credentials_path, [calendar.readonly]).run_local_server()` and writing the token JSON to the token path (mode 0600), creating the `tokens/` dir as needed
- [x] 2.4 Verify: `poetry run python main.py calendar_auth --account personal` opens the browser and produces a token file

## 3. Event lookup
- [x] 3.1 Implement per-account event query over `[anchor − before_minutes, anchor + after_minutes]` using the Calendar API `events().list` with `singleEvents=True, orderBy=startTime`
- [x] 3.2 Apply filters: drop events where the user's own attendee `responseStatus == "declined"`; drop events whose `slugify(title)` contains any configured ignore-slug
- [x] 3.3 Implement `find_event(anchor_dt, config)` that queries **all** configured accounts, collects `(distance, event, account_name)` candidates, and returns the closest by `abs(event_start − anchor)`, or `None` if no candidate survives
- [x] 3.4 Implement extraction of event data from the winner: title, source account/calendar name, start/end (preserving Google's `dateTime`/`date` form), and up to N attendee display names (falling back to email)
- [x] 3.5 Ensure the whole lookup path is non-fatal: any exception returns `None` and logs a warning

# Phase 2 — Title/summary enrichment (`transcription`)

## 4. Calendar-conditional title and summary
- [x] 4.1 In `transcriber.transcribe`, after resolving the recording timestamp and before title generation, call `calendar.find_event(timestamp, config)` (guarded so it's skipped/None when calendar is unconfigured)
- [x] 4.2 When an event matches, use the event title as the resolved title and **skip** the `_generate_title` LLM call; when no event matches, keep the existing LLM title path unchanged
- [x] 4.3 When an event matches, prepend event context (title + attendee names) to the summary user-content; leave the summary system prompt unchanged
- [x] 4.4 Extend frontmatter to include optional `calendar`, `event_start`, `event_end`, `attendees` fields when an event matched, and remain minimal otherwise
- [x] 4.5 Confirm filenames use the resolved (event-or-LLM) title via the existing slug/timestamp construction — no filename format change
- [x] 4.6 Verify: transcribe a recording whose start time falls in a real calendar event and confirm the event title appears in both filenames + frontmatter and no LLM title call was made; transcribe one with no matching event and confirm unchanged behavior

# Phase 3 — Meeting-prompt scheduler (`meeting-autorecord`)

## 5. Upcoming-event polling in the menu bar
- [x] 5.1 Add a `rumps.Timer` in `menubar.py` (mirroring the recovery-scan timer) that runs every `poll_interval_minutes` when `autorecord.enabled` and calendar is configured; otherwise a no-op
- [x] 5.2 On each poll, query upcoming accepted, non-ignored events (reuse Phase 1 filters, forward-looking window) with per-poll error handling that logs a warning and retries next tick without killing the timer
- [x] 5.3 Track per-event de-duplication (upcoming-notify/start-modal fired-once) via in-memory sets keyed by event id

## 6. Notification + start-time confirmation modal
- [x] 6.1 When an accepted event starts within `notify_before_minutes`, show a one-time `rumps.notification` announcing the next meeting (title + start time)
- [x] 6.2 When such an event's start time has arrived, show a one-time modal dialog (`_show_alert`, ok='Iniciar gravação', cancel='Agora não') naming the meeting (title + start time) and asking whether to start recording
- [x] 6.3 If the user confirms the modal, call `recorder.start_recording()` via the same path as the manual "Iniciar" action and transition menu state exactly like a manual start; if the user cancels/dismisses, take no action — no recording is started and the app does not show the modal again for that event
- [x] 6.4 Surface persistent calendar/auth failures via a `rumps.notification` so login-start (headless) users notice
- [x] 6.5 Since the modal is blocking (`_show_alert`/`NSAlert.runModal` runs on the main thread), confirm the poll timer and other menu bar interactions resume normally once the modal is dismissed, and that only one modal can be queued/shown at a time even if two events start close together (verified: `_run_autorecord_poll` processes events sequentially, so a second event's modal only shows after the first is dismissed)

## 7. Documentation
- [x] 7.1 Add a README "Google Calendar" section: creating the Google Cloud OAuth client, where to place `credentials/{name}.json`, the `calendars:` config, running `calendar_auth` per account, and that tokens live/refresh as files in the config dir (never `.env`)
- [x] 7.2 Document the reactive enrichment behavior (event title in filenames/frontmatter, late-start tolerance window, ignore-slugs)
- [x] 7.3 Document the meeting prompt: config fields, that the app must be running (pairs with launchd login-start), that a modal appears at each meeting's start time, and that recording only starts if the user confirms it

## 8. Manual verification
- [x] 8.1 Reactive: start a recording during a real accepted meeting, stop, and confirm the event title drives both filenames + frontmatter
- [x] 8.2 Late-start tolerance: start a recording ~20–30 min into a meeting and confirm it still matches that event
- [x] 8.3 Ignore-slug: confirm an event whose slug matches an ignore entry is skipped by both enrichment and the meeting prompt
- [x] 8.4 Meeting prompt: with an accepted upcoming test event, confirm the upcoming notification fires, the start-time modal appears with the correct title/time, confirming it starts recording, and dismissing it does not start recording
- [x] 8.5 Unconfigured: with no `calendars:` section, confirm transcription and the menu bar behave exactly as before this change
