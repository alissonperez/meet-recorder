## Context

`meet_recorder/recorder.py` captures two mono audio sources (default mic and BlackHole system-audio) via two independent `sounddevice.InputStream` callbacks. Today each callback just appends its chunk (`indata.copy()`) to an unbounded in-memory list (`_state['mic_frames']` / `_state['sys_frames']`). `stop_recording_and_save` concatenates each list into one array, truncates both to the shorter length, interleaves them into a stereo array, and writes it with `soundfile.write`. A background thread (`_silence_monitor_loop`) also polls `_state['sys_frames']` once a second to detect sustained silence on the system-audio channel.

For long meetings (~2h) this holds >1GB of raw float32 audio in RAM for the whole session, with a further transient spike at stop time, and loses the entire recording if the process dies before `stop_recording_and_save` completes.

Callbacks run on `sounddevice`'s real-time audio thread(s) (PortAudio-managed); blocking that thread with disk I/O risks dropped audio, so writes must happen off that thread.

## Goals / Non-Goals

**Goals:**
- Bound memory usage during recording regardless of meeting duration.
- Make in-progress recordings crash-resilient: at most a few unflushed seconds lost if the process dies mid-recording.
- Preserve the existing public API (`start_recording()`, `stop_recording_and_save()`) and existing external behavior (stereo WAV, mic on channel 0, system audio on channel 1, 44.1kHz, output-device switching, silence warning).
- Keep `_silence_monitor_loop` working without depending on full-history buffers.

**Non-Goals:**
- Crash recovery of an in-progress recording after the process has already died (i.e. resuming/merging leftover temp files after a crash) — tracked separately in `crash-recovery-idea.md`, not built here.
- Sample-accurate synchronization/timestamp alignment between the two sources — current behavior (concatenate + truncate to the shorter stream) is preserved as-is, just restructured to work incrementally.
- Changing the transcription pipeline, menubar app, or CLI handlers.
- Configurable/pluggable storage backends — this only targets local disk via `soundfile`.

## Decisions

**1. Queue + dedicated writer thread per source, not direct writes in the audio callback.**
`sounddevice` callbacks must return quickly; blocking on disk I/O there risks audio glitches. Each callback does a non-blocking `queue.put(indata.copy())` (cheap, bounded work) and returns. A separate `threading.Thread` per source blocks on `queue.get()` and performs the actual `soundfile.SoundFile.write()` call. Two threads (mic, sys) rather than one shared thread/queue, to keep the per-source failure/shutdown logic independent and avoid needing to tag/demux a merged queue.

**2. Two temporary mono WAV files during recording, merged into the final stereo WAV at stop — not a single interleaved file written live.**
Writing a single interleaved stereo file live would require synchronizing arrival of matching frames from two independently-clocked async callbacks in the writer thread, adding real complexity for a benefit (fully live merged file) this change doesn't need. Instead: each source writes its own mono WAV incrementally (`<tmp>/<timestamp>_mic.wav`, `<tmp>/<timestamp>_sys.wav`); at stop, both files are already fully flushed on disk and are merged into the final stereo file by reading fixed-size blocks from each (`soundfile.SoundFile.read(frames=BLOCK_SIZE)`) and writing interleaved stereo blocks until the shorter stream is exhausted — mirroring today's truncate-to-shorter behavior but block-wise instead of loading both fully into RAM. Temp files are deleted after a successful merge.

**3. Temp file location: subdirectory under the recordings dir, not `tempfile.gettempdir()`.**
Keeping temp files under `~/MeetRecordings/.in-progress/<timestamp>/` (mirroring the idea already sketched in `crash-recovery-idea.md`) means they land on the same volume as the final output (cheap to rely on `os.replace`/no cross-filesystem copy concerns) and keeps a future crash-recovery feature able to find them without new configuration. This change creates/removes that directory per recording but does not add any recovery logic for leftovers.

