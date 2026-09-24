## Context

`meet_recorder/calendar.py` has a single filtering helper, `_eligible_events`,
applied by all three event-lookup entry points (`find_event`,
`upcoming_events`, `past_events`). It filters on decline status and
ignore-slug, but never checks whether an event is all-day. `_parse_boundary`
parses an all-day event's `date` field into a `datetime` at local midnight,
so it always produces *some* value — there's no signal downstream that the
value is fabricated rather than a real time-of-day.

`_find_event` (used only by `find_event`) builds its `candidates` list from
whatever `_eligible_events` yields for the queried window, computes each
candidate's distance from the recording anchor, and picks the minimum. It
never checks that the winning candidate's parsed start is actually inside
`[time_min, time_max]` — it relies entirely on the Calendar API's own
`timeMin`/`timeMax` filtering. That reliance is correct for timed events
(the API's overlap check is effectively exact at minute granularity) but
wrong for all-day events: the API returns an all-day event whenever the
query window touches that calendar date at all, which is a much coarser
guarantee than "this event starts near the anchor."

Net effect: when a user's only connected account(s) have no real timed
meeting near the recording's start, but do have an all-day entry (holiday,
birthday, reminder, etc.) on that date, `_find_event`'s `candidates` list
ends up with exactly one entry — the all-day event — and `min(candidates,
key=distance)` returns it by default, even though it has no legitimate time
relationship to the recording. This was called out as a risk in the
original calendar-integration design
(`openspec/changes/archive/2026-07-11-integrate-google-calendar/design.md`)
as something to "confirm during implementation" — that confirmation/guard
was never actually added.

## Goals / Non-Goals

**Goals:**
- No lookup (`find_event`, `upcoming_events`, `past_events`) SHALL ever
  treat an all-day event as a real candidate.
- `find_event` SHALL only return a candidate whose parsed start actually
  falls inside the configured match window — it must stop trusting the
  Calendar API's coarser overlap semantics as a stand-in for that check.
- Both fixes are unconditional (no new config/opt-out): there is no
  legitimate scenario where an all-day-marked calendar entry, or an
  out-of-window event, should be selected as "the meeting happening now."

**Non-Goals:**
- No change to `upcoming_events`/`past_events` beyond the shared all-day
  exclusion. Neither does single-winner distance selection the way
  `find_event` does, so the window-containment fix is scoped to
  `_find_event` only.
- No new calendar-ID or per-account calendar-selection config. The report's
  "work calendar not connected" detail is expected behavior — an
  unauthorized account is correctly absent from `config.calendars` — the
  bug is only that the fallback then picks a wrong candidate instead of no
  candidate.
- No change to prompt-context shape or `docs/prompts.md` — this only
  narrows *whether* a match is returned, not what a genuine match contains.

## Decisions

- **Exclude all-day events inside `_eligible_events`, unconditionally.**
  Add `_is_all_day(event)` (`'date' in start and 'dateTime' not in start`
  on `event.get('start', {})`) and drop matching events in the same loop
  that already drops declined/ignore-slug events. Placing it in the shared
  helper protects all three callers with one change, and it's unconditional
  (no `exclude_all_day` parameter like `exclude_declined`) because — unlike
  decline status, which `past_events` legitimately wants to ignore — there
  is no caller for which an all-day event is a valid match.
  - Alternative considered: filter all-day events only inside `_find_event`.
    Rejected — `upcoming_events` (live auto-record prompt) and `past_events`
    (transcript ingestion) are equally exposed to the same spurious-match
    risk and should get the same protection without each caller
    remembering to add it.

- **Enforce window containment as a candidate filter inside `_find_event`,
  not as a post-hoc check on the winner.** Skip an event when building
  `candidates` if its parsed `start` isn't within `[time_min, time_max]`,
  rather than computing distance/tiering first and validating only the
  final pick. Filtering at candidate-construction time keeps `_find_event`'s
  accepted/tentative tiering logic operating only over genuinely
  in-window events, avoiding a class of bug where an out-of-window event
  could still influence tiering (e.g. count as the sole "accepted" event)
  even if a later check would have discarded it as the final answer.
  - Alternative considered: leave `_find_event` untouched and rely solely on
    the all-day exclusion. Rejected — it only fixes today's observed
    symptom; the underlying defect (trusting the API's overlap semantics
    instead of validating window containment) is a broader gap the bug
    report's own analysis identified, and guarding it now is cheap.

## Risks / Trade-offs

- [Risk] A real timed meeting whose Calendar API `dateTime` is stored in a
  form `_parse_boundary` can't parse falls through as "no parseable start"
  today (already handled) — the new window check doesn't change that path,
  since it only runs on events that already produced a parsed `start`.
- [Risk] None for `upcoming_events`/`past_events` — they gain the all-day
  exclusion but keep their existing non-distance-based selection logic
  unchanged.
- [Trade-off] All-day exclusion is unconditional with no config escape
  hatch. If a user genuinely schedules a real meeting as an all-day block
  (uncommon), it would no longer be matchable by any lookup. Accepted: this
  matches how Google Calendar/Meet itself treats all-day entries (no join
  link surfaced the same way), and the existing `ignored_event_slugs`
  mechanism remains available for any per-title exception the other
  direction, though there's no equivalent opt-in for this case.
