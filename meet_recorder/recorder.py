import logging
import os
import queue
import shutil
import threading
import time
from datetime import datetime

import numpy as np
import sounddevice as sd
import soundfile as sf

from meet_recorder import calendar, naming, sck_capture
from meet_recorder.config import load_config

logger = logging.getLogger(__name__)

SAMPLE_RATE = 16000
# Must stay 1 (mono). Requesting channelCount=2 from SCStreamConfiguration produces audibly
# distorted/"robotic" audio on this pyobjc/macOS combination - confirmed by ear across multiple
# sample rates (16kHz and 48kHz) and reproducible with a clean TTS source with no other audio
# playing, so it isn't a quality artifact of real-world audio content. The corruption is present
# independently in each raw channel before any downmixing, so it's not introduced by our own
# processing - requesting native mono directly from ScreenCaptureKit avoids it entirely. See
# design.md (migrate-to-screencapturekit) for the full investigation.
SYS_AUDIO_CHANNELS = 1
SILENCE_CHECK_INTERVAL_SECONDS = 1.0
EARLY_NO_BUFFER_CHECK_SECONDS = 5.0
# The microphone silence check is skipped for this long after start_recording() so opening the
# input device and the user starting to speak don't race a false "microphone is silent" warning.
MIC_SILENCE_GRACE_SECONDS = 5.0
# If no new audio chunk arrives on a channel for this long, its underlying device has likely
# stopped delivering data entirely (e.g. a USB microphone unplugged mid-recording) rather than
# merely gone quiet. The RMS buffer only decays when new (possibly silent) samples are appended,
# so a hard stop like this would otherwise leave it holding pre-disconnect audio forever and
# never read as silent; treating a stale channel as silent closes that gap.
STALE_CHUNK_TIMEOUT_SECONDS = 5.0

DEFAULT_RECORDINGS_DIR = '~/MeetRecordings'
DEFAULT_SILENCE_RMS_THRESHOLD = 0.001
DEFAULT_SILENCE_WINDOW_SECONDS = 30.0

IN_PROGRESS_DIR_NAME = '.in-progress'
TIMESTAMP_FORMAT = '%Y-%m-%d_%H-%M-%S'
# sounddevice delivers frequent small callbacks (blocksize chosen by PortAudio, typically
# well under 50ms); sizing the queue in chunk count rather than seconds, this comfortably
# covers several seconds of buffered audio before a writer thread stall would drop frames.
WRITER_QUEUE_MAXSIZE = 500
MERGE_BLOCK_FRAMES = 16000
# How often the padding thread levels the two channels' frame counts.
PADDING_CHECK_INTERVAL_SECONDS = 0.5
# A channel merely running a little behind (e.g. a chunk still in flight) is not padded until
# the shortfall exceeds this many seconds, so the padder doesn't inflate a channel that is about
# to catch up on its own.
PADDING_TOLERANCE_SECONDS = 1.0


def _default_on_silence_warning(channel):
    pass


def _default_on_silence_recovered(channel):
    pass


# Optional hooks invoked alongside the log warning/recovery when a channel's sustained silence
# state changes. Both receive the affected channel name ('mic' or 'sys'). Default to no-ops so
# the CLI-only path is unchanged; set by menubar.py when running under it.
on_silence_warning = _default_on_silence_warning
on_silence_recovered = _default_on_silence_recovered


class MicResumeFallbackError(RuntimeError):
    '''Raised by resume_mic() when the requested device failed and it fell back to a working
    one; the microphone is already capturing again on the fallback device by the time this
    is raised, so callers should report it without treating the recording as broken.'''

    def __init__(self, requested_device, fallback_device, original_error):
        super().__init__(
            f'Failed to resume microphone on device {requested_device} ({original_error}); '
            f'fell back to device {fallback_device}'
        )
        self.requested_device = requested_device
        self.fallback_device = fallback_device
        self.original_error = original_error


_state = {
    'mic_stream': None,
    'sys_handle': None,
    'mic_queue': None,
    'sys_queue': None,
    'mic_writer_thread': None,
    'sys_writer_thread': None,
    'mic_temp_path': None,
    'sys_temp_path': None,
    'temp_dir': None,
    'mic_silence_buffer': None,
    'mic_silence_buffer_lock': None,
    'sys_silence_buffer': None,
    'sys_silence_buffer_lock': None,
    'silence_stop_event': None,
    'silence_thread': None,
    'first_sys_chunk_received': None,
    'early_check_timer': None,
    'last_chunk_at': None,
    'frame_counts': None,
    'frame_counts_lock': None,
    'padding_stop_event': None,
    'padding_thread': None,
    'mic_callback': None,
    'mic_paused': False,
    'last_mic_device': None,
    'recording_active': False,
}


