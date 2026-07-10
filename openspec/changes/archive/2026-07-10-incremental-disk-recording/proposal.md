## Why

Today `meet_recorder/recorder.py` buffers the entire meeting's audio in memory (two growing Python lists of numpy arrays, one per source) and only writes the WAV file once the recording is stopped. For a ~2h meeting this holds roughly 1.3GB+ of raw audio in RAM, with an additional temporary peak at stop time from `np.concatenate` and the stereo interleave. Worse, if the process crashes, is killed, or the machine sleeps during the meeting, the entire recording is lost — there is no partial data on disk. This change moves audio capture to incremental disk writes so long recordings use bounded memory and survive a mid-recording crash with (at most) a few unflushed seconds of loss.

## What Changes

- Audio callbacks (`mic_callback`, `sys_callback`) stop appending to unbounded in-memory lists. Instead, each pushes captured frames onto a small in-memory queue.
- A dedicated writer thread per source drains its queue and writes frames incrementally to a mono WAV file on disk (via `soundfile.SoundFile` in write mode), so disk I/O never runs on the real-time audio callback thread.
- `stop_recording_and_save` no longer concatenates full in-memory arrays. It stops the streams, drains and closes the writer threads/files, then merges the two mono WAV files into the final stereo WAV by reading and writing in fixed-size blocks (streaming merge), so peak memory is bounded regardless of recording length.
- The silence monitor (`_silence_monitor_loop`) stops reading from the full `sys_frames` history and instead reads from a small bounded rolling buffer (covering only the last `SILENCE_WINDOW_SECONDS`) fed by the same callback, decoupling silence detection from the full-recording buffer that is being removed.
- The two per-source mono WAV files are written to a temporary location and removed after a successful merge into the final stereo file.
- **BREAKING**: none for external callers — `start_recording()` / `stop_recording_and_save()` keep the same signatures and return the same kind of result (path to the final stereo `.wav`). Internal `_state` shape changes (frames lists replaced by queues/writer handles), which only matters to code that reached into `_state` directly (none outside `recorder.py`).

## Capabilities

### New Capabilities
(none — this is a behavior/implementation change to the existing capture pipeline)

### Modified Capabilities
- `audio-capture`: capture no longer buffers full-length audio in memory; frames are written incrementally to per-source temp files during recording and merged into the final stereo WAV at stop time using bounded-memory streaming, instead of one large in-memory concatenate/interleave step. The silence-monitoring requirement now operates on a bounded rolling window instead of the full accumulated history.

## Impact

- `meet_recorder/recorder.py`: core rewrite of the capture/stop/save internals (callbacks, `_state`, `stop_recording_and_save`, `_silence_monitor_loop`).
- No changes expected to `meet_recorder/handlers.py`, `meet_recorder/menubar.py`, or `meet_recorder/transcriber.py` — they consume `recorder.py`'s public functions and the final `.wav` path only.
- New on-disk temp files during recording (per-source mono WAVs) under the recordings directory or a scratch subdirectory; cleaned up on successful stop. Out of scope for this change: recovering those temp files after a crash (tracked separately, see `crash-recovery-idea.md`).
- New runtime dependency: none (uses existing `soundfile`, adds Python stdlib `queue`/`threading`, already used elsewhere in the module).
