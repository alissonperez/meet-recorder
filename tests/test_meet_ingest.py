from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from meet_recorder import meet_ingest
from meet_recorder.calendar import OccurrenceAttachments
from meet_recorder.drive import DriveAccessError, DriveScopeError

UTC = timezone.utc


def _config(max_access_retries=3, lookback_hours=12):
    return SimpleNamespace(
        meet_transcripts=SimpleNamespace(
            lookback_hours=lookback_hours, max_access_retries=max_access_retries,
        ),
    )


def _event(event_id='occ', title='Sync'):
    start = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)
    return SimpleNamespace(
        id=event_id, title=title, calendar='personal',
        start_dt=start, end_dt=start + timedelta(hours=1), attachments=[],
    )


@pytest.fixture(autouse=True)
def _quiet_logger(monkeypatch):
    monkeypatch.setattr(meet_ingest, 'logger', Mock())


@pytest.fixture
def _wiring(monkeypatch):
    '''Default happy-path wiring: one event, never skipped, exports return text, writes succeed.'''
    monkeypatch.setattr(meet_ingest.calendar, 'past_events', lambda config, hours: [_event()])
    monkeypatch.setattr(meet_ingest.ledger, 'should_skip', lambda event_id: False)
    mark_done = Mock()
    monkeypatch.setattr(meet_ingest.ledger, 'mark_done', mark_done)
    monkeypatch.setattr(
        meet_ingest.transcriber, 'write_meet_output',
        lambda event, text, config, gemini_context=None: {
            'transcript_path': 't.md', 'summary_path': 's.md',
            '_text': text, '_gemini': gemini_context,
        },
    )
    return SimpleNamespace(mark_done=mark_done)


def test_transcript_and_gemini_path(monkeypatch, _wiring):
    monkeypatch.setattr(
        meet_ingest.calendar, 'attachments_for_occurrence',
        lambda event: OccurrenceAttachments(['t1'], 'g1'),
    )
    exports = {'t1': 'transcript body', 'g1': 'gemini notes'}
    monkeypatch.setattr(meet_ingest.drive, 'export_doc_markdown', lambda account, doc_id: exports[doc_id])

    written = meet_ingest.ingest_once(_config())

    assert len(written) == 1
    assert written[0]['_text'] == 'transcript body'
    assert written[0]['_gemini'] == 'gemini notes'
    _wiring.mark_done.assert_called_once_with('occ')


def test_transcript_only_concatenates_segments(monkeypatch, _wiring):
    monkeypatch.setattr(
        meet_ingest.calendar, 'attachments_for_occurrence',
        lambda event: OccurrenceAttachments(['s1', 's2'], None),
    )
    exports = {'s1': 'part one', 's2': 'part two'}
    monkeypatch.setattr(meet_ingest.drive, 'export_doc_markdown', lambda account, doc_id: exports[doc_id])

    written = meet_ingest.ingest_once(_config())

    assert written[0]['_text'] == 'part one\n\npart two'
    assert written[0]['_gemini'] is None


def test_gemini_only_uses_notes_as_body(monkeypatch, _wiring):
    monkeypatch.setattr(
        meet_ingest.calendar, 'attachments_for_occurrence',
        lambda event: OccurrenceAttachments([], 'g1'),
    )
    monkeypatch.setattr(meet_ingest.drive, 'export_doc_markdown', lambda account, doc_id: 'gemini body')

    written = meet_ingest.ingest_once(_config())

    # Gemini notes become the transcript body and are NOT also passed as extra context.
    assert written[0]['_text'] == 'gemini body'
    assert written[0]['_gemini'] is None


def test_nothing_attached_is_not_recorded(monkeypatch, _wiring):
    monkeypatch.setattr(
        meet_ingest.calendar, 'attachments_for_occurrence',
        lambda event: OccurrenceAttachments([], None),
    )

    written = meet_ingest.ingest_once(_config())

    assert written == []
    _wiring.mark_done.assert_not_called()


def test_done_only_marked_after_successful_write(monkeypatch, _wiring):
    monkeypatch.setattr(
        meet_ingest.calendar, 'attachments_for_occurrence',
        lambda event: OccurrenceAttachments(['t1'], None),
    )
    monkeypatch.setattr(meet_ingest.drive, 'export_doc_markdown', lambda account, doc_id: 'body')
    monkeypatch.setattr(
        meet_ingest.transcriber, 'write_meet_output',
        Mock(side_effect=RuntimeError('write failed')),
    )

    written = meet_ingest.ingest_once(_config())

    assert written == []
    _wiring.mark_done.assert_not_called()


