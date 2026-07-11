from unittest.mock import AsyncMock, Mock

import pytest

from meet_recorder import handlers


@pytest.fixture(autouse=True)
def _quiet_logger(monkeypatch):
    monkeypatch.setattr(handlers, 'logger', Mock())


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
