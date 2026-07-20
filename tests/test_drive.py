import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from googleapiclient.errors import HttpError

from meet_recorder import drive
from meet_recorder.drive import DriveAccessError, DriveScopeError


# --- doc_id_from_url ---------------------------------------------------------

def test_doc_id_from_transcript_url():
    url = 'https://docs.google.com/document/d/1AbC_dEf/edit?usp=drive_web'
    assert drive.doc_id_from_url(url) == '1AbC_dEf'


def test_doc_id_from_gemini_url():
    url = 'https://docs.google.com/document/d/XYZ-123/edit?usp=meet_tnfm_calendar'
    assert drive.doc_id_from_url(url) == 'XYZ-123'


def test_doc_id_from_non_docs_url_returns_none():
    # A Drive `/file/d/` URL is not a Google Doc.
    assert drive.doc_id_from_url('https://drive.google.com/file/d/NOPE/view') is None


def test_doc_id_from_malformed_input_returns_none():
    assert drive.doc_id_from_url('') is None
    assert drive.doc_id_from_url(None) is None
    assert drive.doc_id_from_url('not-a-url') is None
    assert drive.doc_id_from_url('https://docs.google.com/document/d/') is None


# --- export_doc_markdown -----------------------------------------------------

def _service_returning(content):
    export = Mock()
    export.execute = Mock(return_value=content)
    files = Mock()
    files.export = Mock(return_value=export)
    service = Mock()
    service.files = Mock(return_value=files)
    return service


def _service_raising(error):
    export = Mock()
    export.execute = Mock(side_effect=error)
    files = Mock()
    files.export = Mock(return_value=export)
    service = Mock()
    service.files = Mock(return_value=files)
    return service


def _http_error(status, message):
    resp = SimpleNamespace(status=status, reason='')
    content = json.dumps({'error': {'code': status, 'message': message}}).encode('utf-8')
    return HttpError(resp, content)


def test_export_returns_decoded_markdown(monkeypatch):
    monkeypatch.setattr(drive, '_build_service', lambda account: _service_returning(b'# Heading\ntext'))

    result = drive.export_doc_markdown('personal', 'file-1')

    assert result == '# Heading\ntext'


def test_export_missing_scope_raises_scope_error(monkeypatch):
    error = _http_error(403, 'Request had insufficient authentication scopes.')
    monkeypatch.setattr(drive, '_build_service', lambda account: _service_raising(error))

    with pytest.raises(DriveScopeError, match='calendar_auth --account personal'):
        drive.export_doc_markdown('personal', 'file-1')


def test_export_per_file_permission_raises_access_error(monkeypatch):
    error = _http_error(404, 'File not found: file-1.')
    monkeypatch.setattr(drive, '_build_service', lambda account: _service_raising(error))

    with pytest.raises(DriveAccessError):
        drive.export_doc_markdown('personal', 'file-1')


def test_export_403_without_scope_marker_is_access_error(monkeypatch):
    # A 403 that is about the file (not the token scope) is a per-file access error.
    error = _http_error(403, 'The user does not have sufficient permissions for file file-1.')
    monkeypatch.setattr(drive, '_build_service', lambda account: _service_raising(error))

    with pytest.raises(DriveAccessError):
        drive.export_doc_markdown('personal', 'file-1')
