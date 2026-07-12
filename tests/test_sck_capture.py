import threading
from unittest.mock import MagicMock

import numpy as np
import pytest

from meet_recorder import sck_capture


def test_float32_stereo_to_mono_averages_channels():
    raw = np.array([1.0, -1.0, 0.5, 0.5], dtype='float32').tobytes()

    mono = sck_capture.float32_stereo_to_mono(raw, channels=2)

    assert mono.shape == (2, 1)
    np.testing.assert_allclose(mono.flatten(), [0.0, 0.5])


def test_float32_stereo_to_mono_passthrough_for_mono_input():
    raw = np.array([0.25, -0.75], dtype='float32').tobytes()

    mono = sck_capture.float32_stereo_to_mono(raw, channels=1)

    assert mono.shape == (2, 1)
    np.testing.assert_allclose(mono.flatten(), [0.25, -0.75])


def test_float32_stereo_to_mono_empty_buffer():
    mono = sck_capture.float32_stereo_to_mono(b'', channels=2)

    assert mono.shape == (0, 1)


def test_run_async_returns_when_completion_called_without_error():
    def action(completion):
        completion(None)

    sck_capture._run_async(1, action)


def test_run_async_raises_when_completion_called_with_error():
    def action(completion):
        completion('boom')

    with pytest.raises(RuntimeError, match='boom'):
        sck_capture._run_async(1, action)


def test_run_async_raises_on_timeout():
    def action(completion):
        pass

    with pytest.raises(RuntimeError, match='Timed out'):
        sck_capture._run_async(0.05, action)


def test_run_async_supports_completion_called_from_another_thread():
    def action(completion):
        threading.Timer(0.01, lambda: completion(None)).start()

    sck_capture._run_async(1, action)


@pytest.fixture
def sck_mocks(monkeypatch):
    display = MagicMock()
    content = MagicMock()
    content.displays.return_value = [display]

    def fake_get_shareable_content(handler):
        handler(content, None)

    shareable_content = MagicMock()
    shareable_content.getShareableContentWithCompletionHandler_.side_effect = fake_get_shareable_content
    monkeypatch.setattr(sck_capture, 'SCShareableContent', shareable_content)

    content_filter_cls = MagicMock()
    content_filter_instance = MagicMock()
    content_filter_cls.alloc.return_value.initWithDisplay_excludingApplications_exceptingWindows_.return_value = (
        content_filter_instance
    )
    monkeypatch.setattr(sck_capture, 'SCContentFilter', content_filter_cls)

    config_cls = MagicMock()
    config_instance = MagicMock()
    config_cls.alloc.return_value.init.return_value = config_instance
    monkeypatch.setattr(sck_capture, 'SCStreamConfiguration', config_cls)

    stream_instance = MagicMock()
    stream_instance.addStreamOutput_type_sampleHandlerQueue_error_.return_value = (True, None)
    stream_instance.startCaptureWithCompletionHandler_.side_effect = lambda completion: completion(None)
    stream_instance.stopCaptureWithCompletionHandler_.side_effect = lambda completion: completion(None)
    stream_cls = MagicMock()
    stream_cls.alloc.return_value.initWithFilter_configuration_delegate_.return_value = stream_instance
    monkeypatch.setattr(sck_capture, 'SCStream', stream_cls)

    monkeypatch.setattr(sck_capture.dispatch, 'dispatch_queue_create', lambda *a, **k: MagicMock())

    return {'content': content, 'display': display, 'stream': stream_instance, 'config': config_instance}


def test_start_raises_when_no_displays_found(sck_mocks):
    sck_mocks['content'].displays.return_value = []

    with pytest.raises(RuntimeError, match='No shareable displays'):
        sck_capture.start(lambda chunk: None, sample_rate=16000)


def test_start_raises_when_add_stream_output_fails(sck_mocks):
    sck_mocks['stream'].addStreamOutput_type_sampleHandlerQueue_error_.return_value = (False, 'nope')

    with pytest.raises(RuntimeError, match='nope'):
        sck_capture.start(lambda chunk: None, sample_rate=16000)


def test_start_raises_when_capture_start_fails(sck_mocks):
    sck_mocks['stream'].startCaptureWithCompletionHandler_.side_effect = lambda completion: completion('denied')

    with pytest.raises(RuntimeError, match='denied'):
        sck_capture.start(lambda chunk: None, sample_rate=16000)


def test_start_configures_stream_with_requested_sample_rate_and_channels(sck_mocks):
    sck_capture.start(lambda chunk: None, sample_rate=16000, channels=2)

    sck_mocks['config'].setCapturesAudio_.assert_called_once_with(True)
    sck_mocks['config'].setSampleRate_.assert_called_once_with(16000)
    sck_mocks['config'].setChannelCount_.assert_called_once_with(2)


def test_start_returns_active_handle(sck_mocks):
    handle = sck_capture.start(lambda chunk: None, sample_rate=16000, channels=2)

    assert handle._active is True
    assert handle.channels == 2
    assert handle.stream is sck_mocks['stream']


def test_stop_calls_stop_capture_and_deactivates_handle(sck_mocks):
    handle = sck_capture.start(lambda chunk: None, sample_rate=16000)

    sck_capture.stop(handle)

    sck_mocks['stream'].stopCaptureWithCompletionHandler_.assert_called_once()
    assert handle._active is False


def test_stop_is_a_noop_when_handle_has_no_stream():
    sck_capture.stop(sck_capture.CaptureHandle(lambda chunk: None, channels=2))


def test_stop_logs_and_does_not_raise_when_stop_capture_errors(sck_mocks, caplog):
    sck_mocks['stream'].stopCaptureWithCompletionHandler_.side_effect = lambda completion: completion('oops')
    handle = sck_capture.start(lambda chunk: None, sample_rate=16000)

    sck_capture.stop(handle)

    assert 'oops' in caplog.text


def test_delegate_forwards_mono_chunks_to_callback(sck_mocks, monkeypatch):
    received = []
    sck_capture.start(received.append, sample_rate=16000, channels=2)

    delegate = sck_mocks['stream'].addStreamOutput_type_sampleHandlerQueue_error_.call_args[0][0]

    raw = np.array([1.0, -1.0, 0.5, 0.5], dtype='float32').tobytes()

    monkeypatch.setattr(sck_capture, 'CMSampleBufferGetDataBuffer', lambda sb: object())
    monkeypatch.setattr(sck_capture, 'CMBlockBufferGetDataLength', lambda db: len(raw))
    monkeypatch.setattr(sck_capture, 'CMBlockBufferCopyDataBytes', lambda db, offset, length, out: (0, raw))
    monkeypatch.setattr(sck_capture, 'CMSampleBufferGetFormatDescription', lambda sb: object())
    monkeypatch.setattr(
        sck_capture, 'CMAudioFormatDescriptionGetStreamBasicDescription',
        lambda fmt: (16000.0, 0, 0, 0, 0, 0, 2, 32, 0),
    )

    delegate.stream_didOutputSampleBuffer_ofType_(
        sck_mocks['stream'], object(), sck_capture.SCStreamOutputTypeAudio,
    )

    assert len(received) == 1
    np.testing.assert_allclose(received[0].flatten(), [0.0, 0.5])


def test_delegate_ignores_non_audio_buffers(sck_mocks):
    received = []
    sck_capture.start(received.append, sample_rate=16000, channels=2)
    delegate = sck_mocks['stream'].addStreamOutput_type_sampleHandlerQueue_error_.call_args[0][0]

    delegate.stream_didOutputSampleBuffer_ofType_(sck_mocks['stream'], object(), 'some-other-type')

    assert received == []
