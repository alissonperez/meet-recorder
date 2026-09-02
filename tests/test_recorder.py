import os
import threading
from unittest.mock import MagicMock

import numpy as np
import pytest
import soundfile as sf

from meet_recorder import recorder

SAMPLE_RATE = recorder.SAMPLE_RATE


def _write_mono_wav(path, samples, samplerate=SAMPLE_RATE):
    with sf.SoundFile(str(path), mode='w', samplerate=samplerate, channels=1, subtype='PCM_16') as f:
        f.write(np.asarray(samples, dtype='float32'))


def test_rms_empty_array_returns_zero():
    assert recorder._rms(np.array([])) == 0.0


def test_rms_known_sample_data():
    frames = np.array([1.0, -1.0, 1.0, -1.0], dtype='float32')

    assert recorder._rms(frames) == pytest.approx(1.0)


def test_merge_to_stereo_interleaves_channels(tmp_path):
    mic_path = tmp_path / 'mic.wav'
    sys_path = tmp_path / 'sys.wav'
    output_path = tmp_path / 'out.wav'

    mic_samples = [0.1, 0.2, 0.3, 0.4]
    sys_samples = [0.9, 0.8, 0.7, 0.6]

    _write_mono_wav(mic_path, mic_samples)
    _write_mono_wav(sys_path, sys_samples)

    recorder._merge_to_stereo(str(mic_path), str(sys_path), str(output_path))

    with sf.SoundFile(str(output_path), mode='r') as f:
        assert f.channels == 2
        data = f.read(dtype='float32', always_2d=True)

    np.testing.assert_allclose(data[:, 0], mic_samples, atol=1e-4)
    np.testing.assert_allclose(data[:, 1], sys_samples, atol=1e-4)


def test_merge_to_stereo_truncates_to_shorter_stream(tmp_path):
    mic_path = tmp_path / 'mic.wav'
    sys_path = tmp_path / 'sys.wav'
    output_path = tmp_path / 'out.wav'

    _write_mono_wav(mic_path, [0.1, 0.2, 0.3, 0.4, 0.5])
    _write_mono_wav(sys_path, [0.9, 0.8])

    recorder._merge_to_stereo(str(mic_path), str(sys_path), str(output_path))

    with sf.SoundFile(str(output_path), mode='r') as f:
        assert len(f) == 2


def test_list_orphan_candidates_returns_empty_when_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setenv('RECORDINGS_DIR', str(tmp_path / 'nonexistent'))

    assert recorder.list_orphan_candidates() == []


def test_list_orphan_candidates_returns_sorted_subdirs(tmp_path, monkeypatch):
    monkeypatch.setenv('RECORDINGS_DIR', str(tmp_path))

    in_progress_dir = tmp_path / recorder.IN_PROGRESS_DIR_NAME
    for name in ('2024-02-01', '2024-01-01'):
        (in_progress_dir / name).mkdir(parents=True)
    (in_progress_dir / 'not-a-dir.txt').write_text('x')

    candidates = recorder.list_orphan_candidates()

    assert candidates == [
        str(in_progress_dir / '2024-01-01'),
        str(in_progress_dir / '2024-02-01'),
    ]


def _make_orphan_dir(base_dir, name, mic_samples=(0.1, 0.2), sys_samples=(0.3, 0.4)):
    orphan_dir = base_dir / name
    orphan_dir.mkdir(parents=True)
    _write_mono_wav(orphan_dir / 'mic.wav', mic_samples)
    _write_mono_wav(orphan_dir / 'sys.wav', sys_samples)
    return orphan_dir


def test_is_valid_orphan_true_for_readable_nonempty_wavs(tmp_path):
    orphan_dir = _make_orphan_dir(tmp_path, 'orphan')

    assert recorder._is_valid_orphan(str(orphan_dir)) is True


def test_is_valid_orphan_false_for_zero_frame_wav(tmp_path):
    orphan_dir = _make_orphan_dir(tmp_path, 'orphan', mic_samples=())

    assert recorder._is_valid_orphan(str(orphan_dir)) is False


def test_is_valid_orphan_false_for_corrupted_wav(tmp_path):
    orphan_dir = tmp_path / 'orphan'
    orphan_dir.mkdir()
    (orphan_dir / 'mic.wav').write_text('not a real wav file')
    (orphan_dir / 'sys.wav').write_text('not a real wav file')

    assert recorder._is_valid_orphan(str(orphan_dir)) is False


def test_discard_invalid_orphans_removes_invalid_and_returns_valid(tmp_path):
    valid_dir = _make_orphan_dir(tmp_path, 'valid')
    invalid_dir = _make_orphan_dir(tmp_path, 'invalid', mic_samples=())

    result = recorder.discard_invalid_orphans([str(valid_dir), str(invalid_dir)])

    assert result == [str(valid_dir)]
    assert os.path.isdir(valid_dir)
    assert not os.path.exists(invalid_dir)


def test_delete_orphan_removes_directory(tmp_path):
    orphan_dir = _make_orphan_dir(tmp_path, 'orphan')

    recorder.delete_orphan(str(orphan_dir))

    assert not os.path.exists(orphan_dir)


def test_merge_and_cleanup_returns_path_and_removes_temp_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('RECORDINGS_DIR', str(tmp_path / 'recordings'))

    temp_dir = tmp_path / 'temp'
    temp_dir.mkdir()
    mic_path = temp_dir / 'mic.wav'
    sys_path = temp_dir / 'sys.wav'
    _write_mono_wav(mic_path, [0.1, 0.2])
    _write_mono_wav(sys_path, [0.3, 0.4])

    output_path = recorder.merge_and_cleanup(str(mic_path), str(sys_path), str(temp_dir))

    assert os.path.isfile(output_path)
    assert not os.path.exists(temp_dir)


