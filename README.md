Meet Recorder
=============================================

Record your meetings on macOS — microphone and system audio together — and turn them into
Markdown transcripts and LLM-generated summaries, optionally enriched with your Google Calendar.

> **Note:** only macOS is supported for now. The audio capture (ScreenCaptureKit), menu bar app,
> and autostart (launchd) are all built on macOS-specific APIs.

## Features

- **Dual-channel audio recording** — captures your microphone and the computer's system audio
  (the other call participants) simultaneously into a single stereo WAV file (channel 0 = mic,
  channel 1 = system audio), using [ScreenCaptureKit](#audio-capture-setup-screencapturekit) —
  no virtual audio driver, no output-device switching, system volume stays controllable.
- **[Menu bar app](#menu-bar-app)** — start/stop recordings on demand from a macOS menu bar
  icon, with status icons for the recording/transcribing states and native notifications for
  failures (e.g. silent system audio, transcription errors).
- **[Transcription + summary](#transcription)** — after a recording stops, it's chunked,
  transcribed via an OpenAI-compatible API (OpenRouter by default), and written out as a
  full-text Markdown transcript plus a structured Markdown summary with an LLM-generated title.
  The source `.wav` is never deleted or moved, so transcription can always be re-run.
- **[Google Calendar integration](#google-calendar-optional)** *(optional)* — matches each
  recording to the calendar event it belongs to (using the event's title and attendees in the
  output), and prompts you at a meeting's start time asking whether to record — recording never
  starts silently on its own. Read-only scope; supports multiple Google accounts.
- **[Meet transcript ingestion](#meet-transcript-ingestion)** *(optional)* — for meetings Google
  Meet transcribed itself, pulls the transcript and Gemini notes from the calendar event's
  attachments and produces the same transcript + summary files without recording — on demand or on
  a background poll.
- **[Autostart at login](#autostart-at-login-launchd)** — a `launchd` LaunchAgent setup to keep
  the menu bar app running from login, with auto-relaunch if it exits.
- **Crash recovery** — `python main.py recover` scans for orphaned in-progress recordings left
  behind by a crash and lets you process, ignore, or delete each one.
- **CLI commands** for everything: `record` (fixed-duration recording), `menubar`, `transcribe`
  (re-run the pipeline on any existing `.wav`), `meet_transcripts` (ingest Meet transcripts from
  calendar events), `calendar_auth`, and `recover` — see `poetry run python main.py --help`.

## Requirements

- **macOS 13+** (Ventura or later): the only supported OS for now — system-audio capture relies
  on ScreenCaptureKit.
- Python 3.13.0 (in [`.python-version`](./.python-version)): Recommended to use [pyenv](https://github.com/pyenv/pyenv) to manage your python versions.
- **Poetry**: See how to install poetry [here](https://python-poetry.org/docs/#installing-with-pipx).

## How to setup

```
$ make setup
```

To clean up all app env (removing the poetry env, for example):

```
$ make clear
```

## How to run

Fill a `.env` based on `.env.example` and then:

```
$ poetry run python main.py --help
```

## How to lint

```
make lint
```

## Audio capture setup (ScreenCaptureKit)

Recording captures both your microphone and the computer's system audio (e.g. the other
participants in a call) at the same time. System audio is captured via
[ScreenCaptureKit](https://developer.apple.com/documentation/screencapturekit) (macOS 13+),
which reads system audio directly from the OS with no virtual audio driver and no output-device
switching — your system volume stays normally controllable throughout a recording.

This requires the running process to have the macOS **Screen Recording** permission (the same
permission screen-recording apps use; audio capture rides on it because there's no separate
"system audio capture" TCC permission prior to macOS 14.2's Core Audio Process Taps API):

1. The first time you record, macOS prompts for Screen Recording permission. Grant it in
   **System Settings → Privacy & Security → Screen Recording**.
2. The permission is granted **per invoking process**, and running the same code from a
   different launcher (e.g. Terminal vs. a `launchd` LaunchAgent) can trigger a *separate*
   prompt attributed to a different binary — see [Autostart at login](#autostart-at-login-launchd)
   below if you're setting up auto-start. If a recording produces no system audio and no error,
   re-check this setting for the process that's actually running (`ps` its PID and compare).
3. If permission is missing entirely, recording fails fast with a clear
   `ScreenCaptureKitError`-style message rather than silently producing an empty channel.

### Echo from speaker bleed into the microphone

The microphone and system-audio channels are recorded separately and never mixed (channel 0 =
mic, channel 1 = system audio), but if system audio is playing out loud through your speakers
while you record, the physical microphone picks up that same audio from the room — at a lower
volume and with a slight delay — in addition to your own voice. Played back together, this sounds
like an echo. This isn't a bug in the capture pipeline; it's inherent to recording mic + system
audio simultaneously with audible speaker output, and isn't specific to ScreenCaptureKit (the
previous BlackHole/Multi-Output Device setup had the same behavior, since it also routed audio to
real speakers alongside the virtual driver). **Use headphones while recording to eliminate it
entirely** — with nothing playing out loud, the microphone has nothing to pick back up.

## Menu bar app

Instead of running a fixed-duration CLI recording, you can start/stop recordings on demand from
a macOS menu bar icon:

```
$ poetry run python main.py menubar
```

This launches a menu bar icon with a submenu:

- **Iniciar** — starts a recording (disabled while already recording; stays enabled even while a
  previous recording is still being transcribed).
- **Parar** — stops and saves the current recording, then starts transcription for it in the
  background (disabled while idle).
- **Parar e não transcrever** — stops and saves the current recording exactly like **Parar**, but
  skips transcription entirely (disabled while idle).
- **Sair** — quits the app, automatically stopping and saving any in-progress recording first. If
  one or more transcriptions are still running in the background, a confirmation alert is shown
  first (see [Transcription](#transcription) below); declining leaves the app running.

The icon reflects two independent, combinable states — recording and transcribing:

| Recording | Transcribing | Icon |
|---|---|---|
| No | No | 🎤 |
| Yes | No | 🔴 |
| No | Yes | ⏳ |
| Yes | Yes | 🔴⏳ |

No count of in-progress transcriptions is shown, only presence/absence of each state.

It uses the same capture logic as `python main.py record` (requires the
[ScreenCaptureKit setup](#audio-capture-setup-screencapturekit) above), and adds:

- A modal alert if starting a recording fails (e.g. no default microphone, or Screen Recording
  permission missing/denied).
- A native macOS notification if the system-audio channel is detected as silent for a sustained
  period, or if no system-audio buffers arrive at all shortly after starting (both point at the
  Screen Recording permission — see setup above).
- A native macOS notification if a background transcription fails (see
  [Transcription](#transcription) below); the app keeps running and the original recording is
  left untouched, so it can be retried later via the `transcribe` CLI command.

The app runs attached to the terminal it was launched from (no `.app` bundle / Finder launch yet)
and must be started manually each time — it does not launch at login.

## Transcription

After a recording is stopped (via **Parar** in the menu bar app, or manually via the CLI), it can
be transcribed into a full-text Markdown transcript plus an LLM-generated Markdown summary. The
pipeline: downmixes/compresses the recording's `.wav` to mono mp3 via `ffmpeg`, splits it into
chunks if it's longer than the configured chunk duration, transcribes each chunk via an
OpenAI-compatible `/audio/transcriptions` endpoint, generates a short title and a structured
summary via separate LLM chat calls, and writes both as Markdown files. The source `.wav` is
never deleted, moved, or renamed by this process, regardless of success or failure — a failed or
skipped transcription can always be re-run later.

### Requirements

- **`ffmpeg`** must be installed and available on `PATH` (e.g. `brew install ffmpeg`).
- **`OPENROUTER_API_KEY`** must be set in `.env` (see `.env.example`). This is the only secret
  used by the transcription pipeline and is never read from `config.yaml`.

### Configuration (`~/.config/meet-recorder/config.yaml`)

Copy [`config.example.yaml`](./config.example.yaml) to `~/.config/meet-recorder/config.yaml` and
adjust it. All fields are required unless noted otherwise:

| Field | Purpose |
|---|---|
| `transcription_model` | Model id used for speech-to-text (sent to `/audio/transcriptions`). |
| `summary_model` | Model id used to generate the Markdown summary. |
| `title_model` | Model id used to generate the short recording title. |
| `transcription_prompt` | Prompt/hint sent alongside the audio to the transcription model. |
| `summary_prompt` | System prompt used to generate the structured summary. |
| `title_prompt` | System prompt used to generate the title (must fit 60 characters or fewer; a bounded retry loop with a truncation fallback enforces this). |
| `transcript_dir` | Directory where full transcript Markdown files are written, in `YYYY-MM` per-month subfolders. |
| `summary_dir` | Directory where summary Markdown files are written, in `YYYY-MM` per-month subfolders. |
| `chunk_duration` | *(optional, default `420`, i.e. 7 minutes)* Seconds per chunk; longer recordings are split into sequential, non-overlapping chunks before transcription. |
| `base_url` | *(optional, default `https://openrouter.ai/api/v1`)* Base URL of the OpenAI-compatible API used for both transcription and chat completions. |

Output files are named `TIMESTAMP - Title-Slug.md`, where `TIMESTAMP` and the `YYYY-MM` folder
are derived from the recording's start time (parsed from the `.wav` filename), and `Title-Slug`
is the generated title slugified (and capped to 80 characters).

For what each of the three prompts (`transcription_prompt`, `summary_prompt`, `title_prompt`)
does, what dynamic calendar-event context is prepended to each, and an example of the output
frontmatter, see [`docs/prompts.md`](./docs/prompts.md).

See [`pipeline-transcricao.md`](./pipeline-transcricao.md) at the repo root for the prior-art
pipeline (from an earlier, separate project) that this transcription approach — chunking,
base64+JSON STT payload, separate title/summary LLM calls — was adapted from.

### Manual transcription (CLI)

An existing `.wav` recording can be transcribed independently of the menu bar app:

```
$ poetry run python main.py transcribe --path=<path-to-recording.wav>
```

This runs the same pipeline used by the menu bar app's background transcription and writes the
same transcript/summary output files.

## Google Calendar (optional)

meet-recorder can optionally connect to Google Calendar for three things:

- **Reactive enrichment** — when a recording is transcribed, it's matched to the calendar event
  it belongs to and the *event's* title is used for the output filenames and frontmatter instead
  of an LLM-invented one.
- **Proactive meeting prompt** — the menu bar app watches your upcoming meetings, notifies you of
  the next one, and at its start time shows a dialog asking whether to start recording — recording
  never starts silently on its own.
- **Meet transcript ingestion** — for meetings Google Meet transcribed itself, pull the transcript
  (and Gemini notes) straight from the calendar event's attachments and produce the same
  transcript + summary files, without recording. See [Meet transcript ingestion](#meet-transcript-ingestion).

The whole feature is **opt-in**. With no `calendars:` list in `config.yaml`, the app behaves
exactly as documented above: an LLM-generated title, no enrichment, and no calendar polling.

### Setup

1. **Create a Google Cloud OAuth client.** In the [Google Cloud Console](https://console.cloud.google.com/),
   create (or reuse) a project, enable the **Google Calendar API**, and create an **OAuth client ID**
   of type *Desktop app*. Download its JSON.
2. **Place the credentials file.** Save that JSON as
   `~/.config/meet-recorder/credentials/{name}.json`, where `{name}` is a logical account name you
   choose (e.g. `personal`, `work`). Repeat per Google account you want to connect.
3. **List the accounts in `config.yaml`:**

   ```yaml
   calendars:
     - name: personal
     - name: work
   ```

4. **Authorize each account once** — this opens a browser for Google's consent screen and writes a
   token file:

   ```
   $ poetry run python main.py calendar_auth --account personal
   ```

Tokens live as files in the config dir (`~/.config/meet-recorder/tokens/{name}.json`, mode `0600`)
and are **refreshed and re-saved automatically** when they expire. **No calendar secret ever goes
in `.env`** — `.env` only holds `OPENROUTER_API_KEY`. The requested scopes are read-only
(`calendar.readonly` and `drive.readonly`); meet-recorder never modifies your calendar or Drive.

> **Re-authorization required for Drive access.** Drive read access (`drive.readonly`) was added
> for [Meet transcript ingestion](#meet-transcript-ingestion). Tokens authorized before that scope
> existed keep working for calendar features but **cannot export Drive docs** — re-run
> `calendar_auth --account {name}` once per account to grant it. Until then, transcript ingestion
> fails non-fatally with a message telling you to re-authorize.

### Reactive enrichment

When a recording is transcribed, its start time (from the `.wav` filename) is matched against your
calendars over an asymmetric window — by default 60 minutes *before* to 15 minutes *after* the
recording started. The large "before" value is what absorbs **starting a recording late**: if you
forget and hit record 20–30 minutes into a meeting, the event still matches. Events you've accepted
("Yes") are preferred over ones you've only tentatively responded to ("Maybe") or left unanswered;
within the winning tier, the closest event by start-time distance across all accounts wins.

When an event matches:

- its title drives both the transcript and summary **filenames** and the `title:` frontmatter (and
  the LLM title call is skipped);
- the frontmatter also gains `calendar`, `event_start`, `event_end`, and `attendees` fields;
- the event title + attendee names are prepended to the summary prompt for context.

Events you've **declined** are ignored, as are events whose slugified title contains any entry in
`ignored_event_slugs`:

```yaml
ignored_event_slugs:
  - lunch
  - almoco
```

Matching keys tuning: `calendar_match_before_minutes`, `calendar_match_after_minutes`. Calendar
lookup is non-fatal — if it fails, transcription proceeds with the plain LLM title and unenriched
summary.

### Meeting prompt

Opt in under `autorecord` in `config.yaml`:

```yaml
autorecord:
  enabled: true
  calendar_poll_interval_minutes: 5   # how often the menu bar app polls Google Calendar
  check_interval_seconds: 60          # how often it re-checks fetched events to notify/prompt
  prompt_delay_seconds: 0             # wait this long after the start time before showing the start modal
  notify_before_minutes: 5            # lead time for the "next meeting" notification
  max_meeting_age_minutes: 20         # don't show the start modal for a meeting older than this
```

With the meeting prompt enabled and at least one calendar configured, the menu bar app polls on a
background timer and:

- shows a **"próxima reunião"** notification once, when an accepted meeting is within
  `notify_before_minutes`;
- at the meeting's start time, shows a **modal dialog** naming the meeting and its start time, with
  the choice **"Iniciar gravação"** or **"Agora não"**. Recording only starts if you click
  **"Iniciar gravação"** — the app never starts a recording on its own. Confirming uses the same
  path as clicking **Iniciar** in the menu, so **Parar** afterward works exactly the same way.

Notes:

- The **app must be running** for the prompt to appear — it pairs naturally with the
  [launchd login-start](#autostart-at-login-launchd) below.
- Meetings matching an `ignored_event_slugs` entry never trigger the prompt, and an event that
  arrives while a recording is already in progress is skipped (no modal, never double-records).
- The dialog is shown once per event; dismissing it (or ignoring it) means it won't reappear for
  that meeting.
- Persistent calendar/auth failures are surfaced via a notification so login-start users notice.

### Meet transcript ingestion

When Google Meet transcribes a meeting itself (a **Google Workspace** feature), it attaches the
transcript — and often an "Anotações do Gemini" notes doc — to the calendar event afterward as
Google Docs. This flow pulls those Docs from past events and produces the same transcript + summary
Markdown files the recording pipeline does, so meetings you **didn't record** still get output. It
complements recording; it never replaces it.

**Prerequisites:**

- The meeting must have been transcribed by Google Meet (a Workspace feature — personal Gmail
  accounts don't transcribe).
- Each account's token must include `drive.readonly` — re-run `calendar_auth --account {name}`
  after upgrading (see the re-authorization note under [Setup](#setup)).

Run it once on demand over the look-back window:

```
$ poetry run python main.py meet_transcripts
```

Or enable the background poller in the menu bar app under `meet_transcripts` in `config.yaml`:

```yaml
meet_transcripts:
  enabled: true
  poll_interval_minutes: 15   # how often the menu bar app polls for newly-ended meetings
  lookback_hours: 12          # ingest meetings that ended within this window (clamped to 48h)
  max_access_retries: 3       # per-file access retries before giving up (throttled to hourly)

# Optional. Unlike summary_prompt, this MAY attribute speech to people, since Meet transcripts
# carry speaker names. A sensible default is used when omitted.
meet_summary_prompt: |
  Você é um assistente que resume transcrições de reuniões em português.
  A transcrição a seguir foi gerada pelo Google Meet e identifica quem fala.
  ...
```

How it works and its limits:

- Each eligible past occurrence's Doc attachments are exported to Markdown via the Drive API and
  written with the event title as the title and the occurrence start time as the timestamp. Output
  reuses the existing per-month folders and frontmatter.
- A meeting with Gemini notes but no transcript still produces output, using the notes as the body.
- **Overwrite by design:** if both this flow and a recording produce output for the same meeting,
  the Meet-sourced files win (they carry speaker attribution).
- **Recurring-event accumulation:** a recurring occurrence surfaces transcript attachments from
  *all* past occurrences (even under former event names). A transcript is bound to an occurrence
  only when the date in its title matches that occurrence's start date; same-date segments
  (`Transcript`, `Transcript 2`, …) are concatenated in order.
- **Gemini-notes binding is best-effort:** the notes carry no date, so when an event has more than
  one Gemini notes doc they are skipped (with a warning) rather than risk attaching the wrong one.
- A persistent, self-rotating dedup ledger (`~/.config/meet-recorder/processed_meet.json`) keeps a
  processed or abandoned meeting from being reprocessed. A transcript that isn't attached yet is
  simply retried on the next poll; a doc that's attached but unreadable (not shared with you) is
  retried at most hourly, then abandoned — the menu bar app shows a one-time modal the first time.

## Autostart at login (launchd)

The menu bar app can be started automatically when you log into macOS, using a `launchd`
LaunchAgent:

- [`run.sh`](./run.sh) — wrapper script that `cd`s into the project directory (so `.env` is
  found) and invokes `poetry run python main.py menubar`.
- [`com.alisson.meet-recorder.plist`](./com.alisson.meet-recorder.plist) — the LaunchAgent
  definition: `RunAtLoad` (start at login) + `KeepAlive` (relaunch if the process exits), with
  stdout/stderr redirected to log files.

Both files live at the repo root.

### Before installing: edit the plist placeholders

`com.alisson.meet-recorder.plist` ships with placeholder paths. Edit `HOME` and
`ProgramArguments` to point at your own username and the absolute path where you cloned the
repo:

```xml
<key>HOME</key>
<string>/Users/YOUR_USERNAME</string>
...
<string>/path/to/meet-recorder/run.sh</string>
```

`run.sh` itself needs no editing — it resolves its own directory and runs `poetry run`, so it
works from wherever the repo lives, as long as `poetry` is on the `PATH` set in the plist
(`/opt/homebrew/bin` by default).

### Install

```
$ ln -sf "$(pwd)/com.alisson.meet-recorder.plist" ~/Library/LaunchAgents/com.alisson.meet-recorder.plist
$ launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alisson.meet-recorder.plist
```

The menu bar icon should appear shortly after loading, without running any command manually.

### Checking logs

```
$ tail -f /tmp/com.alisson.meet-recorder.out
$ tail -f /tmp/com.alisson.meet-recorder.err
```

If the icon doesn't appear after loading, check `.err` first — a bad `HOME`/project path or
missing `.env` will show up there. `KeepAlive` will keep relaunching the process even if it's
crashing immediately, so a tight restart loop in the logs is a sign something's misconfigured.

Note: `icecream`'s `ic()` debug calls still emit ANSI color codes regardless of whether stdout is
a terminal (this is separate from this project's own logger, which is fully plain when
non-interactive) — you may see a few colored escape sequences mixed into otherwise plain log
files.

### Uninstall

```
$ launchctl bootout gui/$(id -u)/com.alisson.meet-recorder
$ rm ~/Library/LaunchAgents/com.alisson.meet-recorder.plist
```

### Notes

- Only the app/menu bar icon starts automatically — no recording starts on its own; you still
  click **Iniciar**.
- **Screen Recording permission under launchd is separate from the terminal-launched grant.**
  Unlike the microphone permission, Screen Recording is attributed to the specific binary macOS
  identifies as responsible for the process — when launched via this LaunchAgent, that resolves
  to the Poetry venv's `python` executable, not to Terminal/iTerm. The first time a recording
  runs under launchd, expect a separate System Settings prompt even if you already granted it
  while testing from a terminal; grant it once and it persists across restarts (but the venv's
  path includes a content hash and can change on `make clear && make setup`, which may require
  re-granting).

## License

[GNU AGPL v3.0](./LICENSE)
