## 1. Dependencies and config scaffolding

- [x] 1.1 Add `python-slugify`, `pyyaml`, and `httpx` to `pyproject.toml` (check which are not already present) and run `poetry lock`
- [x] 1.2 Add `openai` SDK dependency to `pyproject.toml`
- [x] 1.3 Create `meet_recorder/config.py` that loads and validates `~/.config/meet-recorder/config.yaml` (transcription model, summary model, title model, transcription prompt, summary prompt, title prompt, `transcript_dir`, `summary_dir`, chunk duration, `base_url`), raising a clear error on missing/malformed config
- [x] 1.4 Add `config.example.yaml` at the repo root (or `docs/`) documenting all fields with sensible defaults (OpenRouter `base_url`, 7-minute chunk duration), mirroring the `.env.example` pattern
- [x] 1.5 Document required `OPENROUTER_API_KEY` in `.env.example` (if not already present) and confirm it is never read from `config.yaml`

## 2. Audio preprocessing and chunking

- [x] 2.1 Implement `meet_recorder/transcriber.py::_preprocess_audio(wav_path)` that shells out to `ffmpeg` to downmix to mono and encode to mp3 (low bitrate/sample rate), raising a clear error if `ffmpeg` is not found on `PATH`
- [x] 2.2 Implement `_split_into_chunks(mp3_path, chunk_duration)` using `ffmpeg -ss/-t` to produce sequential, non-overlapping chunk files when audio duration exceeds `chunk_duration`
- [x] 2.3 Handle the single-chunk case (audio shorter than `chunk_duration`) without invoking the chunking path

## 3. Transcription (STT)

- [x] 3.1 Implement `_transcribe_chunk(chunk_path, config)` sending a base64+JSON POST request via `httpx` to `{base_url}/audio/transcriptions` with the configured transcription model and prompt
- [x] 3.2 Implement `_transcribe_audio(mp3_path, config)` that chunks if needed, transcribes each chunk in order, and concatenates the resulting text with `\n`
- [x] 3.3 Propagate transcription request failures as a clear, catchable error (no partial output written on failure)

## 4. Title and summary generation (LLM)

- [x] 4.1 Implement `_generate_title(transcript_text, config)` using the `openai` SDK (`base_url` from config) with the configured title model/prompt, enforcing the 60-character limit with a bounded retry loop and truncation fallback
- [x] 4.2 Implement `_generate_summary(transcript_text, config)` using the `openai` SDK with the configured summary model/prompt, as a single independent call from title generation

## 5. Output persistence

- [x] 5.1 Implement filename construction: timestamp (from the recording) + `slugify(title, lowercase=False)[:80]`
- [x] 5.2 Implement writing the transcript Markdown file to `transcript_dir/YYYY-MM/TIMESTAMP - Title-Slug.md`, creating directories as needed
- [x] 5.3 Implement writing the summary Markdown file to `summary_dir/YYYY-MM/TIMESTAMP - Title-Slug.md`, creating directories as needed
- [x] 5.4 Confirm no step in the pipeline ever deletes, moves, or renames the source `.wav`

## 6. Transcription pipeline entrypoint + CLI

- [x] 6.1 Implement `transcriber.transcribe(wav_path, config=None)` (async) orchestrating steps 2-5, loading config via `meet_recorder/config.py` if not passed in
- [x] 6.2 Add `handler_transcribe(path, verbose=False, dryrun=False)` to `meet_recorder/handlers.py` using the existing `@handler` decorator, calling `transcriber.transcribe`
- [x] 6.3 Manually verify `poetry run python main.py transcribe --path=<existing.wav>` produces both output files

## 7. Menu bar integration

- [x] 7.1 Add `active_transcriptions` counter and `is_recording` state tracking in `menubar.py` (or reuse existing recording-state check)
- [x] 7.2 Add icon constants for transcribing-only and recording+transcribing combined states, alongside existing idle/recording constants
- [x] 7.3 Implement `_refresh_title()` (or extend `_set_recording_state`) as a pure function of `(is_recording, active_transcriptions)` deciding which icon to show
- [x] 7.4 Wire default "Parar" (`on_stop`) to start a `threading.Thread(daemon=True)` running `transcriber.transcribe` after saving, incrementing/decrementing `active_transcriptions` around the call (decrement in a `finally` block) and refreshing the icon at each transition
- [x] 7.5 On transcription thread failure, log the error and show `rumps.notification(...)` describing the failure, without crashing the app
- [x] 7.6 Add new menu item "Parar e não transcrever" that calls `recorder.stop_recording_and_save()` and updates recording state without starting a transcription thread
- [x] 7.7 Update "Iniciar" to remain enabled/callable regardless of `active_transcriptions` (only gated by `is_recording`)
- [x] 7.8 Update `on_quit` to show a `rumps.alert()` confirmation when `active_transcriptions > 0`, only proceeding to quit (after the existing auto-save-on-quit behavior) if the user confirms

## 8. Documentation

- [x] 8.1 Update `README.md` with a "Transcription" section documenting: where `~/.config/meet-recorder/config.yaml` lives, every required/optional field it accepts (transcription/summary/title models, the three prompts, `transcript_dir`, `summary_dir`, chunk duration, `base_url`) and its purpose, that `OPENROUTER_API_KEY` goes in `.env` and never in `config.yaml`, that `ffmpeg` must be installed and on `PATH`, and a reference to `config.example.yaml` as the starting template
- [x] 8.2 Update `README.md`'s menu bar section with the new "Parar e não transcrever" item and the new icon states (transcribing-only, recording+transcribing combined)
- [x] 8.3 Document the new `transcribe` CLI command usage in `README.md`
- [x] 8.4 Add a short note referencing `pipeline-transcricao.md` as prior art / rationale for the STT/LLM approach, if useful for future readers

## 9. Manual verification

- [x] 9.1 Full flow: start recording, "Parar", confirm icon shows transcribing state, confirm both output files appear with correct content and filenames, confirm `.wav` still exists
- [x] 9.2 "Parar e não transcrever": confirm no transcription starts and no output files are written
- [x] 9.3 Start a new recording while a previous transcription is still running: confirm both recording and transcription proceed independently and the combined icon state is shown
- [x] 9.4 Quit while a transcription is in progress: confirm the confirmation alert appears and both "confirm" and "cancel" paths behave as specified
- [x] 9.5 Trigger a failure path (e.g. temporarily rename `ffmpeg` off `PATH`, or use an invalid API key) and confirm a notification is shown, the app keeps running, and the `.wav` is untouched
