## Context

`meet-recorder` currently records microphone + system audio directly to a stereo `.wav` file (`meet_recorder/recorder.py`) and stops there. A previous, separate project (`obs-transcript`, documented in `pipeline-transcricao.md` at the repo root) already solved audio-to-text transcription plus LLM summary generation for OBS `.mov` recordings, batch-processed via cron, with Google Calendar enrichment. That project's STT/LLM logic is reusable; its file-watching, video extraction, and calendar pieces are not — this project already has a `.wav` in hand the moment recording stops, and calendar enrichment is deliberately deferred to a later change.

The menu bar app (`meet_recorder/menubar.py`, `rumps`-based) already runs a background daemon thread for silence monitoring and updates `self.title` / shows `rumps.notification()` from that thread — this is the established (if not strictly AppKit-"safe") pattern in this codebase, and transcription will reuse it rather than introduce subprocess isolation.

## Goals / Non-Goals

**Goals:**
- Transcribe a recording and generate a title + summary automatically after "Parar", without blocking the UI or preventing a new recording from starting.
- Make models, prompts, chunk duration, and output directories user-configurable via YAML, without code changes.
- Keep the OpenRouter API key out of the YAML config, consistent with the project's existing `.env` convention.
- Preserve the source `.wav` unconditionally — transcription is a read-only, retryable operation from the recording's point of view.
- Give the user a way to opt out of transcription per-recording ("Parar e não transcrever").
- Reflect concurrent recording + transcribing state in the menu bar icon.

