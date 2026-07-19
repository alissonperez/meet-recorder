## Context

`transcriber.py` already has one enrichment path: `_event_context(event)`
builds a small text block (title + attendees) that gets prepended to the
summary's user content when a calendar event matched
(`_generate_summary`). Nothing else touches the event. The STT request
(`_transcribe_chunk`) sends `config.transcription_prompt` verbatim with no
awareness of the matched event, even though `_transcribe_audio`/`transcribe`
already have the `event` object in scope at the point they're called. The
event's `description` (the Google Calendar event body — agenda, links,
context) is never read out of the API response at all: `_extract_event` in
`calendar.py` builds `CalendarEvent` from `title`, `start`/`end`,
`attendees` — no `description`.

Prompts themselves (the three `*_prompt` config values) stay user-owned
YAML strings in `config.yaml` — this change does not touch that config
contract. What changes is the dynamic context appended to them at request
time, and specifically what that context now includes.

## Goals / Non-Goals

**Goals:**
- Extract `description` from the Google Calendar API event payload into
  `CalendarEvent`.
- Reuse a single event-context builder for both the summary prompt (already
  wired) and the transcription/STT prompt (newly wired), so the two stay
  consistent and there's one place to change the format later.
- Document the three prompts and their dynamic context in
  `docs/prompts.md`, including a real frontmatter example, so the doc is a
  reliable reference instead of the prompts only existing as
  `config.example.yaml` comments.

**Non-Goals:**
- No change to title generation. The existing shortcut (event match → use
  `event.title` directly, skip the title LLM call) stays as-is per
  explicit decision — see Open Questions resolution below. Event data is
  therefore never threaded into `title_prompt`.
- No change to the `config.yaml` schema — no new required/optional fields,
  no new prompt slot for "description-only" content.
- No change to frontmatter output fields (`calendar`, `event_start`,
  `event_end`, `attendees`) — `description` is not added to frontmatter,
  only to LLM/STT input context. (Frontmatter already omits it and nothing
  in the proposal asks for it there.)

## Decisions

**1. Add `description` to `CalendarEvent`, sourced from `event.get('description')` in `_extract_event` (`calendar.py`).**
The Google Calendar API already returns this field on `events.list`
results; it's just never read. Default to `None`/absent when the API omits
it (matches how `attendees` already degrades to `[]`).

**2. Generalize `_event_context` into the shared builder for both summary and transcription, adding a description line.**
`_event_context(event)` currently returns:
```
Título da reunião: {title}
Participantes: {attendees}
```
Extend it to conditionally add a description line (only when present,
same pattern as the existing `if event.attendees:` check):
```
Título da reunião: {title}
Descrição: {description}
Participantes: {attendees}
```
This function is reused as-is for transcription — no second formatter.

**3. Thread event context into the STT prompt via the `prompt` hint field, not a separate API parameter.**
The `/audio/transcriptions` endpoint (OpenAI-compatible) only accepts a
single free-text `prompt` hint. `_transcribe_chunk`/`_transcribe_audio`
need an `event` parameter threaded through from `transcribe()` (mirroring
how `_generate_summary` already receives `event`), and when present,
`_event_context(event)` is prepended to `config.transcription_prompt`
before it's sent — same shape as how summary's `user_content` is built
today (`_event_context(event) + transcript_text`).

Edge case on the existing guard: today `_transcribe_chunk` only sets
`payload['prompt']` when `config.transcription_prompt` is truthy. With an
event present there is context worth sending even if the user configured
no `transcription_prompt`, so the guard becomes: set `prompt` when there
is event context **or** a non-empty `transcription_prompt`; when `event`
is `None`, the behavior is exactly as before (prompt only when
`transcription_prompt` is truthy). This keeps the no-match path
byte-for-byte identical to prior behavior.

`event` is threaded as a keyword arg defaulting to `None` on both
`_transcribe_chunk` and `_transcribe_audio`, so the change is additive and
no existing internal caller is forced to pass it.

**4. Title generation is unchanged (explicit decision).**
Considered making the title LLM call always run — using event context to
produce a better title than a generic calendar summary like "Sync" or
"Daily" — but this is a bigger behavior change (removes the existing
short-circuit, changes the `transcription` spec's Title generation
requirement, changes output naming behavior for every event-matched
recording) and was explicitly declined in favor of keeping current
behavior. If wanted later, it's a separate, standalone change.

**5. New `docs/prompts.md`, not a README section or an `openspec/specs/` file.**
`openspec/specs/` holds structured requirement/scenario specs, not
human-readable prompt reference docs, and this needs to be a living doc a
human updates whenever prompt-related code changes — not spec-formatted.
The "keep it updated" rule itself lives as a contribution checklist item in
`CLAUDE.md` (a process rule), not as a spec scenario.
README already documents *where* prompts are configured
(`config.yaml`); `docs/prompts.md` documents *what* each prompt does, what
dynamic context is added to it and when, and shows a real frontmatter
example (format: `title`, `calendar`, `event_start`, `event_end`,
`attendees` — matching `_frontmatter()` in `transcriber.py`). This is a new
`docs/` directory in the repo (none exists yet); root-level ad hoc docs
(`pipeline-transcricao.md`, etc.) are not a convention worth extending.

## Risks / Trade-offs

- **STT prompt hints have limited effect on some models.** The
  `/audio/transcriptions` `prompt` field is a soft bias, not a hard
  instruction — appending a title/description/attendee block may or may
  not measurably improve transcription of names/jargon depending on
  `transcription_model`. → Non-fatal either way: worst case it's inert
  extra context, same non-goal-breaking risk profile as the existing
  summary enrichment.
- **Very long event descriptions bloating the STT prompt.** A Google
  Calendar description can be long (multi-paragraph agenda, pasted links).
  → No truncation is introduced in this change; if this proves to be a
  problem in practice, truncation can be added to `_event_context` later
  without changing its call sites.
- **Docs drift again.** A hand-maintained `docs/prompts.md` can go stale
  the same way the prompts have been undocumented until now. → Mitigated
  only by convention: a contribution checklist item in `CLAUDE.md` calls
  for updating `docs/prompts.md` in any change that alters prompt context.
  No automated enforcement is in scope here, and this is deliberately a
  process rule rather than a spec requirement.

## Testing

The repo has a `pytest` suite (`tests/`), including `tests/test_transcriber.py`
and `tests/test_calendar.py` that already cover `_event_context`,
`_extract_event`, and the `transcribe()` pipeline. This change both extends
that coverage and must update two existing fixtures the signature/attribute
changes would otherwise break:

- **`_event()` helper (`tests/test_transcriber.py`)** — a `SimpleNamespace`
  with no `description` attribute. `_event_context` reading `event.description`
  would raise `AttributeError` for every test using it. The helper gains a
  `description` field (and Decision 2's `getattr` fallback is the defensive
  belt-and-suspenders for any other event-like object).
- **`_transcribe_audio` stubs (`tests/test_transcriber.py`)** — three tests
  monkeypatch `_transcribe_audio` with `lambda m, c:`; once `transcribe()`
  calls it with a third `event` arg these raise `TypeError`. They must accept
  the new arg.

New coverage: `_extract_event` description extraction (present/absent),
`_event_context` description line (present/absent), `_transcribe_chunk`
prompt enrichment (event vs. no-event), and `_transcribe_audio` threading
`event` to chunks. See `tasks.md` sections 5–6.

## Open Questions

None outstanding — the title-generation question was raised and resolved
during proposal (decision: keep existing shortcut, no LLM title call added
for event-matched recordings; see Decision 4).