**4. Silence monitor: bounded rolling buffer fed independently, not reading the removed full-history list.**
`_silence_monitor_loop` currently slices `_state['sys_frames'][last_index:]` each tick. Since the full list goes away, the sys-audio callback instead also appends each `indata.copy()` chunk to a small `collections.deque` capped to hold `SILENCE_WINDOW_SECONDS` worth of audio (old chunks evicted automatically via `deque(maxlen=...)` sized in chunks, or trimmed by sample count). The monitor computes RMS over that bounded buffer instead of the full history. This is strictly less memory than today, not more.

**5. Queue writer shutdown ordering.**
On stop: (a) stop/close the `sd.InputStream`s first so no new frames are produced, (b) push a sentinel (`None`) onto each queue, (c) join each writer thread (which drains remaining queued frames, writes them, then exits on the sentinel), (d) close both `SoundFile` handles, (e) run the block-wise merge, (f) delete temp files/directory. This guarantees no frames are dropped between "stream stopped" and "writer thread told to exit."

**6. Bounded queue size with blocking `put`, not unbounded queue.**
An unbounded `queue.Queue` would just reintroduce the original memory-growth problem if the writer thread ever falls behind (e.g. slow disk). Using a bounded `queue.Queue(maxsize=N)` with a blocking `put()` in the callback would risk blocking the real-time thread if the writer stalls. Given `soundfile` writes to a local WAV file are fast relative to audio chunk arrival rate, and this is a known/accepted risk already implicit in using threads for real-time audio, we use a bounded queue sized generously (e.g. a few seconds of audio worth of chunks) with `put_nowait` in the callback and drop-and-log-a-warning as the fallback if it's ever full, rather than risking a callback stall. This trades a theoretical few-hundred-ms of audio loss under extreme disk stall for a guarantee the real-time thread never blocks.

## Risks / Trade-offs

- **[Risk]** Writer thread falls behind and the bounded queue fills up under disk contention → some audio frames dropped for that source. **Mitigation**: size the queue generously (seconds, not milliseconds, of buffered audio), log a warning on drop so it's visible, and rely on local SSD write speed vastly exceeding 44.1kHz mono PCM throughput (~176KB/s) in normal operation.
- **[Risk]** Process crash between "frame written to mono WAV" and "final merge" loses the whole recording just like today, since the merge only happens at `stop_recording_and_save`. **Mitigation**: explicitly out of scope here (see Non-Goals) — the per-source mono files already being on disk during the crash is what makes the follow-up crash-recovery feature possible later, even though this change doesn't implement recovery itself.
- **[Risk]** Two extra threads and a queue per recording increase complexity/failure surface versus simple list append. **Mitigation**: keep the writer thread logic minimal (read queue, write, repeat, handle sentinel) and covered by the existing manual CLI test entrypoint (`record` command) for a real end-to-end check, plus unit-testable in isolation from `sounddevice`.
- **[Risk]** `soundfile.SoundFile` open in write mode for the duration of a 2h recording holds a file handle and internal buffer; behavior under abrupt process kill (`SIGKILL`) may still lose the last unflushed write. **Mitigation**: acceptable per Goals ("at most a few unflushed seconds lost"), a large improvement over total loss today. Could periodically call `.flush()` if stronger guarantees are wanted later — left as an open question below.

## Migration Plan

- No data migration; this only changes in-process behavior of `recorder.py`. No persisted state or file formats change (final output is still a stereo WAV at the same path convention).
- Rollout is a single code change behind no feature flag — `start_recording()`/`stop_recording_and_save()` signatures are unchanged, so `menubar.py` and the CLI handler need no changes.
- Rollback: revert the `recorder.py` change; no data format was altered so no backward-compatibility concern for already-recorded files.
- Manual verification: run the existing `record` CLI command for a short duration and confirm the resulting stereo WAV is correct; then a longer (~10+ minute) run while watching process memory (e.g. `ps`/Activity Monitor) to confirm it stays flat rather than growing, and killing the process mid-recording to confirm the mono temp files survive on disk with audio up to the kill point.

## Open Questions

- Should `SoundFile.flush()` be called periodically (e.g. every N seconds) during writing to reduce the unflushed-data window on an abrupt kill, at the cost of more frequent small disk writes? Left as a follow-up tuning knob, not required for this change's goals.
- Exact bounded-queue size (in seconds of audio) and merge block size — left to implementation/tasks, not a spec-level decision.