def test_per_file_access_error_defers_and_calls_callback(monkeypatch):
    monkeypatch.setattr(meet_ingest.calendar, 'past_events', lambda config, hours: [_event()])
    monkeypatch.setattr(meet_ingest.ledger, 'should_skip', lambda event_id: False)
    monkeypatch.setattr(
        meet_ingest.calendar, 'attachments_for_occurrence',
        lambda event: OccurrenceAttachments(['t1'], None),
    )
    monkeypatch.setattr(
        meet_ingest.drive, 'export_doc_markdown',
        Mock(side_effect=DriveAccessError('not shared')),
    )
    record = Mock(return_value=SimpleNamespace(status='deferred', attempts=1))
    monkeypatch.setattr(meet_ingest.ledger, 'record_access_failure', record)
    monkeypatch.setattr(meet_ingest.ledger, 'mark_done', Mock())
    callback = Mock()

    written = meet_ingest.ingest_once(_config(), on_access_error=callback)

    assert written == []
    record.assert_called_once_with('occ', 3)
    callback.assert_called_once()
    assert callback.call_args.args[0].id == 'occ'


def test_access_error_callback_not_called_on_retry(monkeypatch):
    monkeypatch.setattr(meet_ingest.calendar, 'past_events', lambda config, hours: [_event()])
    monkeypatch.setattr(meet_ingest.ledger, 'should_skip', lambda event_id: False)
    monkeypatch.setattr(
        meet_ingest.calendar, 'attachments_for_occurrence',
        lambda event: OccurrenceAttachments(['t1'], None),
    )
    monkeypatch.setattr(
        meet_ingest.drive, 'export_doc_markdown', Mock(side_effect=DriveAccessError('x')),
    )
    # attempts == 2 -> a later retry, not the first failure.
    monkeypatch.setattr(
        meet_ingest.ledger, 'record_access_failure',
        Mock(return_value=SimpleNamespace(status='deferred', attempts=2)),
    )
    monkeypatch.setattr(meet_ingest.ledger, 'mark_done', Mock())
    callback = Mock()

    meet_ingest.ingest_once(_config(), on_access_error=callback)

    callback.assert_not_called()


def test_missing_scope_aborts_run_without_counting_attempt(monkeypatch):
    monkeypatch.setattr(meet_ingest.calendar, 'past_events', lambda config, hours: [_event()])
    monkeypatch.setattr(meet_ingest.ledger, 'should_skip', lambda event_id: False)
    monkeypatch.setattr(
        meet_ingest.calendar, 'attachments_for_occurrence',
        lambda event: OccurrenceAttachments(['t1'], None),
    )
    monkeypatch.setattr(
        meet_ingest.drive, 'export_doc_markdown', Mock(side_effect=DriveScopeError('re-auth')),
    )
    record = Mock()
    monkeypatch.setattr(meet_ingest.ledger, 'record_access_failure', record)

    with pytest.raises(DriveScopeError):
        meet_ingest.ingest_once(_config())

    record.assert_not_called()


def test_skipped_occurrence_is_not_processed(monkeypatch):
    monkeypatch.setattr(meet_ingest.calendar, 'past_events', lambda config, hours: [_event()])
    monkeypatch.setattr(meet_ingest.ledger, 'should_skip', lambda event_id: True)
    attachments = Mock()
    monkeypatch.setattr(meet_ingest.calendar, 'attachments_for_occurrence', attachments)

    written = meet_ingest.ingest_once(_config())

    assert written == []
    attachments.assert_not_called()


def test_per_occurrence_non_access_error_does_not_abort_batch(monkeypatch):
    good = _event(event_id='good', title='Good')
    bad = _event(event_id='bad', title='Bad')
    monkeypatch.setattr(meet_ingest.calendar, 'past_events', lambda config, hours: [bad, good])
    monkeypatch.setattr(meet_ingest.ledger, 'should_skip', lambda event_id: False)
    monkeypatch.setattr(meet_ingest.ledger, 'mark_done', Mock())
    monkeypatch.setattr(
        meet_ingest.calendar, 'attachments_for_occurrence',
        lambda event: OccurrenceAttachments(['t'], None),
    )

    def export(account, doc_id):
        return 'body'

    monkeypatch.setattr(meet_ingest.drive, 'export_doc_markdown', export)

    def write(event, text, config, gemini_context=None):
        if event.id == 'bad':
            raise RuntimeError('boom')
        return {'transcript_path': 't.md', 'summary_path': 's.md'}

    monkeypatch.setattr(meet_ingest.transcriber, 'write_meet_output', write)

    written = meet_ingest.ingest_once(_config())

    assert len(written) == 1
