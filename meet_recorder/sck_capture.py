import logging
import threading

import dispatch
import numpy as np
import objc
from Foundation import NSObject
from ScreenCaptureKit import (
    SCContentFilter,
    SCShareableContent,
    SCStream,
    SCStreamConfiguration,
    SCStreamOutputTypeAudio,
)
from CoreMedia import (
    CMAudioFormatDescriptionGetStreamBasicDescription,
    CMBlockBufferCopyDataBytes,
    CMBlockBufferGetDataLength,
    CMSampleBufferGetDataBuffer,
    CMSampleBufferGetFormatDescription,
    CMTimeMake,
)

logger = logging.getLogger(__name__)

# ScreenCaptureKit requires a configured video stream even when only audio is
# wanted; these are the minimal dimensions/frame rate that discard video work
# without disabling it outright (see screencapture-guide.md).
DISCARDED_VIDEO_WIDTH = 2
DISCARDED_VIDEO_HEIGHT = 2

CONTENT_LIST_TIMEOUT_SECONDS = 10
START_TIMEOUT_SECONDS = 10
STOP_TIMEOUT_SECONDS = 10

SCStreamOutput = objc.protocolNamed('SCStreamOutput')
SCStreamDelegateProtocol = objc.protocolNamed('SCStreamDelegate')


def float32_stereo_to_mono(raw_bytes, channels):
    '''Convert raw interleaved Float32 bytes from an SCStream audio buffer to a mono (n, 1) array.'''
    samples = np.frombuffer(raw_bytes, dtype='float32')
    if channels == 1:
        return samples.reshape(-1, 1)
    frames = samples.reshape(-1, channels)
    return np.mean(frames, axis=1, keepdims=True).astype('float32')


class _CaptureDelegate(NSObject, protocols=[SCStreamOutput, SCStreamDelegateProtocol]):
    # NOTE: do NOT decorate these with @objc.python_method. That marks the method
    # unreachable from the Objective-C runtime, so SCStream can never invoke it as
    # its delegate callback - the stream then "runs" with no error but delivers
    # zero buffers. This was root-caused during the migrate-to-screencapturekit
    # spike; see openspec/changes/migrate-to-screencapturekit/design.md (D4).
    def stream_didOutputSampleBuffer_ofType_(self, stream, sample_buffer, buf_type):
        if buf_type != SCStreamOutputTypeAudio:
            return

        handle = self.handle
        if handle is None or not handle._active:
            return

        if not handle._format_logged:
            handle._format_logged = True
            _log_format(sample_buffer)

        data_buffer = CMSampleBufferGetDataBuffer(sample_buffer)
        if data_buffer is None:
            return

        length = CMBlockBufferGetDataLength(data_buffer)
        status, raw_bytes = CMBlockBufferCopyDataBytes(data_buffer, 0, length, None)
        if status != 0 or not raw_bytes:
            return

        mono_chunk = float32_stereo_to_mono(raw_bytes, handle.channels)
        handle.on_chunk(mono_chunk)

    def stream_didStopWithError_(self, stream, error):
        if error is not None:
            logger.error(f'ScreenCaptureKit stream stopped with error: {error}')


def _log_format(sample_buffer):
    try:
        fmt = CMSampleBufferGetFormatDescription(sample_buffer)
        asbd = CMAudioFormatDescriptionGetStreamBasicDescription(fmt)
        # asbd is a raw tuple mirroring AudioStreamBasicDescription field order:
        # (sampleRate, formatID, formatFlags, bytesPerPacket, framesPerPacket,
        #  bytesPerFrame, channelsPerFrame, bitsPerChannel, reserved)
        logger.debug(
            f'ScreenCaptureKit audio format: sampleRate={asbd[0]} channelsPerFrame={asbd[6]} '
            f'bitsPerChannel={asbd[7]}'
        )
    except Exception as e:
        logger.debug(f'Could not read ScreenCaptureKit audio format: {e}')


class CaptureHandle:
    def __init__(self, on_chunk, channels):
        self.on_chunk = on_chunk
        self.channels = channels
        self.stream = None
        self.delegate = None
        self._active = False
        self._format_logged = False


def _run_async(timeout_seconds, action):
    '''Bridge an SCK completion-handler call into a synchronous call, raising on error/timeout.'''
    done = threading.Event()
    result = {'error': None}

    def completion(error=None):
        result['error'] = error
        done.set()

    action(completion)

    if not done.wait(timeout=timeout_seconds):
        raise RuntimeError('Timed out waiting for ScreenCaptureKit')
    if result['error'] is not None:
        raise RuntimeError(f'ScreenCaptureKit error: {result["error"]}')


def start(on_chunk, sample_rate, channels=1):
    '''Start system-audio capture via ScreenCaptureKit.

    `on_chunk` is called with a (n, 1) float32 mono numpy array for each audio buffer.
    Raises RuntimeError if content listing, stream creation, or capture start fails.
    Returns a CaptureHandle to pass to `stop`.
    '''
    handle = CaptureHandle(on_chunk, channels)
    content_result = {}

    def list_content(completion):
        def on_content(content, error):
            content_result['content'] = content
            completion(error)

        SCShareableContent.getShareableContentWithCompletionHandler_(on_content)

    _run_async(CONTENT_LIST_TIMEOUT_SECONDS, list_content)

    content = content_result.get('content')
    displays = content.displays() if content else None
    if not displays:
        raise RuntimeError('No shareable displays found - is Screen Recording permission granted?')

    display = displays[0]
    content_filter = SCContentFilter.alloc().initWithDisplay_excludingApplications_exceptingWindows_(
        display, [], [],
    )

    config = SCStreamConfiguration.alloc().init()
    config.setCapturesAudio_(True)
    config.setSampleRate_(sample_rate)
    # channels=2 is intentionally avoided by callers: SCStreamConfiguration's stereo delivery
    # produces audibly corrupted/"robotic" audio on this pyobjc/macOS combination, independent
    # of downstream downmixing (confirmed present in each raw channel before any processing of
    # ours). channels=1 (native mono from ScreenCaptureKit) is clean. See design.md.
    config.setChannelCount_(channels)
    config.setWidth_(DISCARDED_VIDEO_WIDTH)
    config.setHeight_(DISCARDED_VIDEO_HEIGHT)
    config.setMinimumFrameInterval_(CMTimeMake(1, 1))

    delegate = _CaptureDelegate.alloc().init()
    delegate.handle = handle

    stream = SCStream.alloc().initWithFilter_configuration_delegate_(content_filter, config, delegate)

    dispatch_queue = dispatch.dispatch_queue_create(b'meet-recorder.sck-audio', None)
    ok, err = stream.addStreamOutput_type_sampleHandlerQueue_error_(
        delegate, SCStreamOutputTypeAudio, dispatch_queue, None,
    )
    if not ok:
        raise RuntimeError(f'Could not add ScreenCaptureKit audio output: {err}')

    def start_capture(completion):
        stream.startCaptureWithCompletionHandler_(completion)

    _run_async(START_TIMEOUT_SECONDS, start_capture)

    handle.stream = stream
    handle.delegate = delegate
    handle._active = True

    return handle


def stop(handle):
    '''Stop a capture started with `start`. Safe to call even if the stream never fully started.'''
    if handle is None or handle.stream is None:
        return

    handle._active = False

    def stop_capture(completion):
        handle.stream.stopCaptureWithCompletionHandler_(completion)

    try:
        _run_async(STOP_TIMEOUT_SECONDS, stop_capture)
    except RuntimeError as e:
        logger.error(f'Error stopping ScreenCaptureKit stream: {e}')
