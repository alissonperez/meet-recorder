## Context

`meet_recorder/calendar.py` has a single filtering helper, `_eligible_events`, applied identically by all three event-lookup entry points:

- `find_event` (recording-anchored match, used to enrich a manual recording with calendar metadata)
- `upcoming_events` (drives the live auto-record notification + start-confirmation modal)
- `past_events` (drives Meet-transcript/Gemini-notes ingestion)

`_eligible_events` drops any event with `responseStatus == "declined"` for the user, plus any event matching an ignore-slug. That's correct for the two live/recording-anchored paths — you don't want to be prompted to record, or have a manual recording matched to, a meeting you declined. It's the wrong call for `past_events`: by the time ingestion runs, the meeting already happened and Google Meet may have generated a real transcript/notes doc regardless of stale RSVP state. Today that doc is silently orphaned.

## Goals / Non-Goals

**Goals:**
- `past_events` (and therefore `meet_ingest.ingest_once`) SHALL surface declined events as ingestion candidates.
- `upcoming_events` and `find_event` keep excluding declined events — unchanged behavior.
- Ignore-slug filtering keeps applying uniformly everywhere, including `past_events`.

**Non-Goals:**
- No change to how `attachments_for_occurrence` or `meet_ingest._process_occurrence` decide whether an occurrence actually has anything to ingest — an event with no transcript/Gemini doc still produces nothing, declined or not.
- No new config flag. This isn't behavior worth making toggleable; ingestion is already opt-in via `meet_transcripts.enabled`, and "an actual transcript exists" is already the real gate.

## Decisions

- **Make decline-exclusion a parameter of `_eligible_events` instead of splitting the filter into two functions.** `_eligible_events(events, config, exclude_declined=True)`, defaulting to today's behavior so `find_event`/`upcoming_events` need no change at their call sites. `past_events` passes `exclude_declined=False`.
  - Alternative considered: duplicate the loop into `_eligible_events` and `_eligible_past_events`. Rejected — the two would drift, and the only difference is one boolean check.
  - Alternative considered: filter declines only in the caller (`upcoming_events`/`find_event`) instead of inside `_eligible_events`, leaving `past_events` naturally permissive. Rejected — it inverts the default so a future third caller silently ingests declined events unless it remembers to opt in; keeping decline-exclusion as the default and having `past_events` explicitly opt out is the safer default to extend later.

## Risks / Trade-offs

- [Risk] A declined event that was never actually attended could still have Meet-generated content (e.g., someone else's device autojoined, or Google attaches something unexpected) → **Mitigation**: unchanged downstream gate — `meet_ingest` only writes output when a transcript or Gemini-notes doc is actually attached, so a declined-and-truly-skipped meeting still produces nothing.
- [Risk] None for the live/prompt paths — they're untouched by this change (default `exclude_declined=True` preserved).
