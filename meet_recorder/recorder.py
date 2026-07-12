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

from meet_recorder import sck_capture

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

DEFAULT_RECORDINGS_DIR = '~/MeetRecordings'
DEFAULT_SILENCE_RMS_THRESHOLD = 0.001
DEFAULT_SILENCE_WINDOW_SECONDS = 30.0

IN_PROGRESS_DIR_NAME = '.in-progress'
# sounddevice delivers frequent small callbacks (blocksize chosen by PortAudio, typically
# well under 50ms); sizing the queue in chunk count rather than seconds, this comfortably
# covers several seconds of buffered audio before a writer thread stall would drop frames.
WRITER_QUEUE_MAXSIZE = 500
MERGE_BLOCK_FRAMES = 16000


def _default_on_silence_warning():
    pass


# Optional hook invoked alongside the log warning when sustained silence is detected.
# Defaults to a no-op so the CLI-only path is unchanged; set by menubar.py when running under it.
on_silence_warning = _default_on_silence_warning

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
    'silence_buffer': None,
    'silence_buffer_lock': None,
    'silence_stop_event': None,
    'silence_thread': None,
    'first_sys_chunk_received': None,
    'early_check_timer': None,
}


def _recordings_dir():
    return os.path.expanduser(os.environ.get('RECORDINGS_DIR', DEFAULT_RECORDINGS_DIR))


def _silence_rms_threshold():
    return float(os.environ.get('SILENCE_RMS_THRESHOLD', DEFAULT_SILENCE_RMS_THRESHOLD))


def _silence_window_seconds():
    return float(os.environ.get('SILENCE_WINDOW_SECONDS', DEFAULT_SILENCE_WINDOW_SECONDS))


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
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
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


def _enqueue(file_queue, source_name, chunk):
    try:
        file_queue.put_nowait(chunk)
    except queue.Full:
        logger.warning(f'{source_name} writer queue is full - dropping an audio frame')


def _append_to_silence_buffer(chunk):
    window_seconds = _silence_window_seconds()
    max_samples = int(window_seconds * SAMPLE_RATE)

    with _state['silence_buffer_lock']:
        buffer = np.concatenate([_state['silence_buffer'], chunk], axis=0)
        if len(buffer) > max_samples:
            buffer = buffer[-max_samples:]
        _state['silence_buffer'] = buffer


def _read_silence_buffer():
    with _state['silence_buffer_lock']:
        return _state['silence_buffer'].copy()


def _silence_monitor_loop(stop_event):
    threshold = _silence_rms_threshold()
    window_seconds = _silence_window_seconds()

    silent_since = None
    warned = False

    while not stop_event.wait(SILENCE_CHECK_INTERVAL_SECONDS):
        buffer = _read_silence_buffer()

        if len(buffer) == 0:
            continue

        level = _rms(buffer)
        now = time.monotonic()

        if level <= threshold:
            if silent_since is None:
                silent_since = now
            elif not warned and (now - silent_since) >= window_seconds:
                logger.warning(
                    f'System audio channel has been silent for over {window_seconds:.0f}s - '
                    'check that Screen Recording permission is granted to this process'
                )
                on_silence_warning()
                warned = True
        else:
            silent_since = None
            warned = False


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
        on_silence_warning()


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


def start_recording():
    if _state['mic_stream'] is not None:
        raise RuntimeError('A recording is already in progress')

    mic_device = _find_default_mic_device()

    temp_dir, mic_temp_path, sys_temp_path = _build_temp_paths()
    os.makedirs(temp_dir, exist_ok=True)

    mic_queue = queue.Queue(maxsize=WRITER_QUEUE_MAXSIZE)
    sys_queue = queue.Queue(maxsize=WRITER_QUEUE_MAXSIZE)

    _state['silence_buffer'] = np.zeros((0, 1), dtype='float32')
    _state['silence_buffer_lock'] = threading.Lock()
    _state['first_sys_chunk_received'] = threading.Event()

    def mic_callback(indata, frames, time_info, status):
        _enqueue(mic_queue, 'mic', indata.copy())

    def sys_on_chunk(chunk):
        _state['first_sys_chunk_received'].set()
        _enqueue(sys_queue, 'sys', chunk)
        _append_to_silence_buffer(chunk)

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
        _state['silence_buffer'] = None
        _state['silence_buffer_lock'] = None
        _state['first_sys_chunk_received'] = None
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

    _start_silence_monitor()
    _start_early_buffer_check()


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


def merge_and_cleanup(mic_path, sys_path, temp_dir):
    path = _build_output_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _merge_to_stereo(mic_path, sys_path, path)

    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return path


def stop_recording_and_save():
    if _state['mic_stream'] is None:
        raise RuntimeError('No recording is in progress')

    try:
        _stop_early_buffer_check()
        _stop_silence_monitor()

        try:
            _state['mic_stream'].stop()
        except Exception as e:
            logger.error(f'Error stopping mic stream: {e}')
        try:
            _state['mic_stream'].close()
        except Exception as e:
            logger.error(f'Error closing mic stream: {e}')
        sck_capture.stop(_state['sys_handle'])

        _stop_writer(_state['mic_queue'], _state['mic_writer_thread'])
        _stop_writer(_state['sys_queue'], _state['sys_writer_thread'])

        return merge_and_cleanup(_state['mic_temp_path'], _state['sys_temp_path'], _state['temp_dir'])
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
        _state['silence_buffer'] = None
        _state['silence_buffer_lock'] = None
        _state['first_sys_chunk_received'] = None


def _build_output_path():
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
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
