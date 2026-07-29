## 1. Calendar event data

- [x] 1.1 Add `description` parameter/attribute to `CalendarEvent.__init__` in `meet_recorder/calendar.py`, defaulting to `None` (keyword arg) so existing constructor call sites and callers that don't pass it keep working
- [x] 1.2 Read `event.get('description')` in `_extract_event` and pass it through to `CalendarEvent`

## 2. Shared event-context builder

- [x] 2.1 Extend `_event_context(event)` in `meet_recorder/transcriber.py` to add a description line (only when `event.description` is present), keeping the existing title/attendees lines. Access description defensively (e.g. `getattr(event, 'description', None)`) so any event-like object without the attribute is treated as "no description"

## 3. Transcription (STT) prompt enrichment

- [x] 3.1 Thread `event` through `_transcribe_audio` and `_transcribe_chunk` (mirroring how `_generate_summary` already receives `event`), as a keyword arg defaulting to `None`
- [x] 3.2 In `_transcribe_chunk`, when `event` is not `None`, prepend `_event_context(event)` to `config.transcription_prompt` and set the resulting string as the `prompt` payload field. The `prompt` field must be sent when there is event context to send even if `config.transcription_prompt` is empty/falsy; when `event` is `None`, preserve the current guard (only set `prompt` when `config.transcription_prompt` is truthy)
- [x] 3.3 Update the `transcribe()` call site to pass `event` into `_transcribe_audio`

## 4. docs/prompts.md

- [x] 4.1 Create `docs/prompts.md` documenting the transcription, summary, and title prompts: purpose, dynamic context prepended to each and under what condition, and an example of the output frontmatter (`title`, `calendar`, `event_start`, `event_end`, `attendees`)
- [x] 4.2 Link to `docs/prompts.md` from the README's transcription configuration section

## 5. Update existing tests (regression protection)

- [x] 5.1 Add a `description` field to the `_event()` SimpleNamespace helper in `tests/test_transcriber.py` so events built by the helper carry the new attribute (otherwise `_event_context`/frontmatter tests that use it break on attribute access)
- [x] 5.2 Update the three `_transcribe_audio` stubs in `tests/test_transcriber.py` (`test_transcribe_uses_event_title_and_skips_llm`, `test_transcribe_derives_filenames_and_month_folder_from_start_time_filename`, `test_transcribe_falls_back_to_llm_title_without_event`) from `lambda m, c:` to accept the new `event` arg (e.g. `lambda m, c, e=None:`), matching the new `_transcribe_audio` signature

## 6. New unit tests

- [x] 6.1 `tests/test_calendar.py`: assert `_extract_event` populates `CalendarEvent.description` from the raw event's `description` field, and that it is `None` when the field is absent
- [x] 6.2 `tests/test_transcriber.py`: assert `_event_context` includes the description line when `event.description` is present and omits it when absent (mirroring the existing `test_event_context_includes_title_and_attendees`)
- [x] 6.3 `tests/test_transcriber.py`: assert `_transcribe_chunk` sends a `prompt` payload that begins with the event context (title/description/attendees) when an event is passed, and sends `config.transcription_prompt` as-is (event context absent) when no event is passed — stub the HTTP call so no real request is made
- [x] 6.4 `tests/test_transcriber.py`: assert `_transcribe_audio` threads the `event` through to each chunk (e.g. via a stubbed `_transcribe_chunk` capturing the received `event`)

## 7. Verification

- [x] 7.1 Run `make lint`
- [x] 7.2 Run the test suite (`poetry run pytest`) and confirm existing and new tests pass — 130 passed
- [ ] 7.3 Manually run the `transcribe` CLI against a sample `.wav` with a calendar-matched recording and confirm (via `--verbose` logging or a temporary print) that the STT/summary requests include the event's title, description, and attendees — *deferred: requires a real `.wav`, a valid `OPENROUTER_API_KEY`, and a matching calendar event (not available in this environment)*
- [x] 7.4 Confirm behavior is unchanged (no event context, prompts sent as-is) when no calendar event matches — covered by `test_transcribe_chunk_sends_prompt_as_is_without_event` and `test_generate_summary_without_event_passes_transcript_only`
