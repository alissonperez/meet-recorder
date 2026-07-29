## Why

When a recording is matched to a calendar event, the transcription and summary
LLM calls only receive the event's title and attendee names as context — the
event description (agenda, links, context the organizer wrote) is dropped
entirely, and the transcription (STT) call receives no event context at all,
even though passing meeting subject/participant names as a prompt hint is a
well-known way to improve speech-to-text accuracy for names and jargon. On top
of that, the prompts governing transcription/summary/title output are only
documented as YAML defaults in `config.example.yaml` with no explanation of
what data each one receives or why — new prompt behavior (like this change)
has nowhere authoritative to be recorded, so it drifts out of sync with the
code.

## What Changes

- Add `description` to the calendar event data extracted from the Google
  Calendar API (`CalendarEvent`), alongside the existing `title` and
  `attendees`.
- Extend the summary prompt's event context to include the event description
  (in addition to the title and attendees it already includes).
- Add event context (title, description, attendee names) to the
  transcription (STT) prompt when a calendar event matched the recording,
  passed as the `prompt` hint field on the `/audio/transcriptions` request.
- Title generation is unchanged: when a calendar event matches, the event's
  title is still used directly and the title LLM call is still skipped, so
  event data is not threaded into the title prompt (it's only used when no
  event matches, at which point there's no event data to add).
- Add `docs/prompts.md`, documenting each of the three configurable prompts
  (transcription, summary, title): what each one is for, what dynamic context
  is prepended to it (and when), and an example of the resulting frontmatter
  on output files. Keeping this doc in sync with prompt-related code changes
  is captured as a contribution checklist item in `CLAUDE.md`, not as a spec
  requirement.

## Capabilities

### New Capabilities
(none)

### Modified Capabilities
- `calendar-integration`: event extraction (`CalendarEvent`) gains a
  `description` field sourced from the Google Calendar API event payload.
- `transcription`: the STT request now includes calendar event context
  (title, description, attendees) in its prompt hint when a match exists; the
  summary's event-context prefix now also includes the event description.

## Impact

- `meet_recorder/calendar.py`: `CalendarEvent.__init__`, `_extract_event`.
- `meet_recorder/transcriber.py`: `_transcribe_chunk`, `_transcribe_audio`,
  `_event_context` (shared by summary and transcription prompts).
- `tests/test_transcriber.py`: update the `_event()` helper (add
  `description`) and the three `_transcribe_audio` stubs (new `event` arg)
  to keep existing tests green; add coverage for the new context and
  threading. `tests/test_calendar.py`: add `description` extraction
  coverage.
- `docs/prompts.md`: new file.
- `openspec/specs/calendar-integration/spec.md`,
  `openspec/specs/transcription/spec.md`: requirement deltas.
- No config schema changes — the three prompts remain user-configured
  `config.yaml` strings; only the dynamic context prepended to them changes.
  When an event matches but `transcription_prompt` is empty, the STT
  request now carries the event context alone as its `prompt` hint (see
  design Decision 3); the no-match path is unchanged.
