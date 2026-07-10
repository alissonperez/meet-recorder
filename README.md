Meet Recorder
=============================================

## Requirements

- Python 3.13.0 (in [`.python-version`](./.python-version)): Recommended to use [pyenv](https://github.com/pyenv/pyenv) to manage your python versions.
- **Poetry**: See how to install poetry [here](https://python-poetry.org/docs/#installing-with-pipx).

## How to setup

```
$ make setup
```

To clean up all app env (removing pipenv env, for example):

```
$ make clear
```

## How to run

Fill a `.env` based on `.env.example` and then:

```
$ pipenv run python main.py --help
```

## How to lint

```
make lint
```

## Audio capture setup (BlackHole)

Recording captures both your microphone and the computer's system audio (e.g. the other
participants in a call) at the same time, using [BlackHole](https://existential.audio/blackhole/)
as a virtual audio driver. This requires a one-time system setup:

1. Install the required Homebrew packages:

   ```
   brew install blackhole-2ch switchaudio-osx
   ```

2. Restart Core Audio so the new virtual device appears:

   ```
   sudo killall -9 coreaudiod
   ```

3. Create a Multi-Output Device (one-time, manual):
   - Open **Audio MIDI Setup** (Spotlight → "Audio MIDI Setup").
   - Click `+` in the bottom-left corner → **Create Multi-Output Device**.
   - Check the boxes for your physical output (e.g. "MacBook Pro Speakers" or your headphones)
     and **"BlackHole 2ch"**.
   - Check **"Drift Correction"** next to BlackHole (reduces desync on longer recordings).
   - Rename the device to `Multi-Output (BlackHole)` (or set `MULTI_OUTPUT_DEVICE_NAME` in
     `.env` if you name it differently — see `.env.example`).

Once set up, `python main.py record` will automatically switch the system output to this
Multi-Output Device while recording, and restore your original output device when it stops.

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
[BlackHole setup](#audio-capture-setup-blackhole) above), and adds:

- A modal alert if starting a recording fails (e.g. microphone or BlackHole device not found).
- A native macOS notification if the system-audio channel is detected as silent for a sustained
  period (e.g. the Multi-Output Device isn't selected as system output).
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
are derived from the recording's own timestamp, and `Title-Slug` is the generated title slugified
(and capped to 80 characters).

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

## Autostart at login (launchd)

The menu bar app can be started automatically when you log into macOS, using a `launchd`
LaunchAgent:

- [`run.sh`](./run.sh) — wrapper script that `cd`s into the project directory (so `.env` is
  found) and invokes the poetry venv's Python directly with `main.py menubar`.
- [`com.alisson.meet-recorder.plist`](./com.alisson.meet-recorder.plist) — the LaunchAgent
  definition: `RunAtLoad` (start at login) + `KeepAlive` (relaunch if the process exits), with
  stdout/stderr redirected to log files.

Both files live at the repo root.

### Finding/updating the poetry venv Python path

`run.sh` hardcodes the venv's Python path in `VENV_PYTHON`, since launchd's minimal environment
doesn't reliably have `poetry` on `PATH`. Find the current path with:

```
$ poetry env info --path
```

Append `/bin/python` to that path. If the venv is ever deleted and recreated (e.g. after
`make clear` + `make setup`), its hashed path changes — re-run the command above and update
`VENV_PYTHON` in `run.sh` accordingly.

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

If the icon doesn't appear after loading, check `.err` first — a bad `VENV_PYTHON` path or
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
- On this machine, starting the app via launchd did not trigger a new microphone/screen-recording
  permission prompt beyond what was already granted to the terminal-launched process. If you see
  a new prompt on a different machine, grant it once and it should persist across restarts.
