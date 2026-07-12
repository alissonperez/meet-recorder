from unittest.mock import AsyncMock, Mock

import pytest

from meet_recorder import handlers


@pytest.fixture(autouse=True)
def _quiet_logger(monkeypatch):
    monkeypatch.setattr(handlers, 'logger', Mock())


def test_handler_record_starts_sleeps_for_duration_and_saves(monkeypatch):
    start_mock = Mock()
    stop_mock = Mock(return_value='/recordings/out.wav')
    sleep_mock = Mock()
    monkeypatch.setattr(handlers.recorder, 'start_recording', start_mock)
    monkeypatch.setattr(handlers.recorder, 'stop_recording_and_save', stop_mock)
    monkeypatch.setattr(handlers.time, 'sleep', sleep_mock)

    handlers.handler_record(duration=5)

    start_mock.assert_called_once()
    sleep_mock.assert_called_once_with(5)
    stop_mock.assert_called_once()


def test_handler_record_still_saves_when_sleep_is_interrupted(monkeypatch):
    # A verified-no-run-loop-needed design (see design.md D7): ScreenCaptureKit delivery
    # doesn't depend on the CLI process pumping a run loop, so the plain time.sleep() here
    # is sufficient - this test locks in that the recording is still saved (via the
    # try/finally) if that sleep is interrupted, e.g. by Ctrl-C.
    start_mock = Mock()
    stop_mock = Mock(return_value='/recordings/out.wav')
    monkeypatch.setattr(handlers.recorder, 'start_recording', start_mock)
    monkeypatch.setattr(handlers.recorder, 'stop_recording_and_save', stop_mock)
    monkeypatch.setattr(handlers.time, 'sleep', Mock(side_effect=KeyboardInterrupt))

    with pytest.raises(KeyboardInterrupt):
        handlers.handler_record(duration=5)

    stop_mock.assert_called_once()


def test_no_orphans_found_does_not_prompt(monkeypatch):
    monkeypatch.setattr(handlers.recorder, 'list_orphan_candidates', Mock(return_value=[]))
    monkeypatch.setattr(handlers.recorder, 'discard_invalid_orphans', Mock(return_value=[]))
    input_mock = Mock()
    monkeypatch.setattr('builtins.input', input_mock)

    handlers.handler_recover()

    input_mock.assert_not_called()
    handlers.logger.info.assert_called_with('Nothing to recover')


def test_process_choice_merges_and_transcribes(monkeypatch):
    orphans = ['/recordings/.in-progress/orphan1']
    monkeypatch.setattr(handlers.recorder, 'list_orphan_candidates', Mock(return_value=orphans))
    monkeypatch.setattr(handlers.recorder, 'discard_invalid_orphans', Mock(return_value=orphans))
    monkeypatch.setattr(handlers.recorder, 'merge_and_cleanup', Mock(return_value='/recordings/merged.wav'))
    transcribe_mock = AsyncMock(return_value={'transcript_path': 't.md', 'summary_path': 's.md'})
    monkeypatch.setattr(handlers.transcriber, 'transcribe', transcribe_mock)
    monkeypatch.setattr('builtins.input', Mock(return_value='p'))

    handlers.handler_recover()

    handlers.recorder.merge_and_cleanup.assert_called_once()
    transcribe_mock.assert_awaited_once_with('/recordings/merged.wav')


def test_delete_choice_deletes_and_skips_transcription(monkeypatch):
    orphans = ['/recordings/.in-progress/orphan1']
    monkeypatch.setattr(handlers.recorder, 'list_orphan_candidates', Mock(return_value=orphans))
    monkeypatch.setattr(handlers.recorder, 'discard_invalid_orphans', Mock(return_value=orphans))
    monkeypatch.setattr(handlers.recorder, 'delete_orphan', Mock())
    transcribe_mock = AsyncMock()
    monkeypatch.setattr(handlers.transcriber, 'transcribe', transcribe_mock)
    monkeypatch.setattr('builtins.input', Mock(return_value='a'))

    handlers.handler_recover()

    handlers.recorder.delete_orphan.assert_called_once_with(orphans[0])
    transcribe_mock.assert_not_awaited()


def test_ignore_choice_leaves_orphans_untouched(monkeypatch):
    orphans = ['/recordings/.in-progress/orphan1']
    monkeypatch.setattr(handlers.recorder, 'list_orphan_candidates', Mock(return_value=orphans))
    monkeypatch.setattr(handlers.recorder, 'discard_invalid_orphans', Mock(return_value=orphans))
    merge_mock = Mock()
    delete_mock = Mock()
    transcribe_mock = AsyncMock()
    monkeypatch.setattr(handlers.recorder, 'merge_and_cleanup', merge_mock)
    monkeypatch.setattr(handlers.recorder, 'delete_orphan', delete_mock)
    monkeypatch.setattr(handlers.transcriber, 'transcribe', transcribe_mock)
    monkeypatch.setattr('builtins.input', Mock(return_value='i'))

    handlers.handler_recover()

    merge_mock.assert_not_called()
    delete_mock.assert_not_called()
    transcribe_mock.assert_not_awaited()