def _recordings_dir():
    return os.path.expanduser(os.environ.get('RECORDINGS_DIR', DEFAULT_RECORDINGS_DIR))


def _silence_rms_threshold():
    return float(os.environ.get('SILENCE_RMS_THRESHOLD', DEFAULT_SILENCE_RMS_THRESHOLD))


def _silence_window_seconds():
    return float(os.environ.get('SILENCE_WINDOW_SECONDS', DEFAULT_SILENCE_WINDOW_SECONDS))


def _refresh_audio_devices():
    # sd._terminate()/sd._initialize() are private sounddevice calls (pinned sounddevice
    # version in pyproject.toml) that force PortAudio to re-enumerate CoreAudio's current
    # device list, instead of reusing a snapshot cached since process/library startup.
    sd._terminate()
    sd._initialize()


def _find_default_mic_device():
    device_index, _ = sd.default.device
    if device_index is None or device_index < 0:
        raise RuntimeError('No default microphone input device found')
    return device_index


def _rms(frames):
    if len(frames) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(frames))))


def _build_temp_paths():
    timestamp = datetime.now().strftime(TIMESTAMP_FORMAT)
    temp_dir = os.path.join(_recordings_dir(), IN_PROGRESS_DIR_NAME, timestamp)
    return temp_dir, os.path.join(temp_dir, 'mic.wav'), os.path.join(temp_dir, 'sys.wav')


def _writer_loop(file_queue, path):
    with sf.SoundFile(path, mode='w', samplerate=SAMPLE_RATE, channels=1, subtype='PCM_16') as f:
        while True:
            chunk = file_queue.get()
            if chunk is None:
                break
            f.write(chunk)


def _start_writer(file_queue, path):
    thread = threading.Thread(target=_writer_loop, args=(file_queue, path), daemon=True)
    thread.start()
    return thread


def _stop_writer(file_queue, thread):
    if file_queue is None or thread is None:
        return
    file_queue.put(None)
    thread.join()


def _enqueue(file_queue, channel, chunk):
    try:
        file_queue.put_nowait(chunk)
    except queue.Full:
        logger.warning(f'{channel} writer queue is full - dropping an audio frame')
    _increment_frame_count(channel, len(chunk))


def _increment_frame_count(channel, frames):
    with _state['frame_counts_lock']:
        _state['frame_counts'][channel] += frames


def _silence_state_key(channel):
    return f'{channel}_silence_buffer'


def _append_to_silence_buffer(channel, chunk):
    window_seconds = _silence_window_seconds()
    max_samples = int(window_seconds * SAMPLE_RATE)
    buffer_key = _silence_state_key(channel)

    with _state[f'{buffer_key}_lock']:
        buffer = np.concatenate([_state[buffer_key], chunk], axis=0)
        if len(buffer) > max_samples:
            buffer = buffer[-max_samples:]
        _state[buffer_key] = buffer

    _state['last_chunk_at'][channel] = time.monotonic()


def _read_silence_buffer(channel):
    buffer_key = _silence_state_key(channel)
    with _state[f'{buffer_key}_lock']:
        return _state[buffer_key].copy()


_SILENCE_WARNING_TEXT = {
    'sys': (
        'System audio channel has been silent for over {window:.0f}s - '
        'check that Screen Recording permission is granted to this process'
    ),
    'mic': (
        'Microphone channel has been silent for over {window:.0f}s - '
        'try switching the microphone input device'
    ),
}


def _silence_monitor_loop(stop_event):
    threshold = _silence_rms_threshold()
    window_seconds = _silence_window_seconds()
    mic_grace_until = time.monotonic() + MIC_SILENCE_GRACE_SECONDS

    channel_state = {channel: {'silent_since': None, 'warned': False} for channel in ('mic', 'sys')}

    while not stop_event.wait(SILENCE_CHECK_INTERVAL_SECONDS):
        now = time.monotonic()

        for channel, state in channel_state.items():
            if channel == 'mic' and (now < mic_grace_until or _state['mic_paused']):
                continue

            last_chunk_at = _state['last_chunk_at'][channel]
            stale = last_chunk_at is None or (now - last_chunk_at) >= STALE_CHUNK_TIMEOUT_SECONDS

            if stale:
                is_silent = True
            else:
                buffer = _read_silence_buffer(channel)
                if len(buffer) == 0:
                    continue
                is_silent = _rms(buffer) <= threshold

            if is_silent:
                if state['silent_since'] is None:
                    state['silent_since'] = now
                elif not state['warned'] and (now - state['silent_since']) >= window_seconds:
                    logger.warning(_SILENCE_WARNING_TEXT[channel].format(window=window_seconds))
                    on_silence_warning(channel)
                    state['warned'] = True
            else:
                if state['warned']:
                    on_silence_recovered(channel)
                state['silent_since'] = None
                state['warned'] = False


