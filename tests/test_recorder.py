import os

import numpy as np
import pytest
import soundfile as sf

from meet_recorder import recorder

SAMPLE_RATE = recorder.SAMPLE_RATE


def _write_mono_wav(path, samples):
    with sf.SoundFile(str(path), mode='w', samplerate=SAMPLE_RATE, channels=1, subtype='PCM_16') as f:
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