def test_merge_and_cleanup_names_output_after_temp_dir_start_timestamp(tmp_path, monkeypatch):
    monkeypatch.setenv('RECORDINGS_DIR', str(tmp_path / 'recordings'))

    start_timestamp = '2026-01-01_10-00-00'
    temp_dir = tmp_path / start_timestamp
    temp_dir.mkdir()
    mic_path = temp_dir / 'mic.wav'
    sys_path = temp_dir / 'sys.wav'
    _write_mono_wav(mic_path, [0.1, 0.2])
    _write_mono_wav(sys_path, [0.3, 0.4])

    output_path = recorder.merge_and_cleanup(str(mic_path), str(sys_path), str(temp_dir) + os.sep)

    assert os.path.basename(output_path) == f'{start_timestamp}.wav'


def test_merge_and_cleanup_uses_start_timestamp_not_stop_time(tmp_path, monkeypatch):
    monkeypatch.setenv('RECORDINGS_DIR', str(tmp_path / 'recordings'))

    start_timestamp = '2026-01-01_10-00-00'
    temp_dir = tmp_path / start_timestamp
    temp_dir.mkdir()
    mic_path = temp_dir / 'mic.wav'
    sys_path = temp_dir / 'sys.wav'
    _write_mono_wav(mic_path, [0.1, 0.2])
    _write_mono_wav(sys_path, [0.3, 0.4])

    class _LaterDatetime:
        @staticmethod
        def now():
            # Simulates a long recording where stop-time wall clock is far past start time.
            from datetime import datetime as real_datetime
            return real_datetime(2026, 1, 1, 23, 0, 0)

    monkeypatch.setattr(recorder, 'datetime', _LaterDatetime)

    output_path = recorder.merge_and_cleanup(str(mic_path), str(sys_path), str(temp_dir))

    assert os.path.basename(output_path) == f'{start_timestamp}.wav'


def test_merge_and_cleanup_names_output_from_orphan_dir_timestamp(tmp_path, monkeypatch):
    # Mirrors the shape used by handler_recover() / menubar crash-recovery: orphan_dir is
    # RECORDINGS_DIR/.in-progress/<start-timestamp>/, and merge_and_cleanup is called with it
    # directly as temp_dir - same function, same fix as the live stop-and-save path.
    recordings_dir = tmp_path / 'recordings'
    monkeypatch.setenv('RECORDINGS_DIR', str(recordings_dir))

    start_timestamp = '2026-02-01_09-15-00'
    orphan_dir = recordings_dir / recorder.IN_PROGRESS_DIR_NAME / start_timestamp
    orphan_dir.mkdir(parents=True)
    mic_path = orphan_dir / 'mic.wav'
    sys_path = orphan_dir / 'sys.wav'
    _write_mono_wav(mic_path, [0.1, 0.2])
    _write_mono_wav(sys_path, [0.3, 0.4])

    output_path = recorder.merge_and_cleanup(str(mic_path), str(sys_path), str(orphan_dir))

    assert os.path.basename(output_path) == f'{start_timestamp}.wav'
    assert not os.path.exists(orphan_dir)


def test_merge_to_stereo_preserves_source_sample_rate_for_pre_migration_orphans(tmp_path):
    mic_path = tmp_path / 'mic.wav'
    sys_path = tmp_path / 'sys.wav'
    output_path = tmp_path / 'out.wav'

    _write_mono_wav(mic_path, [0.1, 0.2, 0.3], samplerate=44100)
    _write_mono_wav(sys_path, [0.4, 0.5, 0.6], samplerate=44100)

    recorder._merge_to_stereo(str(mic_path), str(sys_path), str(output_path))

    with sf.SoundFile(str(output_path), mode='r') as f:
        assert f.samplerate == 44100
        assert f.channels == 2


def test_sys_capture_hooks_default_to_callable_noops():
    recorder.on_sys_capture_interrupted('some error')
    recorder.on_sys_capture_restored()


def test_check_early_sys_buffers_warns_when_no_chunk_received(monkeypatch):
    recorder._state['first_sys_chunk_received'] = threading.Event()
    warning_hook = MagicMock()
    monkeypatch.setattr(recorder, 'on_silence_warning', warning_hook)

    recorder._check_early_sys_buffers()

    warning_hook.assert_called_once()


def test_check_early_sys_buffers_silent_when_chunk_already_received(monkeypatch):
    event = threading.Event()
    event.set()
    recorder._state['first_sys_chunk_received'] = event
    warning_hook = MagicMock()
    monkeypatch.setattr(recorder, 'on_silence_warning', warning_hook)

    recorder._check_early_sys_buffers()

    warning_hook.assert_not_called()


def test_check_early_sys_buffers_noop_when_state_already_cleared(monkeypatch):
    recorder._state['first_sys_chunk_received'] = None
    warning_hook = MagicMock()
    monkeypatch.setattr(recorder, 'on_silence_warning', warning_hook)

    recorder._check_early_sys_buffers()

    warning_hook.assert_not_called()


def test_start_recording_uses_sck_capture_for_system_audio(tmp_path, monkeypatch):
    monkeypatch.setenv('RECORDINGS_DIR', str(tmp_path))
    monkeypatch.setattr(recorder.sd.default, 'device', (0, 0))

    mic_stream = MagicMock()
    monkeypatch.setattr(recorder.sd, 'InputStream', MagicMock(return_value=mic_stream))

    fake_handle = MagicMock()
    sck_start = MagicMock(return_value=fake_handle)
    sck_stop = MagicMock()
    monkeypatch.setattr(recorder.sck_capture, 'start', sck_start)
    monkeypatch.setattr(recorder.sck_capture, 'stop', sck_stop)

    recorder.start_recording()

    sck_start.assert_called_once()
    _, kwargs = sck_start.call_args
    assert kwargs['sample_rate'] == recorder.SAMPLE_RATE
    assert kwargs['channels'] == recorder.SYS_AUDIO_CHANNELS
    mic_stream.start.assert_called_once()
    assert recorder._state['sys_handle'] is fake_handle

    recorder.stop_recording_and_save()

    sck_stop.assert_called_once_with(fake_handle)
    mic_stream.stop.assert_called_once()
    mic_stream.close.assert_called_once()
    assert recorder._state['mic_stream'] is None
    assert recorder._state['sys_handle'] is None


