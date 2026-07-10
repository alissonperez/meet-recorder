## Why

Today a recording stops as a `.wav` file and nothing else happens — turning it into a transcript and a summary is a manual step outside the app. This change closes that gap: right after stopping a recording, the app transcribes the audio and generates a summary automatically, in the background, without blocking a new recording from starting. Calendar enrichment (meeting title/attendees from Google Calendar) is explicitly out of scope for this change and will be layered on later.

## What Changes

- Add a `meet_recorder/transcriber.py` module that, given a recording's `.wav` path: downmixes/compresses it to mp3 via `ffmpeg`, splits it into fixed-duration chunks (no overlap) if it exceeds a configured duration, transcribes each chunk via a raw HTTP call to an OpenAI-compatible `/audio/transcriptions` endpoint (base64+JSON payload, not multipart), generates a short title via one LLM chat call and a structured summary via a separate LLM chat call (both via the `openai` SDK pointed at a configurable `base_url`, defaulting to OpenRouter), and writes the full transcript and the summary as two Markdown files.
- Add a YAML config file at `~/.config/meet-recorder/config.yaml` for: transcription model, summary model, title model, the three prompts (transcription hint, summary, title) as inline strings, two output directories (transcript dir, summary dir), chunk duration, and the OpenRouter `base_url`. The OpenRouter API key stays in `.env` (`OPENROUTER_API_KEY`), consistent with existing project convention — it is never read from this config file.
- Change the default "Parar" menu bar action to trigger transcription asynchronously (in a background daemon thread, same pattern already used by the silence monitor) immediately after the recording is saved, without blocking the UI or preventing a new recording from starting.
- Add a new menu item "Parar e não transcrever" that stops and saves the recording exactly like today, skipping transcription entirely.
- Add a `transcribe` CLI handler (`handler_transcribe`) so transcription can also be invoked manually against an existing `.wav` file, independent of the menu bar app.
- Update the menu bar icon to reflect two independent, combinable states — recording and transcribing — since a new recording can now start while a previous one is still being transcribed (e.g. idle 🎤, recording 🔴, transcribing ⏳, both 🔴⏳). No count is shown, only presence/absence of each state.
- Show a confirmation alert on "Sair" if one or more transcriptions are still in progress, letting the user choose whether to quit anyway (losing in-progress transcription output; the source `.wav` is never deleted, so it can be reprocessed later).
- The original `.wav` recording is never deleted or renamed by the transcription step, regardless of success or failure.
- Add `python-slugify` as a new dependency, used to build output filenames from the generated title.

## Capabilities

### New Capabilities
- `transcription`: audio-to-text transcription and LLM-generated summary/title for a completed recording, including chunking for long audio, YAML-based configuration, and Markdown output files.

### Modified Capabilities
- `menubar-app`: the "Parar" action now triggers async transcription by default, a new "Parar e não transcrever" menu item is added, the icon gains a transcribing state combinable with the recording state, and "Sair" gains a confirmation alert when transcriptions are in progress.

## Impact

- New file: `meet_recorder/transcriber.py`.
- New file: `meet_recorder/config.py` (or similar) to load/validate `~/.config/meet-recorder/config.yaml`.
- Modified: `meet_recorder/menubar.py` (new menu item, combinable icon states, quit confirmation, background thread trigger on stop).
- Modified: `meet_recorder/handlers.py` (new `handler_transcribe`).
- New dependency: `python-slugify` (pyproject.toml, poetry.lock).
- New runtime dependency: `ffmpeg` binary must be present on `PATH` (documented in README, not bundled).
- New user-level file: `~/.config/meet-recorder/config.yaml` (not part of the repo).
- No changes to `meet_recorder/recorder.py` (audio capture itself is untouched).
