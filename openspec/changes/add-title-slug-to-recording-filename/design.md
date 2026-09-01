## Context

See `proposal.md` — Why. Two existing facts shape the approach:

- The `.wav` path is the key of the transcription-retry ledger (`meet_recorder/transcription_retry.py`,
  whose contract is "keyed by the recording's `.wav` path, which the pipeline never renames"), and the
  `transcription` spec requires the source recording to be left unmodified and in place. Both are scoped
  to the *transcription* pipeline: the ledger entry is created only in `menubar._defer_transcription`,
  after `transcriber.transcribe(path)` has already failed — long after the recorder handed the path out.
  So the path must be final by the time `merge_and_cleanup` returns it, but is free to change before that.
- `transcriber._resolve_timestamp` currently `strptime`s the *entire* filename stem against
  `FILENAME_TIMESTAMP_FORMAT` and falls back to the file's mtime on failure. Appending anything to the
  stem silently breaks that parse: transcription would fall back to the merged file's mtime — i.e. the
  *stop* time — which would then drive both calendar matching and the transcript/summary filenames.
  Prefix parsing is therefore not optional polish; it is part of the same change.

The only place a final `.wav` is created is `recorder.merge_and_cleanup`, used by both the normal
stop path (`stop_recording_and_save`) and the orphan-recovery paths in `handlers.py` and `menubar.py`.
It already derives the recording's start timestamp from the in-progress temp directory's name.

## Goals / Non-Goals

**Goals:**
- One creation point for the titled name, so every entry path (stop, orphan recovery) inherits it.
- Bit-for-bit unchanged behavior when no event matches, so nothing regresses for users without calendar.
- Old untitled recordings keep transcribing identically.

**Non-Goals:**
- Renaming or migrating recordings already on disk.
- Generating a title at save time when no calendar event matches. That would need the transcript, which
  does not exist yet; the LLM title stays where it is, in the transcription pipeline.
- Changing transcript/summary naming, which already works.

## Decisions

**Resolve the title inside `merge_and_cleanup`, not at the call sites.**
`merge_and_cleanup` already owns the timestamp→path mapping and is the single funnel for both the stop
path and orphan recovery, so putting the work there means orphan recovery gets titles for free.
Alternative considered: resolve at `start_recording` and thread the title through `_state`. Rejected — it
would miss orphan recovery entirely (the process died, `_state` is gone), and the temp directory name is
already the durable carrier of the start time.

**Merge to the untitled path first, then rename — do not resolve the title before the audio is on disk.**
The order is: merge into `<timestamp>.wav`, remove the temp directory, resolve the title, `os.rename`
within the recordings directory, return whichever path is now current. Titling is a *cosmetic* step and
must never sit between the user pressing Stop and the audio becoming durable. `calendar.find_event` is a
network call: it can be slow, hang, or fail in ways that are hard to enumerate in advance, and none of
those should be able to cost the user a recording. With this order every failure mode after the merge —
lookup error, empty slug, rename error, process killed mid-step — leaves a complete, valid
`<timestamp>.wav`, which is exactly the specified no-title fallback. `os.rename` within one directory is
atomic on macOS, so no observer ever sees a half-named file, and the rename lands before the path is
returned, so the retry ledger's key is stable from the caller's first sight of it.

Alternative considered (and initially chosen): resolve the title first and merge straight into the final
path, avoiding a rename. Rejected — it buys nothing (the ledger's constraint is satisfied either way,
since no entry exists until transcription fails) and it puts a network round-trip in front of the audio
reaching disk, converting any calendar-side fault into a recording that only orphan recovery can save.

**Do not overwrite an existing file when renaming.**
`os.rename` replaces the destination silently on POSIX. A collision needs two recordings that share a
start second *and* an event title, which the second-precision timestamp makes essentially impossible —
but the cost of being wrong is a destroyed recording, so check first and keep the untitled name if the
target exists, rather than relying on the collision never happening.

**Reuse the transcript naming rules verbatim.**
Same ` - ` separator, same `slugify(title, lowercase=False)`, same 80-char cap that
`transcriber._build_base_filename` uses. This is what makes the recording sort next to and read like its
transcript, which is the whole point of the request. The shared slug/truncate step should live in one
place rather than being duplicated in `recorder.py` — extract it so the two names cannot drift apart.

**Keep the timestamp prefix in `FILENAME_TIMESTAMP_FORMAT`, unchanged.**
The recording filename keeps `%Y-%m-%d_%H-%M-%S` — it is *not* switched to the transcript's ISO-ish
display format. Changing it would break `_resolve_timestamp` for every existing file on disk for no user
benefit; the titles are what the user is looking for, not a different date rendering.

**Parse the timestamp from the stem's prefix.**
`_resolve_timestamp` takes the leading fixed-width slice of the stem (or the part before the first ` - `)
and `strptime`s that, falling back to mtime only when the prefix does not parse. Because
`FILENAME_TIMESTAMP_FORMAT` is fixed-width this is unambiguous, and a bare-timestamp stem is just the
case where there is nothing after the prefix — one code path covers both old and new files.
Alternative considered: a regex over the stem. Rejected per project convention — a fixed-width slice plus
`strptime` is both simpler and the parser that already defines the format.

**Calendar failure is never fatal to a save.**
`calendar.find_event` is already documented as non-fatal (logs a warning, returns `None` on any error),
and `config.calendar_enabled` short-circuits it. The naming code treats `None` as "no title" and must not
introduce a new failure mode between the user pressing Stop and the audio reaching disk.

## Risks / Trade-offs

- **A calendar round-trip is added to the stop path** → it runs after the merge, so it delays only the
  returned path, never the audio's durability; the call is already bounded and non-fatal, and it is the
  same lookup transcription performs moments later.
- **The recordings directory briefly contains an untitled file that then changes name** → the window is a
  single `os.rename` and nothing scans that directory (orphan recovery scans only the in-progress
  subdirectory; the retry scan iterates ledger keys, not the filesystem), so no other code path can
  observe the intermediate name.
- **A crash mid-merge still leaves a truncated `.wav`** → unchanged from today's behavior, since the merge
  already writes directly to its destination. Out of scope here.
- **The recording and its transcript can end up with different titles** — the recording is named from the
  calendar event, while a transcript for an unmatched recording is named from an LLM-generated title. This
  is accepted: when calendar matching works both agree, and when it does not the recording simply keeps
  today's untitled name rather than guessing.
- **Two recordings of the same meeting in the same second would collide** → already true today with bare
  timestamps; the title suffix does not make it worse.
- **A title that slugifies to the empty string** (e.g. an all-emoji event title) → treat an empty slug as
  "no title" and fall back to the bare timestamp, rather than emitting a trailing ` - `.

## Migration Plan

None required. The change is additive and backward compatible in both directions: old untitled files still
parse (bare prefix), and new titled files parse via the same prefix logic. No existing file is renamed, so
in-flight retry-ledger entries keep resolving. Rollback is reverting the commit; files saved with titles
while it was deployed continue to transcribe correctly only if the prefix-parsing change is kept, so if a
rollback is ever needed, revert the naming and keep `_resolve_timestamp`'s prefix parsing.
