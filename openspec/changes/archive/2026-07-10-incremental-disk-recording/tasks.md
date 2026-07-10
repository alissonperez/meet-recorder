## 1. Temp file plumbing

- [x] 1.1 Add a helper to build the per-recording temp directory path (`~/MeetRecordings/.in-progress/<timestamp>/`) and the two per-source mono file paths (`mic.wav`, `sys.wav`) inside it.
- [x] 1.2 Create the temp directory (and recordings dir if needed) when `start_recording()` is called, before opening any streams.

## 2. Per-source writer queue + thread

- [x] 2.1 Replace `_state['mic_frames']` / `_state['sys_frames']` lists with a bounded `queue.Queue(maxsize=N)` per source (size covers a few seconds of audio at the current block size).
- [x] 2.2 Implement a writer thread function that opens a `soundfile.SoundFile` in write mode for its source's mono temp path, loops on `queue.get()`, writes each received frame array, and exits cleanly on a `None` sentinel, closing the file on exit.
- [x] 2.3 Update `mic_callback` / `sys_callback` to `put_nowait` the copied frame onto the corresponding queue instead of appending to a list; on `queue.Full`, drop the frame and log a warning instead of blocking.
- [x] 2.4 Start both writer threads in `start_recording()` after creating the temp files, before `mic_stream.start()` / `sys_stream.start()`, and store thread + queue handles in `_state`.

## 3. Silence monitor on a bounded buffer

- [x] 3.1 Add a bounded rolling buffer (e.g. `collections.deque` trimmed by sample count to `SILENCE_WINDOW_SECONDS`) fed from `sys_callback` alongside the queue `put_nowait`, independent of the writer queue.
- [x] 3.2 Update `_silence_monitor_loop` to compute RMS from the bounded rolling buffer instead of slicing `_state['sys_frames']`.
- [x] 3.3 Verify the silence-warning behavior (`SILENCE_RMS_THRESHOLD`, `SILENCE_WINDOW_SECONDS`) is unchanged from the caller's perspective (same env vars, same warning trigger semantics).

## 4. Stop/save: shutdown ordering and block-wise merge

- [x] 4.1 In `stop_recording_and_save`, stop and close both `sd.InputStream`s first, then push a sentinel onto each writer queue and `join()` both writer threads before proceeding.
- [x] 4.2 Implement a block-wise stereo merge: open both mono temp files for reading, read fixed-size blocks from each with `soundfile.SoundFile.read(frames=BLOCK_SIZE)`, interleave into a stereo block, and write it to the final output `SoundFile` opened at `_build_output_path()`, stopping when either source is exhausted (preserves existing truncate-to-shorter behavior).
- [x] 4.3 Delete the two mono temp files and the per-recording temp directory after a successful merge.
- [x] 4.4 Keep the existing `finally` block behavior (output device restore, `_state` reset) intact, extending it to also reset/clear the new queue and thread handles.

## 5. Verification

- [x] 5.1 Run `poetry run python main.py record --duration=<short>` and confirm the resulting stereo `.wav` is correct (2 channels, expected duration, mic on channel 0, system audio on channel 1).
- [x] 5.2 Run a longer recording (10+ minutes) while observing process memory (e.g. Activity Monitor / `ps`) to confirm it stays flat rather than growing with elapsed time.
- [x] 5.3 Kill the process mid-recording (e.g. `kill -9`) and confirm the per-source temp WAV files on disk contain audio up to (approximately) the kill point, demonstrating bounded data loss instead of total loss.
- [x] 5.4 Confirm the silence warning still logs correctly when the system-audio (BlackHole) channel is silent for longer than `SILENCE_WINDOW_SECONDS`, and does not log when it isn't.
- [x] 5.5 Run `make lint` and confirm it passes.

## 6. Spec sync

- [x] 6.1 Update `openspec/specs/audio-capture/spec.md` per the delta in this change once implementation is verified (handled automatically by `openspec archive` at the end of the change lifecycle).