def _start_silence_monitor():
    stop_event = threading.Event()
    thread = threading.Thread(target=_silence_monitor_loop, args=(stop_event,), daemon=True)

    _state['silence_stop_event'] = stop_event
    _state['silence_thread'] = thread

    thread.start()


def _stop_silence_monitor():
    stop_event = _state['silence_stop_event']
    thread = _state['silence_thread']

    if stop_event is not None:
        stop_event.set()

    if thread is not None:
        thread.join(timeout=2)

    _state['silence_stop_event'] = None
    _state['silence_thread'] = None


def _check_early_sys_buffers():
    # timer.cancel() in _stop_early_buffer_check() can't stop a timer that has already fired,
    # so this can run concurrently with (or after) stop_recording_and_save() clearing _state.
    event = _state['first_sys_chunk_received']
    if event is not None and not event.is_set():
        logger.warning(
            f'No system-audio buffers received in the first {EARLY_NO_BUFFER_CHECK_SECONDS:.0f}s of '
            'recording - check that Screen Recording permission is granted to this process'
        )
        on_silence_warning('sys')


def _start_early_buffer_check():
    timer = threading.Timer(EARLY_NO_BUFFER_CHECK_SECONDS, _check_early_sys_buffers)
    timer.daemon = True
    _state['early_check_timer'] = timer
    timer.start()


def _stop_early_buffer_check():
    timer = _state['early_check_timer']
    if timer is not None:
        timer.cancel()
    _state['early_check_timer'] = None


_PADDING_QUEUE_STATE_KEY = {'mic': 'mic_queue', 'sys': 'sys_queue'}


def _level_channels(tolerance_frames=0):
    '''Pads whichever channel has produced fewer frames with zeros through its own queue, so
    both channels stay frame-aligned. A channel behind by no more than tolerance_frames is left
    alone, so a channel that is merely running a little behind isn't inflated ahead of real
    audio that is still in flight.'''
    with _state['frame_counts_lock']:
        counts = dict(_state['frame_counts'])

    target = max(counts.values())
    for channel, count in counts.items():
        shortfall = target - count
        if shortfall > tolerance_frames:
            file_queue = _state[_PADDING_QUEUE_STATE_KEY[channel]]
            zeros = np.zeros((shortfall, 1), dtype='float32')
            _enqueue(file_queue, channel, zeros)


def _padding_loop(stop_event):
    tolerance_frames = int(PADDING_TOLERANCE_SECONDS * SAMPLE_RATE)
    while not stop_event.wait(PADDING_CHECK_INTERVAL_SECONDS):
        _level_channels(tolerance_frames)


def _start_padding_thread():
    stop_event = threading.Event()
    thread = threading.Thread(target=_padding_loop, args=(stop_event,), daemon=True)

    _state['padding_stop_event'] = stop_event
    _state['padding_thread'] = thread

    thread.start()


def _stop_padding_thread():
    stop_event = _state['padding_stop_event']
    thread = _state['padding_thread']

    if stop_event is not None:
        stop_event.set()

    if thread is not None:
        thread.join(timeout=2)

    # Final levelling pass (no tolerance) so the temporary files are frame-aligned before the
    # writers are stopped, covering any shortfall that accrued since the last periodic tick.
    if _state['frame_counts'] is not None:
        _level_channels(tolerance_frames=0)

    _state['padding_stop_event'] = None
    _state['padding_thread'] = None


