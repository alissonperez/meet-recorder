import logging
import os
import subprocess
import threading
import time
from datetime import datetime

import numpy as np
import sounddevice as sd
import soundfile as sf

logger = logging.getLogger(__name__)

SAMPLE_RATE = 44100
BLACKHOLE_DEVICE_NAME = 'BlackHole'
SILENCE_CHECK_INTERVAL_SECONDS = 1.0

DEFAULT_RECORDINGS_DIR = '~/MeetRecordings'
DEFAULT_MULTI_OUTPUT_DEVICE_NAME = 'Multi-Output (BlackHole)'
DEFAULT_SILENCE_RMS_THRESHOLD = 0.001
DEFAULT_SILENCE_WINDOW_SECONDS = 30.0

_state = {
    'mic_stream': None,
    'sys_stream': None,
    'mic_frames': [],
    'sys_frames': [],
    'previous_output_device': None,
    'silence_stop_event': None,
    'silence_thread': None,
}


def _recordings_dir():
    return os.path.expanduser(os.environ.get('RECORDINGS_DIR', DEFAULT_RECORDINGS_DIR))


def _multi_output_device_name():
    return os.environ.get('MULTI_OUTPUT_DEVICE_NAME', DEFAULT_MULTI_OUTPUT_DEVICE_NAME)


def _silence_rms_threshold():
    return float(os.environ.get('SILENCE_RMS_THRESHOLD', DEFAULT_SILENCE_RMS_THRESHOLD))


def _silence_window_seconds():
    return float(os.environ.get('SILENCE_WINDOW_SECONDS', DEFAULT_SILENCE_WINDOW_SECONDS))


def _find_default_mic_device():
    device_index, _ = sd.default.device
    if device_index is None or device_index < 0:
        raise RuntimeError('No default microphone input device found')
    return device_index


def _find_blackhole_device():
    for index, device in enumerate(sd.query_devices()):
        if BLACKHOLE_DEVICE_NAME.lower() in device['name'].lower() and device['max_input_channels'] > 0:
            return index
    raise RuntimeError(f'No input device found matching "{BLACKHOLE_DEVICE_NAME}" - is it installed?')


def _get_current_output_device():
    result = subprocess.run(['SwitchAudioSource', '-c'], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _set_output_device(name):
    subprocess.run(['SwitchAudioSource', '-s', name], capture_output=True, text=True, check=True)


def _switch_output_to_multi_output_device():
    try:
        previous_device = _get_current_output_device()
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        logger.error(f'Could not read current output device via SwitchAudioSource: {e}')
        return None

    try:
        _set_output_device(_multi_output_device_name())
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        logger.error(f'Could not switch output device to "{_multi_output_device_name()}": {e}')

    return previous_device


def _restore_output_device(previous_device):
    if not previous_device:
        return

    try:
        _set_output_device(previous_device)
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        logger.error(f'Could not restore output device to "{previous_device}": {e}')


def _rms(frames):
    if len(frames) == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(frames))))


def _silence_monitor_loop(stop_event):
    threshold = _silence_rms_threshold()
    window_seconds = _silence_window_seconds()

    silent_since = None
    warned = False
    last_index = 0

    while not stop_event.wait(SILENCE_CHECK_INTERVAL_SECONDS):
        new_chunks = _state['sys_frames'][last_index:]
        last_index = len(_state['sys_frames'])

        if not new_chunks:
            continue

        level = _rms(np.concatenate(new_chunks, axis=0))
        now = time.monotonic()

        if level <= threshold:
            if silent_since is None:
                silent_since = now
            elif not warned and (now - silent_since) >= window_seconds:
                logger.warning(
                    f'System audio channel (BlackHole) has been silent for over {window_seconds:.0f}s - '
                    'check that system output is routed to the Multi-Output Device'
                )
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


def start_recording():
    if _state['mic_stream'] is not None:
        raise RuntimeError('A recording is already in progress')

    mic_device = _find_default_mic_device()
    sys_device = _find_blackhole_device()

    _state['mic_frames'] = []
    _state['sys_frames'] = []

    def mic_callback(indata, frames, time_info, status):
        _state['mic_frames'].append(indata.copy())

    def sys_callback(indata, frames, time_info, status):
        _state['sys_frames'].append(indata.copy())

    mic_stream = sd.InputStream(
        device=mic_device, samplerate=SAMPLE_RATE, channels=1, dtype='float32', callback=mic_callback,
    )
    sys_stream = sd.InputStream(
        device=sys_device, samplerate=SAMPLE_RATE, channels=1, dtype='float32', callback=sys_callback,
    )

    previous_output_device = _switch_output_to_multi_output_device()

    mic_stream.start()
    sys_stream.start()

    _state['mic_stream'] = mic_stream
    _state['sys_stream'] = sys_stream
    _state['previous_output_device'] = previous_output_device

    _start_silence_monitor()


def stop_recording_and_save():
    if _state['mic_stream'] is None:
        raise RuntimeError('No recording is in progress')

    try:
        _stop_silence_monitor()

        _state['mic_stream'].stop()
        _state['mic_stream'].close()
        _state['sys_stream'].stop()
        _state['sys_stream'].close()

        mic = np.concatenate(_state['mic_frames'], axis=0) if _state['mic_frames'] else np.zeros((0, 1), dtype='float32')
        system = np.concatenate(_state['sys_frames'], axis=0) if _state['sys_frames'] else np.zeros((0, 1), dtype='float32')

        n = min(len(mic), len(system))
        stereo = np.zeros((n, 2), dtype='float32')
        stereo[:, 0] = mic[:n, 0]
        stereo[:, 1] = system[:n, 0]

        path = _build_output_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        sf.write(path, stereo, SAMPLE_RATE, subtype='PCM_16')

        return path
    finally:
        _restore_output_device(_state['previous_output_device'])

        _state['mic_stream'] = None
        _state['sys_stream'] = None
        _state['previous_output_device'] = None


def _build_output_path():
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    return os.path.join(_recordings_dir(), f'{timestamp}.wav')