def test_start_recording_forwards_sck_chunks_through_sys_queue(tmp_path, monkeypatch):
    monkeypatch.setenv('RECORDINGS_DIR', str(tmp_path))
    monkeypatch.setattr(recorder.sd.default, 'device', (0, 0))
    monkeypatch.setattr(recorder.sd, 'InputStream', MagicMock(return_value=MagicMock()))

    captured = {}

    def fake_start(on_chunk, sample_rate, channels):
        captured['on_chunk'] = on_chunk
        return MagicMock()

    monkeypatch.setattr(recorder.sck_capture, 'start', fake_start)
    monkeypatch.setattr(recorder.sck_capture, 'stop', MagicMock())

    recorder.start_recording()

    assert recorder._state['first_sys_chunk_received'].is_set() is False
    chunk = np.array([[0.5], [-0.5]], dtype='float32')
    captured['on_chunk'](chunk)
    assert recorder._state['first_sys_chunk_received'].is_set() is True

    recorder.stop_recording_and_save()


def test_start_recording_refreshes_audio_devices_before_finding_mic_device(tmp_path, monkeypatch):
    monkeypatch.setenv('RECORDINGS_DIR', str(tmp_path))
    monkeypatch.setattr(recorder.sd.default, 'device', (0, 0))
    monkeypatch.setattr(recorder.sd, 'InputStream', MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(recorder.sck_capture, 'start', MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(recorder.sck_capture, 'stop', MagicMock())

    call_order = []
    monkeypatch.setattr(recorder.sd, '_terminate', MagicMock(side_effect=lambda: call_order.append('terminate')))
    monkeypatch.setattr(recorder.sd, '_initialize', MagicMock(side_effect=lambda: call_order.append('initialize')))
    find_device_spy = MagicMock(side_effect=recorder._find_default_mic_device)
    monkeypatch.setattr(recorder, '_find_default_mic_device', find_device_spy)

    recorder.start_recording()

    assert call_order == ['terminate', 'initialize']
    find_device_spy.assert_called_once()

    recorder.stop_recording_and_save()


def _spy_on_start_writer(monkeypatch):
    '''Let the real _start_writer/_stop_writer run (so cleanup is genuine), but record the
    threads created so failure-path tests can assert they were actually joined.'''
    threads = []
    original = recorder._start_writer

    def spy(*args, **kwargs):
        thread = original(*args, **kwargs)
        threads.append(thread)
        return thread

    monkeypatch.setattr(recorder, '_start_writer', spy)
    return threads


def test_start_recording_cleans_up_when_sck_capture_start_fails(tmp_path, monkeypatch):
    monkeypatch.setenv('RECORDINGS_DIR', str(tmp_path))
    monkeypatch.setattr(recorder.sd.default, 'device', (0, 0))
    threads = _spy_on_start_writer(monkeypatch)

    mic_stream = MagicMock()
    monkeypatch.setattr(recorder.sd, 'InputStream', MagicMock(return_value=mic_stream))
    monkeypatch.setattr(recorder.sck_capture, 'start', MagicMock(side_effect=RuntimeError('no permission')))
    sck_stop = MagicMock()
    monkeypatch.setattr(recorder.sck_capture, 'stop', sck_stop)
    terminate_spy = MagicMock()
    initialize_spy = MagicMock()
    monkeypatch.setattr(recorder.sd, '_terminate', terminate_spy)
    monkeypatch.setattr(recorder.sd, '_initialize', initialize_spy)

    with pytest.raises(RuntimeError, match='no permission'):
        recorder.start_recording()

    terminate_spy.assert_called_once()
    initialize_spy.assert_called_once()
    assert len(threads) == 2
    assert all(not t.is_alive() for t in threads)
    mic_stream.close.assert_called_once()
    sck_stop.assert_not_called()
    assert recorder._state['mic_stream'] is None
    assert recorder._state['sys_handle'] is None
    assert recorder.list_orphan_candidates() == []


def test_start_recording_cleans_up_when_mic_stream_start_fails(tmp_path, monkeypatch):
    monkeypatch.setenv('RECORDINGS_DIR', str(tmp_path))
    monkeypatch.setattr(recorder.sd.default, 'device', (0, 0))
    threads = _spy_on_start_writer(monkeypatch)

    mic_stream = MagicMock()
    mic_stream.start.side_effect = RuntimeError('PortAudio error')
    monkeypatch.setattr(recorder.sd, 'InputStream', MagicMock(return_value=mic_stream))
    fake_handle = MagicMock()
    monkeypatch.setattr(recorder.sck_capture, 'start', MagicMock(return_value=fake_handle))
    sck_stop = MagicMock()
    monkeypatch.setattr(recorder.sck_capture, 'stop', sck_stop)
    terminate_spy = MagicMock()
    initialize_spy = MagicMock()
    monkeypatch.setattr(recorder.sd, '_terminate', terminate_spy)
    monkeypatch.setattr(recorder.sd, '_initialize', initialize_spy)

    with pytest.raises(RuntimeError, match='PortAudio error'):
        recorder.start_recording()

    terminate_spy.assert_called_once()
    initialize_spy.assert_called_once()
    assert len(threads) == 2
    assert all(not t.is_alive() for t in threads)
    mic_stream.close.assert_called_once()
    sck_stop.assert_called_once_with(fake_handle)
    assert recorder._state['mic_stream'] is None
    assert recorder._state['sys_handle'] is None
    assert recorder.list_orphan_candidates() == []


def test_stop_recording_still_stops_writers_and_merges_when_mic_stream_stop_raises(tmp_path, monkeypatch):
    monkeypatch.setenv('RECORDINGS_DIR', str(tmp_path))
    monkeypatch.setattr(recorder.sd.default, 'device', (0, 0))

    mic_stream = MagicMock()
    mic_stream.stop.side_effect = RuntimeError('device disconnected')
    monkeypatch.setattr(recorder.sd, 'InputStream', MagicMock(return_value=mic_stream))
    monkeypatch.setattr(recorder.sck_capture, 'start', MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(recorder.sck_capture, 'stop', MagicMock())

    recorder.start_recording()

    path = recorder.stop_recording_and_save()

    assert os.path.isfile(path)
    mic_stream.close.assert_called_once()
    assert recorder._state['mic_stream'] is None
    assert recorder._state['sys_handle'] is None


def test_stop_recording_warns_when_sys_handle_stopped_unexpectedly(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv('RECORDINGS_DIR', str(tmp_path))
    monkeypatch.setattr(recorder.sd.default, 'device', (0, 0))
    monkeypatch.setattr(recorder.sd, 'InputStream', MagicMock(return_value=MagicMock()))

    fake_handle = MagicMock()
    fake_handle.stopped_unexpectedly = 'connection interruption'
    monkeypatch.setattr(recorder.sck_capture, 'start', MagicMock(return_value=fake_handle))
    monkeypatch.setattr(recorder.sck_capture, 'stop', MagicMock())

    recorder.start_recording()

    with caplog.at_level('WARNING'):
        path = recorder.stop_recording_and_save()

    assert path in caplog.text
    assert 'stopped unexpectedly' in caplog.text


def test_stop_recording_does_not_warn_on_normal_stop(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv('RECORDINGS_DIR', str(tmp_path))
    monkeypatch.setattr(recorder.sd.default, 'device', (0, 0))
    monkeypatch.setattr(recorder.sd, 'InputStream', MagicMock(return_value=MagicMock()))

    fake_handle = MagicMock()
    fake_handle.stopped_unexpectedly = None
    monkeypatch.setattr(recorder.sck_capture, 'start', MagicMock(return_value=fake_handle))
    monkeypatch.setattr(recorder.sck_capture, 'stop', MagicMock())

    recorder.start_recording()

    with caplog.at_level('WARNING'):
        recorder.stop_recording_and_save()

    assert caplog.text == ''


def test_discard_recording_raises_when_no_recording_in_progress():
    with pytest.raises(RuntimeError, match='No recording is in progress'):
        recorder.discard_recording()


def _start_recording_with_stubs(tmp_path, monkeypatch, mic_stream=None):
    monkeypatch.setenv('RECORDINGS_DIR', str(tmp_path))
    monkeypatch.setattr(recorder.sd.default, 'device', (0, 0))
    mic_stream = mic_stream if mic_stream is not None else MagicMock()
    monkeypatch.setattr(recorder.sd, 'InputStream', MagicMock(return_value=mic_stream))
    fake_handle = MagicMock()
    fake_handle.stopped_unexpectedly = None
    monkeypatch.setattr(recorder.sck_capture, 'start', MagicMock(return_value=fake_handle))
    monkeypatch.setattr(recorder.sck_capture, 'stop', MagicMock())

    recorder.start_recording()

    return mic_stream, fake_handle


# --- Frame-count padding -----------------------------------------------------

def test_dropped_frames_are_padded_to_stay_aligned(tmp_path, monkeypatch):
    _start_recording_with_stubs(tmp_path, monkeypatch)

    # Simulate real audio landing on sys but a dropped frame (queue-full) on mic.
    recorder._increment_frame_count('sys', 1600)
    recorder._level_channels(tolerance_frames=0)

    assert recorder._state['frame_counts']['mic'] == 1600
    assert recorder._state['frame_counts']['sys'] == 1600
    assert recorder._state['mic_queue'].qsize() == 1

    recorder.stop_recording_and_save()


def test_padding_accrues_continuously_not_only_at_resume(tmp_path, monkeypatch):
    _start_recording_with_stubs(tmp_path, monkeypatch)

    recorder._increment_frame_count('sys', 800)
    recorder._level_channels(tolerance_frames=0)
    assert recorder._state['frame_counts']['mic'] == 800

    recorder._increment_frame_count('sys', 400)
    recorder._level_channels(tolerance_frames=0)
    assert recorder._state['frame_counts']['mic'] == 1200

    recorder.stop_recording_and_save()


def test_level_channels_respects_tolerance(tmp_path, monkeypatch):
    _start_recording_with_stubs(tmp_path, monkeypatch)

    recorder._increment_frame_count('sys', 100)
    recorder._level_channels(tolerance_frames=1000)

    assert recorder._state['frame_counts']['mic'] == 0
    assert recorder._state['mic_queue'].qsize() == 0

    recorder.stop_recording_and_save()


def test_teardown_performs_final_levelling_pass(tmp_path, monkeypatch):
    _start_recording_with_stubs(tmp_path, monkeypatch)

    recorder._state['padding_stop_event'].set()
    recorder._state['padding_thread'].join(timeout=2)
    sys_chunk = np.zeros((500, 1), dtype='float32')
    recorder._enqueue(recorder._state['sys_queue'], 'sys', sys_chunk)

    path = recorder.stop_recording_and_save()

    with sf.SoundFile(path, mode='r') as f:
        assert len(f) >= 500


def test_early_sck_stop_preserves_full_mic_tail_and_still_warns(tmp_path, monkeypatch, caplog):
    mic_stream, fake_handle = _start_recording_with_stubs(tmp_path, monkeypatch)

    mic_queue = recorder._state['mic_queue']
    mic_chunk = np.zeros((SAMPLE_RATE, 1), dtype='float32')
    recorder._enqueue(mic_queue, 'mic', mic_chunk)

    fake_handle.stopped_unexpectedly = 'connection interruption'

    with caplog.at_level('WARNING'):
        path = recorder.stop_recording_and_save()

    with sf.SoundFile(path, mode='r') as f:
        assert len(f) >= SAMPLE_RATE
    assert 'stopped unexpectedly' in caplog.text


# --- Two-channel silence monitoring ------------------------------------------

def _init_silence_state():
    recorder._state['mic_silence_buffer'] = np.zeros((0, 1), dtype='float32')
    recorder._state['mic_silence_buffer_lock'] = threading.Lock()
    recorder._state['sys_silence_buffer'] = np.zeros((0, 1), dtype='float32')
    recorder._state['sys_silence_buffer_lock'] = threading.Lock()
    recorder._state['last_chunk_at'] = {'mic': None, 'sys': None}
    recorder._state['mic_paused'] = False


def _clear_silence_state():
    recorder._state['mic_silence_buffer'] = None
    recorder._state['mic_silence_buffer_lock'] = None
    recorder._state['sys_silence_buffer'] = None
    recorder._state['sys_silence_buffer_lock'] = None
    recorder._state['last_chunk_at'] = None
    recorder._state['mic_paused'] = False


def test_silence_monitor_warns_independently_per_channel(monkeypatch):
    _init_silence_state()

    warning_hook = MagicMock()
    monkeypatch.setattr(recorder, 'on_silence_warning', warning_hook)
    monkeypatch.setattr(recorder, '_silence_window_seconds', lambda: 0.0)
    monkeypatch.setattr(recorder, '_silence_rms_threshold', lambda: 0.001)
    monkeypatch.setattr(recorder, 'MIC_SILENCE_GRACE_SECONDS', 0.0)

    recorder._append_to_silence_buffer('mic', np.zeros((10, 1), dtype='float32'))
    recorder._append_to_silence_buffer('sys', np.full((10, 1), 0.5, dtype='float32'))

    stop_event = threading.Event()
    thread = threading.Thread(target=recorder._silence_monitor_loop, args=(stop_event,), daemon=True)
    thread.start()
    import time as _time
    _time.sleep(recorder.SILENCE_CHECK_INTERVAL_SECONDS * 2.5)
    stop_event.set()
    thread.join(timeout=2)

    warning_hook.assert_called_once_with('mic')

    _clear_silence_state()


def test_silence_monitor_reports_recovery(monkeypatch):
    _init_silence_state()

    warning_hook = MagicMock()
    recovered_hook = MagicMock()
    monkeypatch.setattr(recorder, 'on_silence_warning', warning_hook)
    monkeypatch.setattr(recorder, 'on_silence_recovered', recovered_hook)
    monkeypatch.setattr(recorder, '_silence_window_seconds', lambda: 0.0)
    monkeypatch.setattr(recorder, '_silence_rms_threshold', lambda: 0.001)
    monkeypatch.setattr(recorder, 'MIC_SILENCE_GRACE_SECONDS', 0.0)

    recorder._append_to_silence_buffer('sys', np.full((10, 1), 0.5, dtype='float32'))

    stop_event = threading.Event()
    thread = threading.Thread(target=recorder._silence_monitor_loop, args=(stop_event,), daemon=True)
    thread.start()
    import time as _time
    _time.sleep(recorder.SILENCE_CHECK_INTERVAL_SECONDS * 2.5)

    recorder._append_to_silence_buffer('mic', np.full((10, 1), 0.5, dtype='float32'))
    _time.sleep(recorder.SILENCE_CHECK_INTERVAL_SECONDS * 1.5)

    stop_event.set()
    thread.join(timeout=2)

    warning_hook.assert_called_once_with('mic')
    recovered_hook.assert_called_once_with('mic')

    _clear_silence_state()


def test_silence_monitor_no_warning_while_channel_active(monkeypatch):
    _init_silence_state()

    warning_hook = MagicMock()
    monkeypatch.setattr(recorder, 'on_silence_warning', warning_hook)
    monkeypatch.setattr(recorder, '_silence_window_seconds', lambda: 0.0)
    monkeypatch.setattr(recorder, '_silence_rms_threshold', lambda: 0.001)
    monkeypatch.setattr(recorder, 'MIC_SILENCE_GRACE_SECONDS', 0.0)

    recorder._append_to_silence_buffer('mic', np.full((10, 1), 0.5, dtype='float32'))
    recorder._append_to_silence_buffer('sys', np.full((10, 1), 0.5, dtype='float32'))

    stop_event = threading.Event()
    thread = threading.Thread(target=recorder._silence_monitor_loop, args=(stop_event,), daemon=True)
    thread.start()
    import time as _time
    _time.sleep(recorder.SILENCE_CHECK_INTERVAL_SECONDS * 2.5)
    stop_event.set()
    thread.join(timeout=2)

    warning_hook.assert_not_called()

    _clear_silence_state()


def test_silence_monitor_warns_when_device_stops_delivering_chunks(monkeypatch):
    '''A device that is physically unplugged mid-recording (e.g. a USB microphone) stops
    calling back entirely - PortAudio never delivers another chunk, silent or otherwise - so
    the RMS buffer is stuck holding loud pre-disconnect audio and would never read as silent
    on its own. The monitor must fall back to "no new chunk for a while" instead.'''
    _init_silence_state()

    warning_hook = MagicMock()
    monkeypatch.setattr(recorder, 'on_silence_warning', warning_hook)
    monkeypatch.setattr(recorder, '_silence_window_seconds', lambda: 0.0)
    monkeypatch.setattr(recorder, '_silence_rms_threshold', lambda: 0.001)
    monkeypatch.setattr(recorder, 'MIC_SILENCE_GRACE_SECONDS', 0.0)

    # Loud content, but no fresh timestamp (last_chunk_at['mic'] stays None) - simulates the
    # last chunk received before the device disappeared, well before the monitor loop starts
    # checking, so the channel is stale from its very first evaluation.
    recorder._state['mic_silence_buffer'] = np.full((10, 1), 0.5, dtype='float32')
    recorder._append_to_silence_buffer('sys', np.full((10, 1), 0.5, dtype='float32'))

    stop_event = threading.Event()
    thread = threading.Thread(target=recorder._silence_monitor_loop, args=(stop_event,), daemon=True)
    thread.start()
    import time as _time
    _time.sleep(recorder.SILENCE_CHECK_INTERVAL_SECONDS * 2.5)
    stop_event.set()
    thread.join(timeout=2)

    warning_hook.assert_called_once_with('mic')

    _clear_silence_state()


def test_silence_monitor_skips_mic_while_paused_for_switch(monkeypatch):
    '''While the microphone is deliberately paused for a device switch, no new chunks arrive
    either - but that is already surfaced via the menu bar's "paused" attention reason, so the
    silence monitor should not pile on a second, confusing "microphone is silent" warning.'''
    _init_silence_state()
    recorder._state['mic_paused'] = True

    warning_hook = MagicMock()
    monkeypatch.setattr(recorder, 'on_silence_warning', warning_hook)
    monkeypatch.setattr(recorder, '_silence_window_seconds', lambda: 0.0)
    monkeypatch.setattr(recorder, '_silence_rms_threshold', lambda: 0.001)
    monkeypatch.setattr(recorder, 'MIC_SILENCE_GRACE_SECONDS', 0.0)

    recorder._append_to_silence_buffer('sys', np.full((10, 1), 0.5, dtype='float32'))

    stop_event = threading.Event()
    thread = threading.Thread(target=recorder._silence_monitor_loop, args=(stop_event,), daemon=True)
    thread.start()
    import time as _time
    _time.sleep(recorder.SILENCE_CHECK_INTERVAL_SECONDS * 2.5)
    stop_event.set()
    thread.join(timeout=2)

    warning_hook.assert_not_called()

    _clear_silence_state()


def test_mic_callback_logs_nonempty_status(tmp_path, monkeypatch, caplog):
    _start_recording_with_stubs(tmp_path, monkeypatch)
    mic_callback = recorder._state['mic_callback']

    with caplog.at_level('WARNING'):
        mic_callback(np.zeros((10, 1), dtype='float32'), 10, None, 'input overflow')

    assert 'input overflow' in caplog.text
    recorder.stop_recording_and_save()


def test_mic_callback_silent_on_empty_status(tmp_path, monkeypatch, caplog):
    _start_recording_with_stubs(tmp_path, monkeypatch)
    mic_callback = recorder._state['mic_callback']

    with caplog.at_level('WARNING'):
        mic_callback(np.zeros((10, 1), dtype='float32'), 10, None, '')

    assert caplog.text == ''
    recorder.stop_recording_and_save()


# --- Microphone pause/resume --------------------------------------------------

def test_pause_mic_leaves_sys_capture_running(tmp_path, monkeypatch):
    mic_stream, fake_handle = _start_recording_with_stubs(tmp_path, monkeypatch)

    recorder.pause_mic()

    mic_stream.stop.assert_called_once()
    mic_stream.close.assert_called_once()
    assert recorder._state['mic_stream'] is None
    assert recorder._state['mic_paused'] is True
    assert recorder._state['sys_handle'] is fake_handle

    recorder.stop_recording_and_save()


def test_resume_mic_writes_to_same_mic_wav(tmp_path, monkeypatch):
    _start_recording_with_stubs(tmp_path, monkeypatch)
    mic_temp_path = recorder._state['mic_temp_path']

    recorder.pause_mic()

    new_stream = MagicMock()
    monkeypatch.setattr(recorder.sd, 'InputStream', MagicMock(return_value=new_stream))

    resumed_device = recorder.resume_mic(device=2)

    assert resumed_device == 2
    new_stream.start.assert_called_once()
    assert recorder._state['mic_stream'] is new_stream
    assert recorder._state['mic_paused'] is False
    assert recorder._state['mic_temp_path'] == mic_temp_path

    recorder.stop_recording_and_save()


def test_resume_mic_falls_back_to_previous_device_when_abandoned(tmp_path, monkeypatch):
    _start_recording_with_stubs(tmp_path, monkeypatch)
    original_device = recorder._state['last_mic_device']

    recorder.pause_mic()

    new_stream = MagicMock()
    input_stream_spy = MagicMock(return_value=new_stream)
    monkeypatch.setattr(recorder.sd, 'InputStream', input_stream_spy)

    recorder.resume_mic(device=None)

    _, kwargs = input_stream_spy.call_args
    assert kwargs['device'] == original_device

    recorder.stop_recording_and_save()


def test_list_input_devices_refused_while_capture_active(tmp_path, monkeypatch):
    _start_recording_with_stubs(tmp_path, monkeypatch)

    with pytest.raises(RuntimeError, match='active'):
        recorder.list_input_devices()

    recorder.stop_recording_and_save()


def test_list_input_devices_returns_inputs_while_paused(tmp_path, monkeypatch):
    _start_recording_with_stubs(tmp_path, monkeypatch)
    recorder.pause_mic()

    terminate_spy = MagicMock()
    initialize_spy = MagicMock()
    monkeypatch.setattr(recorder.sd, '_terminate', terminate_spy)
    monkeypatch.setattr(recorder.sd, '_initialize', initialize_spy)
    monkeypatch.setattr(recorder.sd, 'query_devices', MagicMock(return_value=[
        {'name': 'Built-in Mic', 'max_input_channels': 1},
        {'name': 'Speakers', 'max_input_channels': 0},
        {'name': 'AirPods', 'max_input_channels': 1},
    ]))

    devices = recorder.list_input_devices()

    terminate_spy.assert_called_once()
    initialize_spy.assert_called_once()
    assert devices == [
        {'index': 0, 'name': 'Built-in Mic'},
        {'index': 2, 'name': 'AirPods'},
    ]

    recorder.resume_mic()
    recorder.stop_recording_and_save()


def test_resume_mic_failure_falls_back_without_stopping_recording(tmp_path, monkeypatch):
    _start_recording_with_stubs(tmp_path, monkeypatch)
    recorder.pause_mic()

    fallback_stream = MagicMock()

    def fake_input_stream(*args, **kwargs):
        if kwargs.get('device') == 99:
            raise RuntimeError('unsupported sample rate')
        return fallback_stream

    monkeypatch.setattr(recorder.sd, 'InputStream', MagicMock(side_effect=fake_input_stream))

    with pytest.raises(recorder.MicResumeFallbackError):
        recorder.resume_mic(device=99)

    assert recorder._state['mic_stream'] is fallback_stream
    assert recorder._state['mic_paused'] is False
    fallback_stream.start.assert_called_once()

    recorder.stop_recording_and_save()


def test_interruption_warning_distinguishes_recovered_from_exhausted():
    recovered_warning = recorder._build_interruption_warning(
        'out.wav', [{'error': 'connection interruption', 'recovered': True}],
    )
    exhausted_warning = recorder._build_interruption_warning(
        'out.wav', [{'error': 'connection interruption', 'recovered': False}],
    )

    assert recovered_warning != exhausted_warning
    assert 'truncated' not in recovered_warning
    assert 'truncated' not in exhausted_warning


def test_interruption_warning_reports_multiple_interruptions():
    warning = recorder._build_interruption_warning(
        'out.wav',
        [
            {'error': 'first', 'recovered': True},
            {'error': 'second', 'recovered': True},
        ],
    )

    assert '2 time' in warning


# --- System-audio restart supervisor -----------------------------------------

def test_restart_supervisor_recovers_into_same_recording(tmp_path, monkeypatch):
    _mic_stream, fake_handle = _start_recording_with_stubs(tmp_path, monkeypatch)
    recorder._stop_restart_supervisor()

    fake_handle.stopped_unexpectedly = 'connection interruption'
    new_handle = MagicMock()
    new_handle.stopped_unexpectedly = None
    sck_start = MagicMock(return_value=new_handle)
    monkeypatch.setattr(recorder.sck_capture, 'start', sck_start)

    now = 1000.0
    recorder._sys_restart_tick(now)
    sck_start.assert_not_called()
    assert recorder._state['sys_handle'] is fake_handle

    now += recorder.SYS_RESTART_BASE_DELAY_SECONDS
    recorder._sys_restart_tick(now)

    sck_start.assert_called_once()
    args, kwargs = sck_start.call_args
    assert args[0] is recorder._state['sys_on_chunk']
    assert kwargs['sample_rate'] == recorder.SAMPLE_RATE
    assert kwargs['channels'] == recorder.SYS_AUDIO_CHANNELS
    assert recorder._state['sys_handle'] is new_handle
    assert recorder._state['sys_restart']['interruptions'] == [
        {'error': 'connection interruption', 'recovered': True},
    ]

    recorder.stop_recording_and_save()


def test_restart_supervisor_backs_off_and_bounds_attempts(tmp_path, monkeypatch):
    _mic_stream, fake_handle = _start_recording_with_stubs(tmp_path, monkeypatch)
    recorder._stop_restart_supervisor()

    fake_handle.stopped_unexpectedly = 'connection interruption'
    sck_start = MagicMock(side_effect=RuntimeError('still failing'))
    monkeypatch.setattr(recorder.sck_capture, 'start', sck_start)

    now = 0.0
    recorder._sys_restart_tick(now)  # detects the interruption, schedules the first attempt

    delay = recorder.SYS_RESTART_BASE_DELAY_SECONDS
    delays_used = []
    for _ in range(recorder.SYS_RESTART_MAX_ATTEMPTS):
        now += delay
        delays_used.append(delay)
        recorder._sys_restart_tick(now)
        delay *= 2

    assert sck_start.call_count == recorder.SYS_RESTART_MAX_ATTEMPTS
    assert all(b > a for a, b in zip(delays_used, delays_used[1:]))

    now += delay
    recorder._sys_restart_tick(now)
    assert sck_start.call_count == recorder.SYS_RESTART_MAX_ATTEMPTS  # budget exhausted, no further attempt

    recorder.stop_recording_and_save()


def test_restart_budget_resets_after_sustained_healthy_capture(tmp_path, monkeypatch):
    _mic_stream, fake_handle = _start_recording_with_stubs(tmp_path, monkeypatch)
    recorder._stop_restart_supervisor()

    fake_handle.stopped_unexpectedly = 'first interruption'
    new_handle = MagicMock()
    new_handle.stopped_unexpectedly = None
    monkeypatch.setattr(recorder.sck_capture, 'start', MagicMock(return_value=new_handle))

    now = 0.0
    recorder._sys_restart_tick(now)
    now += recorder.SYS_RESTART_BASE_DELAY_SECONDS
    recorder._sys_restart_tick(now)  # restart succeeds

    assert recorder._state['sys_restart']['attempts_left'] == recorder.SYS_RESTART_MAX_ATTEMPTS - 1

    now += recorder.SYS_RESTART_HEALTHY_RESET_SECONDS
    recorder._state['last_chunk_at']['sys'] = now
    recorder._sys_restart_tick(now)

    assert recorder._state['sys_restart']['attempts_left'] == recorder.SYS_RESTART_MAX_ATTEMPTS

    # A later, unrelated interruption is retried with the fully-restored budget.
    new_handle.stopped_unexpectedly = 'second, unrelated interruption'
    recorder._sys_restart_tick(now)
    assert recorder._state['sys_restart']['attempts_left'] == recorder.SYS_RESTART_MAX_ATTEMPTS

    recorder.stop_recording_and_save()


def test_restart_short_lived_restart_does_not_reset_budget(tmp_path, monkeypatch):
    _mic_stream, fake_handle = _start_recording_with_stubs(tmp_path, monkeypatch)
    recorder._stop_restart_supervisor()

    fake_handle.stopped_unexpectedly = 'first interruption'
    new_handle = MagicMock()
    new_handle.stopped_unexpectedly = None
    monkeypatch.setattr(recorder.sck_capture, 'start', MagicMock(return_value=new_handle))

    now = 0.0
    recorder._sys_restart_tick(now)
    now += recorder.SYS_RESTART_BASE_DELAY_SECONDS
    recorder._sys_restart_tick(now)  # restart succeeds

    attempts_after_restart = recorder._state['sys_restart']['attempts_left']
    assert attempts_after_restart == recorder.SYS_RESTART_MAX_ATTEMPTS - 1

    # The restarted stream dies again well before the sustained healthy period elapses.
    new_handle.stopped_unexpectedly = 'second interruption (short-lived)'
    now += 1.0
    recorder._sys_restart_tick(now)

    assert recorder._state['sys_restart']['attempts_left'] == attempts_after_restart

    recorder.stop_recording_and_save()


def test_no_restart_attempted_after_user_requested_stop(tmp_path, monkeypatch):
    _mic_stream, fake_handle = _start_recording_with_stubs(tmp_path, monkeypatch)
    recorder._stop_restart_supervisor()

    sck_start = MagicMock()
    monkeypatch.setattr(recorder.sck_capture, 'start', sck_start)

    fake_handle.stopped_unexpectedly = None
    recorder.stop_recording_and_save()

    sck_start.assert_not_called()


def test_restart_completing_after_teardown_stops_stream_and_leaves_sys_handle_none(tmp_path, monkeypatch):
    '''A restart attempt can still be blocked inside sck_capture.start() when
    _stop_restart_supervisor()'s bounded join times out, so the user's stop can complete
    (clearing _state['sys_restart']/'sys_restart_lock' to None) before this in-flight tick
    reaches its publish guard. Uses real threads to reproduce that interleaving, rather than
    synthetic `now` values, since it is genuinely concurrent.'''
    _mic_stream, fake_handle = _start_recording_with_stubs(tmp_path, monkeypatch)
    recorder._stop_restart_supervisor()

    fake_handle.stopped_unexpectedly = 'connection interruption'
    recorder._sys_restart_tick(0.0)  # observe the interruption and schedule the first attempt

    new_handle = MagicMock()
    new_handle.stopped_unexpectedly = None
    sck_stop = MagicMock()
    teardown_started = threading.Event()
    release_start = threading.Event()

    def blocking_start(*args, **kwargs):
        teardown_started.set()
        release_start.wait(timeout=2)
        return new_handle

    monkeypatch.setattr(recorder.sck_capture, 'start', MagicMock(side_effect=blocking_start))
    monkeypatch.setattr(recorder.sck_capture, 'stop', sck_stop)

    tick_thread = threading.Thread(
        target=recorder._sys_restart_tick, args=(recorder.SYS_RESTART_BASE_DELAY_SECONDS,),
    )
    tick_thread.start()

    assert teardown_started.wait(timeout=2)
    recorder.stop_recording_and_save()
    assert recorder._state['sys_handle'] is None

    release_start.set()
    tick_thread.join(timeout=2)

    sck_stop.assert_any_call(new_handle)
    assert recorder._state['sys_handle'] is None


def test_discard_recording_removes_temp_dir_without_writing_output(tmp_path, monkeypatch):
    recordings_dir = tmp_path / 'recordings'
    monkeypatch.setenv('RECORDINGS_DIR', str(recordings_dir))
    monkeypatch.setattr(recorder.sd.default, 'device', (0, 0))

    mic_stream = MagicMock()
    monkeypatch.setattr(recorder.sd, 'InputStream', MagicMock(return_value=mic_stream))
    fake_handle = MagicMock()
    sck_stop = MagicMock()
    monkeypatch.setattr(recorder.sck_capture, 'start', MagicMock(return_value=fake_handle))
    monkeypatch.setattr(recorder.sck_capture, 'stop', sck_stop)

    recorder.start_recording()
    temp_dir = recorder._state['temp_dir']
    assert os.path.isdir(temp_dir)

    recorder.discard_recording()

    assert not os.path.exists(temp_dir)
    assert list(recordings_dir.glob('*.wav')) == []
    sck_stop.assert_called_once_with(fake_handle)
    mic_stream.stop.assert_called_once()
    mic_stream.close.assert_called_once()
    assert recorder._state['mic_stream'] is None
    assert recorder._state['sys_handle'] is None
    assert recorder._state['temp_dir'] is None