def start_recording():
    if _state['recording_active']:
        raise RuntimeError('A recording is already in progress')

    _refresh_audio_devices()
    mic_device = _find_default_mic_device()

    temp_dir, mic_temp_path, sys_temp_path = _build_temp_paths()
    os.makedirs(temp_dir, exist_ok=True)

    mic_queue = queue.Queue(maxsize=WRITER_QUEUE_MAXSIZE)
    sys_queue = queue.Queue(maxsize=WRITER_QUEUE_MAXSIZE)

    _state['mic_silence_buffer'] = np.zeros((0, 1), dtype='float32')
    _state['mic_silence_buffer_lock'] = threading.Lock()
    _state['sys_silence_buffer'] = np.zeros((0, 1), dtype='float32')
    _state['sys_silence_buffer_lock'] = threading.Lock()
    _state['first_sys_chunk_received'] = threading.Event()
    _state['last_chunk_at'] = {'mic': None, 'sys': None}
    _state['frame_counts'] = {'mic': 0, 'sys': 0}
    _state['frame_counts_lock'] = threading.Lock()

    def mic_callback(indata, frames, time_info, status):
        if status:
            logger.warning(f'Microphone input status: {status}')
        chunk = indata.copy()
        _enqueue(mic_queue, 'mic', chunk)
        _append_to_silence_buffer('mic', chunk)

    def sys_on_chunk(chunk):
        _state['first_sys_chunk_received'].set()
        _enqueue(sys_queue, 'sys', chunk)
        _append_to_silence_buffer('sys', chunk)

    _state['mic_callback'] = mic_callback

    mic_writer_thread = _start_writer(mic_queue, mic_temp_path)
    sys_writer_thread = _start_writer(sys_queue, sys_temp_path)

    mic_stream = None
    sys_handle = None
    try:
        mic_stream = sd.InputStream(
            device=mic_device, samplerate=SAMPLE_RATE, channels=1, dtype='float32', callback=mic_callback,
        )

        sys_handle = sck_capture.start(sys_on_chunk, sample_rate=SAMPLE_RATE, channels=SYS_AUDIO_CHANNELS)

        mic_stream.start()
    except Exception:
        _stop_writer(mic_queue, mic_writer_thread)
        _stop_writer(sys_queue, sys_writer_thread)
        if mic_stream is not None:
            try:
                mic_stream.close()
            except Exception as e:
                logger.error(f'Error closing mic stream during start_recording failure cleanup: {e}')
        if sys_handle is not None:
            sck_capture.stop(sys_handle)
        shutil.rmtree(temp_dir, ignore_errors=True)
        _state['mic_silence_buffer'] = None
        _state['mic_silence_buffer_lock'] = None
        _state['sys_silence_buffer'] = None
        _state['sys_silence_buffer_lock'] = None
        _state['first_sys_chunk_received'] = None
        _state['last_chunk_at'] = None
        _state['frame_counts'] = None
        _state['frame_counts_lock'] = None
        _state['mic_callback'] = None
        raise

    _state['mic_stream'] = mic_stream
    _state['sys_handle'] = sys_handle
    _state['mic_queue'] = mic_queue
    _state['sys_queue'] = sys_queue
    _state['mic_writer_thread'] = mic_writer_thread
    _state['sys_writer_thread'] = sys_writer_thread
    _state['mic_temp_path'] = mic_temp_path
    _state['sys_temp_path'] = sys_temp_path
    _state['temp_dir'] = temp_dir
    _state['mic_paused'] = False
    _state['last_mic_device'] = mic_device
    _state['recording_active'] = True

    _start_silence_monitor()
    _start_early_buffer_check()
    _start_padding_thread()


def pause_mic():
    '''Stops and closes the current InputStream, leaving the mic queue, writer thread, padding
    thread, and system-audio capture untouched. resume_mic() reopens against a device; the
    padding thread keeps mic.wav frame-aligned with sys.wav for the whole pause.'''
    if not _state['recording_active']:
        raise RuntimeError('No recording is in progress')

    if _state['mic_stream'] is None:
        return

    stream = _state['mic_stream']
    try:
        stream.stop()
    except Exception as e:
        logger.error(f'Error stopping mic stream during pause: {e}')
    try:
        stream.close()
    except Exception as e:
        logger.error(f'Error closing mic stream during pause: {e}')

    _state['mic_stream'] = None
    _state['mic_paused'] = True


def list_input_devices():
    '''Returns the currently available input devices. Only valid while microphone capture is
    paused or has not started - _refresh_audio_devices() calls the private sd._terminate()/
    sd._initialize() pair (see the comment there), which invalidates any open InputStream, so
    this must never be called while _state["mic_stream"] is a live stream.'''
    if _state['mic_stream'] is not None:
        raise RuntimeError('Cannot enumerate input devices while microphone capture is active')

    _refresh_audio_devices()
    return [
        {'index': index, 'name': device['name']}
        for index, device in enumerate(sd.query_devices())
        if device['max_input_channels'] > 0
    ]


