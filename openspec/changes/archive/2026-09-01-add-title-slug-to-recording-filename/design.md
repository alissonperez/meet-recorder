## Context

See `proposal.md` — Why. Four existing facts shape the approach:

- `transcriber.transcribe(wav_path, config)` is the single funnel for every entry point: the menu
  bar's stop flow, its crash-recovery action, its deferred-retry scan, and both CLI paths
  (`handler_transcribe`, `handler_recover`). It already ends by writing the transcript and summary
  and returning a dict of their paths.
- The deferred-retry ledger is keyed by the `.wav` path, but an entry exists **only after a failure**
  (`menubar._defer_transcription`, reached from `transcribe`'s except branch). On the success path
  there is no entry to invalidate. `menubar._transcribe_recording` calls
  `transcription_retry.mark_done(path, ...)` with the path it was *given* — which is exactly the key
  the entry was created under — so a rename inside `transcribe` leaves that call correct as written.
- `transcriber._resolve_timestamp` currently `strptime`s the *entire* filename stem against
  `FILENAME_TIMESTAMP_FORMAT` and falls back to the file's mtime on failure. Appending a title to the
  stem silently breaks that parse: a later re-run would fall back to the merged file's mtime — i.e.
  the *stop* time — which would then drive both calendar matching and the output filenames. Prefix
  parsing is therefore not optional polish; it is part of the same change.
- The recording's timestamp format (`%Y-%m-%d_%H-%M-%S`) and the Markdown outputs' display format
  (ISO-ish) are deliberately different and both already exist on disk in the wild. Only the title
  slug is shared between them.

## Goals / Non-Goals

**Goals:**
- One rename point, so every caller — menu bar, retry scan, both CLI paths — behaves identically.
- The rename cannot turn a successful run into a failed one, or a failed one into a rename.
- Old untitled recordings keep transcribing identically.

**Non-Goals:**
- Changing transcript/summary filenames, or the recording's timestamp format. Neither moves.
- Renaming or migrating recordings already on disk. There is no backfill.
- Renaming on the failure path, or partially — a run that did not write both outputs renames nothing.
- Reworking the retry ledger to track renames. It needs no change; see the Decisions below.
- Naming the recording at save time. See the first decision.

## Decisions

**Apply the title once, at the end, instead of at save time.**
The alternative — and the first version of this change — resolved the calendar event inside
`recorder.merge_and_cleanup` and named the `.wav` as it was saved. Rejected on three counts: it put a
network round-trip (`calendar.find_event`) in the stop path, where nothing should stand between the
user pressing Stop and the audio becoming durable; it produced a *provisional* title that the
transcription pipeline could supersede minutes later with the one it actually used, so the two could
disagree; and it needed its own guard against a calendar fault costing a recording. Doing it after a
successful transcription costs nothing extra — the run has already resolved the event and generated
the title — and the name it writes is final.
The trade-off is that a recording which never completes a transcription keeps its bare timestamp:
"Parar sem transcrever" (`menubar.on_stop_no_transcribe`) and a transcription abandoned after
exhausting its retry budget both leave the file untitled forever. Accepted — those recordings have no
transcript to be found alongside, which is what the titling is for.

**Do the rename inside `transcribe`, as its last statement before returning.**
It is the one place that knows the run succeeded *and* knows the final title, and it is the single
funnel all five entry points already go through. Putting it there means the CLI, the stop flow, crash
recovery, and the retry scan all inherit it with no changes of their own.
Alternative considered: rename in each caller from the returned result. Rejected — five call sites
would each repeat the guard logic, and `handler_transcribe`/`handler_recover` would be easy to
forget, giving the CLI different behavior from the menu bar for no reason.

**Return the recording's current path in `transcribe`'s result dict.**
Add `recording_path` alongside `transcript_path` and `summary_path`. Callers ignore the dict's shape
today, so this breaks nothing, but a caller that later needs the post-rename path does not have to
re-derive it. Deliberately *not* used by `menubar` for `mark_done` — see below.

**Leave `mark_done` on the pre-rename path, and say so in a comment.**
It looks like a bug and is not: the ledger entry was created under the path the retry was started
with, so that is the key that must be cleared. Passing the post-rename path would leave the original
entry in the ledger, where it would be retried until either its budget ran out or a scan noticed the
file missing and pruned it. This is the one non-obvious interaction in the change, so it gets a test
and a comment rather than only a spec line.

**Derive the timestamp prefix from the filename, not from the resolved timestamp.**
The new name is `<the stem's own leading timestamp slice> - <slug>.wav`. It would be simpler to
re-format the `datetime` that `_resolve_timestamp` already returned, but that value falls back to the
file's *mtime* when the stem does not parse — so a recording named `meeting-audio.wav` would be
renamed to a timestamp that was never its start time, inventing data. Instead: if the stem's leading
slice does not parse, skip the rename entirely and leave the file alone.
Alternative considered: rename unparseable files using the mtime timestamp. Rejected — silently
asserting a start time the system does not know is worse than leaving the filename as the user had it.

**Parse the timestamp from the stem's prefix.**
`_resolve_timestamp` takes the leading fixed-width slice of the stem and `strptime`s that, falling
back to mtime only when that slice does not parse. Because `FILENAME_TIMESTAMP_FORMAT` is fixed-width
this is unambiguous, and a bare-timestamp stem is just the case where there is nothing after the
prefix — one code path covers both old and new files.
Alternative considered: a regex over the stem. Rejected per project convention — a fixed-width slice
plus `strptime` is both simpler and the parser that already defines the format.

**Reuse the transcript naming rules verbatim, from one place.**
Same ` - ` separator, same `slugify(title, lowercase=False)`, same 80-char cap that
`_build_base_filename` uses. That shared slug step, and the guarded rename around it, live in a new
`meet_recorder/naming.py` rather than being spelled out inside `transcribe`, so the recording's name
and its transcript's name cannot drift apart.

**Skip the rename when the name is already right.**
With calendar matching the common case is that a re-run produces the same title the file already
carries, so the desired path equals the current path. Comparing first makes the step a no-op there
instead of a rename onto itself, and makes re-running `transcribe` idempotent.

**Do not overwrite an existing file when renaming.**
`os.rename` replaces the destination silently on POSIX. A collision needs two recordings that share a
start second *and* a title, which the second-precision timestamp makes essentially impossible — but
the cost of being wrong is a destroyed recording, so check first and keep the current name if the
target exists, rather than relying on the collision never happening.

**Swallow every failure and still report success.**
By the time the rename runs, the transcript and summary are written and the user's actual output
exists. A rename failure at that point is cosmetic, so it is logged and the result is returned as a
success. Raising instead would be actively harmful under the menu bar: `_transcribe_recording` would
catch it, defer the recording, and retry the whole (expensive, already-completed) pipeline on an
hourly timer, overwriting the outputs each time.

## Risks / Trade-offs

- **A recording that is never transcribed keeps its bare timestamp** → accepted, and covered in the
  first decision above; there is no transcript for it to be found alongside.
- **A recording's name changes under a user who was looking at the folder** → the window is the
  transcription run itself, which the user already knows is asynchronous; the transcript appearing is
  the same signal. Accepted, and it is the point of the change.
- **A `.wav` path a user copied before transcription becomes stale** → previously guaranteed stable.
  Mitigated by renaming only within the same directory and only once per recording; the never-deleted
  guarantee still holds, so the audio is always findable in the recordings folder.
- **An external tool keyed on the `.wav` path** (nothing in this repo is, outside the retry ledger
  already discussed) → out of scope; the withdrawn guarantee is documented in the proposal as the
  breaking part of this change.
- **Re-transcribing an already-titled recording** → the desired name matches the current one, so it
  is a no-op. If the run produces a *different* title (a newly created calendar event, say), the file
  is renamed again, which the spec permits and which keeps audio and transcript in sync.
- **A CLI `transcribe` run renames a recording the menu bar has a deferred entry for** → the entry's
  path no longer exists, so the next scan prunes it, exactly as it already does for a deleted
  recording. Correct outcome via an existing behavior; no new code.
- **Two recordings of the same meeting in the same second would collide** → already true today with
  bare timestamps; the title suffix does not make it worse, and the destination check keeps the
  loser's audio intact.

## Migration Plan

None required. No file already on disk is renamed by deploying this — the rename happens only as part
of a run that succeeds after the change is live, and old untitled files parse via the same prefix
logic as new ones. In-flight retry-ledger entries keep resolving, since nothing renames a recording
whose transcription has not succeeded.

Rollback is reverting the commit. Recordings renamed while it was deployed continue to transcribe
correctly only if the prefix-parsing change is kept, so if a rollback is ever needed, revert the
rename step and keep `_resolve_timestamp`'s prefix parsing.