**Non-Goals:**
- Google Calendar enrichment (title/attendees from an event) — future change.
- Speaker diarization.
- Overlap+dedup stitching across chunk boundaries — chunking replicates the old project's simple non-overlapping split; boundary word loss/truncation is an accepted, pre-existing trade-off.
- Retry/backoff logic for failed API calls beyond a single attempt (title generation keeps its own short retry loop for length, inherited from the old project's approach; STT/summary calls do not retry).
- Persisting a queue or history of past transcriptions — each recording's transcription is a one-shot, fire-and-forget operation.
- Process isolation (subprocess) for transcription — runs as an in-process daemon thread instead.

## Decisions

### 1. In-process daemon thread, not a subprocess
Transcription runs as a `threading.Thread(daemon=True)` started right after `recorder.stop_recording_and_save()` returns, mirroring the existing silence-monitor thread. A subprocess would isolate crashes further, but adds process-lifecycle and IPC complexity (how does the menu bar learn transcription finished? polling `Popen`, a status file, a pipe) for a codebase that already accepts thread-based background work and where transcription failures are logged + surfaced via `rumps.notification()` rather than expected to be fatal.

### 2. Concurrency model: counter, not a boolean
Because a new recording can start while a previous transcription is still running, menu bar state is `(is_recording: bool, active_transcriptions: int)` instead of a single "busy" flag. Each transcription thread increments `active_transcriptions` on start and decrements it (updating the icon) in a `finally` block on exit, success or failure. The icon is a pure function of both values:

| `is_recording` | `active_transcriptions` | icon |
|---|---|---|
| False | 0 | 🎤 idle |
| True | 0 | 🔴 recording |
| False | >0 | ⏳ transcribing |
| True | >0 | 🔴⏳ both |

No count is displayed (max realistic concurrency is ~2; the user explicitly doesn't want a number). Increment/decrement of a plain `int` is safe under the GIL for this access pattern (single writer per thread, no compound read-modify-write races that matter at this scale), so no additional lock is introduced beyond what already guards `recorder._state`.

### 3. Config split: YAML for settings, `.env` for secrets
`~/.config/meet-recorder/config.yaml` holds everything that is not a secret: model ids (transcription, summary, title — independently configurable, since the old project already varied them), the three prompts as inline strings, `transcript_dir`, `summary_dir`, chunk duration, and `base_url` (defaults to OpenRouter's). `OPENROUTER_API_KEY` stays in `.env`, loaded the same way every other handler already expects (`load_dotenv()` in `main.py`). This avoids a secret ending up in a file that's more likely to be copied, backed up, or shared for debugging than `.env` already is.

### 4. STT via raw `httpx`, LLM calls via the `openai` SDK
Preserved from the old project: the OpenRouter `/audio/transcriptions` endpoint takes a JSON body with base64-encoded audio (`{"model": ..., "input_audio": {"data": ..., "format": "mp3"}, "language": "pt"}`), not the multipart form the `openai` SDK's audio client sends — so STT goes through `httpx` directly. Title and summary generation are plain `chat.completions` calls and use the `openai` SDK with `base_url` pointed at OpenRouter, since that's fully compatible. Neither of these choices is Google-specific; they're OpenRouter endpoint-shape decisions independent of which underlying model is configured.

### 5. Title and summary are separate LLM calls
Kept as two independent calls (rather than merging into one prompt) specifically so a future calendar-integration change can substitute "use the event title" for the title call without touching the summary call or its prompt.

### 6. Audio preprocessing: ffmpeg downmix + compress before STT
The recorder's `.wav` is stereo (mic on one channel, system audio on the other) and uncompressed. Before STT, `ffmpeg` downmixes to mono and encodes to a low-bitrate mp3 (mirroring the old project's `acodec=libmp3lame`, `audio_bitrate=32k`, `ac=1`, `ar=16000`), which shrinks the base64 JSON payload substantially. Downmixing to mono is safe because STT here never attempted diarization anyway (both projects instruct the summary prompt not to attribute speech to specific people). This adds a new runtime dependency on the `ffmpeg` binary being present on `PATH` — acceptable since audio-focused setups (this project already depends on `BlackHole`/`SwitchAudioSource`) commonly have it, and it's documented in the README rather than bundled.

### 7. Chunking: fixed-duration, non-overlapping, duration configurable
Audio longer than a configured duration (default 7 minutes, matching the old project's empirically-found `gpt-4o-transcribe` truncation point) is split via `ffmpeg -ss/-t` into sequential, non-overlapping chunks, each transcribed independently and concatenated with `\n`. No overlap/dedup stitching is implemented — see Non-Goals.

### 8. Output layout mirrors the old project
`transcript_dir/YYYY-MM/TIMESTAMP - Titulo-Slug.md` and `summary_dir/YYYY-MM/TIMESTAMP - Titulo-Slug.md`, using `python-slugify` (new dependency) on the generated title, capped and slugified the same way (`slugify(title, lowercase=False)[:80]`). Frontmatter is minimal (no calendar fields available yet) — just enough structure (e.g. a title field) to stay consistent with the eventual calendar-enriched format so that change doesn't need to redesign the file shape.

### 9. Menu bar changes
- New menu item "Parar e não transcrever" calls `recorder.stop_recording_and_save()` and returns without starting a transcription thread.
- Default "Parar" calls the same save, then starts the transcription thread.
- "Sair" checks `active_transcriptions > 0` and shows a `rumps.alert()` confirmation ("N transcrição(ões) em andamento — sair mesmo assim?") before quitting; declining leaves the app running. The in-progress `.wav` is never deleted either way, so a lost transcription is always re-runnable via the `transcribe` CLI handler.

### 10. New CLI handler
`handler_transcribe(path, verbose=False, dryrun=False)` in `handlers.py`, using the existing `@handler` decorator (async-aware, since transcription is naturally a coroutine-friendly I/O-bound flow — though the underlying `transcriber` module's public function can be plain `async def` and let `@handler`'s `asyncio.run()` drive it). This lets transcription be triggered manually against any `.wav`, independent of the menu bar app, and is also what the menu bar's background thread calls into.

## Risks / Trade-offs

- **Chunk-boundary word loss** (no overlap/dedup) → Accepted trade-off, matches the proven old-project behavior; revisit only if it proves to matter in practice.
- **Thread-based icon/notification updates from a background thread are not strictly AppKit-safe** → Mitigation: this pattern is already in production use via the silence monitor; no new risk class introduced.
- **`ffmpeg` missing from `PATH`** → Transcription thread catches the failure, logs it, shows a `rumps.notification()` error, decrements the counter, and leaves the `.wav` untouched for manual retry once `ffmpeg` is installed.
- **Config file missing or malformed on first run** → Loading fails fast with a clear error surfaced via notification; no silent partial-config fallback. (Exact validation behavior can be refined during implementation.)
- **Two simultaneous transcriptions competing for API rate limits** → Not mitigated in this change; acceptable given realistic max concurrency (~2) called out by the user.

## Migration Plan

No data migration. First run requires the user to create `~/.config/meet-recorder/config.yaml` (a documented example/template ships in the repo, e.g. `config.example.yaml`, mirroring the existing `.env.example` pattern) and to have `ffmpeg` installed. Existing recordings already on disk are unaffected and can be transcribed manually via the new `transcribe` CLI handler at any time.

## Open Questions

- Exact YAML schema field names and validation strictness (e.g. required vs. optional fields, defaults) — to be finalized during implementation, guided by the example config file.
- Whether `handler_transcribe` should accept an already-known title (to skip the title LLM call) for future calendar integration, or whether that's better left entirely to the future change — leaning toward leaving it out now to avoid speculative API surface.