def _open_mic_stream(device):
    stream = sd.InputStream(
        device=device, samplerate=SAMPLE_RATE, channels=1, dtype='float32', callback=_state['mic_callback'],
    )
    stream.start()
    return stream


def resume_mic(device=None):
    '''Reopens the InputStream on the given device, falling back to the previously used device
    and then the current default input device when device is None. Restores the same
    mic_callback (and therefore the same mic_queue/mic.wav) used before the pause. If the
    requested device fails to open (e.g. it doesn't support SAMPLE_RATE or mono), falls back to
    the current default device and raises MicResumeFallbackError - the microphone is already
    capturing again by the time that error is raised, so it must be reported, not treated as a
    reason to stop the recording.'''
    if not _state['recording_active']:
        raise RuntimeError('No recording is in progress')

    if _state['mic_stream'] is not None:
        return _state['last_mic_device']

    target_device = device if device is not None else _state['last_mic_device']
    if target_device is None:
        target_device = _find_default_mic_device()

    try:
        mic_stream = _open_mic_stream(target_device)
    except Exception as original_error:
        logger.error(f'Failed to resume microphone on device {target_device}: {original_error}')
        fallback_device = _find_default_mic_device()
        mic_stream = _open_mic_stream(fallback_device)
        _state['mic_stream'] = mic_stream
        _state['mic_paused'] = False
        _state['last_mic_device'] = fallback_device
        raise MicResumeFallbackError(target_device, fallback_device, original_error) from original_error

    _state['mic_stream'] = mic_stream
    _state['mic_paused'] = False
    _state['last_mic_device'] = target_device
    return target_device


def _merge_to_stereo(mic_path, sys_path, output_path):
    with sf.SoundFile(mic_path, mode='r') as mic_file, sf.SoundFile(sys_path, mode='r') as sys_file:
        # Read the rate from the temp file header rather than trusting the module-level
        # SAMPLE_RATE constant, so an orphan recorded before a SAMPLE_RATE change (e.g. a
        # pre-migration 44.1kHz recovery) merges at its own rate instead of a mismatched one.
        samplerate = mic_file.samplerate
        with sf.SoundFile(
            output_path, mode='w', samplerate=samplerate, channels=2, subtype='PCM_16',
        ) as out_file:
            while True:
                mic_block = mic_file.read(frames=MERGE_BLOCK_FRAMES, dtype='float32', always_2d=True)
                sys_block = sys_file.read(frames=MERGE_BLOCK_FRAMES, dtype='float32', always_2d=True)

                n = min(len(mic_block), len(sys_block))
                if n == 0:
                    break

                stereo_block = np.zeros((n, 2), dtype='float32')
                stereo_block[:, 0] = mic_block[:n, 0]
                stereo_block[:, 1] = sys_block[:n, 0]
                out_file.write(stereo_block)

                if len(mic_block) < MERGE_BLOCK_FRAMES or len(sys_block) < MERGE_BLOCK_FRAMES:
                    break


def _apply_meeting_title(path, timestamp):
    '''Renames an already-merged '<timestamp>.wav' to '<timestamp> - <slug>.wav' using the
    calendar event matching the recording's start, and returns the resulting path.

    Titling is cosmetic and runs only once the audio is durably on disk, so it must never cost
    the user a recording: every failure - an unparseable timestamp, no matching event, a title
    that slugifies to nothing, a taken destination, a calendar or rename error - is logged and
    returns `path` unchanged, leaving the complete untitled recording in place.'''
    try:
        start = datetime.strptime(timestamp, TIMESTAMP_FORMAT)
        event = calendar.find_event(start, load_config())
        if event is None:
            return path

        slug = naming.slugify_title(event.title)
        if not slug:
            return path

        titled_path = os.path.join(os.path.dirname(path), f'{timestamp} - {slug}.wav')

        # os.rename() replaces the destination silently on POSIX. A collision needs two
        # recordings sharing a start second *and* a title, but the cost of being wrong is a
        # destroyed recording, so check rather than rely on it never happening.
        if os.path.exists(titled_path):
            logger.warning(f'Not renaming {path} to {titled_path}: destination already exists')
            return path

        os.rename(path, titled_path)
        return titled_path
    except Exception as e:
        logger.warning(f'Could not apply the meeting title to {path}: {e}')
        return path


def merge_and_cleanup(mic_path, sys_path, temp_dir):
    timestamp = os.path.basename(os.path.normpath(temp_dir))
    path = _build_output_path(timestamp)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _merge_to_stereo(mic_path, sys_path, path)

    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)

    # Only now that the audio is complete on disk, and the temp files it came from are gone,
    # is it safe to make a network call for the title.
    return _apply_meeting_title(path, timestamp)


def _teardown_capture():
    try:
        _stop_early_buffer_check()
        _stop_silence_monitor()

        if _state['mic_stream'] is not None:
            try:
                _state['mic_stream'].stop()
            except Exception as e:
                logger.error(f'Error stopping mic stream: {e}')
            try:
                _state['mic_stream'].close()
            except Exception as e:
                logger.error(f'Error closing mic stream: {e}')
        sys_handle = _state['sys_handle']
        stopped_unexpectedly = sys_handle.stopped_unexpectedly if sys_handle is not None else None
        sck_capture.stop(sys_handle)

        # Stop the padder (which performs a final zero-tolerance levelling pass) before the
        # writers, so any shortfall still outstanding is padded before the queues are drained.
        _stop_padding_thread()

        _stop_writer(_state['mic_queue'], _state['mic_writer_thread'])
        _stop_writer(_state['sys_queue'], _state['sys_writer_thread'])

        return _state['mic_temp_path'], _state['sys_temp_path'], _state['temp_dir'], stopped_unexpectedly
    finally:
        _state['mic_stream'] = None
        _state['sys_handle'] = None
        _state['mic_queue'] = None
        _state['sys_queue'] = None
        _state['mic_writer_thread'] = None
        _state['sys_writer_thread'] = None
        _state['mic_temp_path'] = None
        _state['sys_temp_path'] = None
        _state['temp_dir'] = None
        _state['mic_silence_buffer'] = None
        _state['mic_silence_buffer_lock'] = None
        _state['sys_silence_buffer'] = None
        _state['sys_silence_buffer_lock'] = None
        _state['first_sys_chunk_received'] = None
        _state['last_chunk_at'] = None
        _state['frame_counts'] = None
        _state['frame_counts_lock'] = None
        _state['mic_callback'] = None
        _state['mic_paused'] = False
        _state['last_mic_device'] = None
        _state['recording_active'] = False


def stop_recording_and_save():
    if not _state['recording_active']:
        raise RuntimeError('No recording is in progress')

    mic_temp_path, sys_temp_path, temp_dir, stopped_unexpectedly = _teardown_capture()
    path = merge_and_cleanup(mic_temp_path, sys_temp_path, temp_dir)
    if stopped_unexpectedly:
        logger.warning(
            f'Recording saved to {path} but system-audio capture stopped unexpectedly '
            f'partway through ({stopped_unexpectedly}); the file may be truncated.'
        )
    return path


def discard_recording():
    if not _state['recording_active']:
        raise RuntimeError('No recording is in progress')

    _mic_temp_path, _sys_temp_path, temp_dir, _stopped_unexpectedly = _teardown_capture()
    shutil.rmtree(temp_dir, ignore_errors=True)


def _build_output_path(timestamp):
    return os.path.join(_recordings_dir(), f'{timestamp}.wav')


def list_orphan_candidates():
    in_progress_dir = os.path.join(_recordings_dir(), IN_PROGRESS_DIR_NAME)
    if not os.path.isdir(in_progress_dir):
        return []

    return sorted(
        os.path.join(in_progress_dir, name)
        for name in os.listdir(in_progress_dir)
        if os.path.isdir(os.path.join(in_progress_dir, name))
    )


def _is_valid_orphan(orphan_dir):
    mic_path = os.path.join(orphan_dir, 'mic.wav')
    sys_path = os.path.join(orphan_dir, 'sys.wav')

    for path in (mic_path, sys_path):
        try:
            with sf.SoundFile(path, mode='r') as f:
                if len(f) == 0:
                    return False
        except (RuntimeError, OSError):
            return False

    return True


def discard_invalid_orphans(candidates):
    valid_orphans = []
    for candidate in candidates:
        if _is_valid_orphan(candidate):
            valid_orphans.append(candidate)
        else:
            shutil.rmtree(candidate, ignore_errors=True)

    return valid_orphans


def delete_orphan(orphan_dir):
    shutil.rmtree(orphan_dir, ignore_errors=True)
