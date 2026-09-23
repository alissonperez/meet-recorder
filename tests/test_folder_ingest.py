import json
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from meet_recorder import folder_ingest, ledger


@pytest.fixture(autouse=True)
def _ledger_dir(monkeypatch, tmp_path):
    ledger_dir = tmp_path / 'config'
    ledger_dir.mkdir()
    monkeypatch.setattr(ledger.config_module, 'config_dir', lambda: str(ledger_dir))
    return ledger_dir


@pytest.fixture
def inbox(tmp_path):
    path = tmp_path / 'inbox'
    path.mkdir()
    return path


@pytest.fixture
def ingest_text(monkeypatch):
    '''Stub the standard pipeline: record calls and return fake output paths.'''
    mock = Mock(side_effect=lambda text, config, timestamp=None: {
        'transcript_path': f't-{text}.md', 'summary_path': f's-{text}.md',
    })
    monkeypatch.setattr(folder_ingest.transcriber, 'ingest_text', mock)
    return mock


def _config(*directories, max_attempts=3):
    return SimpleNamespace(folder_ingest=SimpleNamespace(
        directories=[str(d) for d in directories], max_attempts=max_attempts,
    ))


def _ledger_entries(ledger_dir):
    path = ledger_dir / folder_ingest.LEDGER_FILENAME
    return json.loads(path.read_text()) if path.exists() else {}


def _age_last_attempt(ledger_dir, key, hours):
    '''Backdate an entry's last attempt so it reads as due without waiting.'''
    path = ledger_dir / folder_ingest.LEDGER_FILENAME
    entries = json.loads(path.read_text())
    entries[key]['last_attempt'] = (datetime.now().astimezone() - timedelta(hours=hours)).isoformat()
    path.write_text(json.dumps(entries))


# --- Directory scan -------------------------------------------------------------------


def test_scan_picks_txt_and_md_case_insensitive_sorted(inbox):
    for name in ('b.md', 'a.TXT', 'c.Md', 'skip.pdf', 'noext'):
        (inbox / name).write_text('x')
    (inbox / 'processed').mkdir()
    (inbox / 'processed' / 'old.txt').write_text('x')
    (inbox / 'dir.txt').mkdir()

    paths = folder_ingest.scan_directory(str(inbox))

    assert [os.path.basename(p) for p in paths] == ['a.TXT', 'b.md', 'c.Md']
    assert all(os.path.isabs(p) for p in paths)


def test_scan_missing_directory_yields_nothing(tmp_path):
    assert folder_ingest.scan_directory(str(tmp_path / 'nope')) == []


# --- Ledger namespace -----------------------------------------------------------------


def test_ledger_retention_outlives_the_full_retry_span():
    assert folder_ingest._ledger(_config(max_attempts=3)).retention_days == 2
    assert folder_ingest._ledger(_config(max_attempts=72)).retention_days == 4


def test_ledger_is_path_keyed_hourly_and_prunes_missing_paths():
    failures = folder_ingest._ledger(_config())

    assert failures.filename == 'processed_folder_ingest.json'
    assert failures.retry_interval_hours == 1
    assert failures.prune_missing_paths is True


def test_ledger_deferred_then_abandoned(inbox):
    path = str(inbox / 'a.txt')
    (inbox / 'a.txt').write_text('x')
    failures = folder_ingest._ledger(_config(max_attempts=2))

    assert failures.record_failure(path, 2).status == 'deferred'
    assert failures.record_failure(path, 2).status == 'abandoned'
    assert failures.should_skip(path) is True


def test_ledger_throttles_deferred_entries_hourly(inbox, _ledger_dir):
    path = str(inbox / 'a.txt')
    (inbox / 'a.txt').write_text('x')
    failures = folder_ingest._ledger(_config())
    failures.record_failure(path, 3)

    assert failures.should_skip(path) is True

    _age_last_attempt(_ledger_dir, path, hours=2)

    assert failures.should_skip(path) is False


def test_ledger_prunes_entries_whose_path_is_gone(inbox, _ledger_dir):
    path = inbox / 'a.txt'
    path.write_text('x')
    failures = folder_ingest._ledger(_config())
    failures.record_failure(str(path), 3)

    path.unlink()

    assert failures.get(str(path)) is None
    assert _ledger_entries(_ledger_dir) == {}


# --- ingest_once ----------------------------------------------------------------------


def test_success_moves_file_to_processed_without_ledger_write(inbox, ingest_text, _ledger_dir):
    source = inbox / 'notes.txt'
    source.write_text('hello', encoding='utf-8')
    mtime = datetime(2025, 3, 4, 9, 30).timestamp()
    os.utime(source, (mtime, mtime))

    written = folder_ingest.ingest_once(_config(inbox))

    assert written == [{'transcript_path': 't-hello.md', 'summary_path': 's-hello.md'}]
    assert ingest_text.call_args.kwargs['timestamp'] == datetime.fromtimestamp(mtime)
    assert not source.exists()
    assert (inbox / 'processed' / 'notes.txt').read_text() == 'hello'
    assert not (inbox / 'failed').exists()
    assert _ledger_entries(_ledger_dir) == {}


def test_second_run_is_a_no_op(inbox, ingest_text):
    (inbox / 'notes.md').write_text('hello')
    config = _config(inbox)

    folder_ingest.ingest_once(config)
    assert folder_ingest.ingest_once(config) == []
    assert ingest_text.call_count == 1


def test_failure_defers_and_leaves_file_in_place(inbox, ingest_text, _ledger_dir):
    source = inbox / 'notes.txt'
    source.write_text('hello')
    ingest_text.side_effect = RuntimeError('llm down')
    on_failure = Mock()

    assert folder_ingest.ingest_once(_config(inbox), on_failure=on_failure) == []

    assert source.exists()
    assert _ledger_entries(_ledger_dir)[str(source)]['status'] == 'deferred'
    on_failure.assert_not_called()


def test_throttled_deferred_file_is_skipped(inbox, ingest_text):
    source = inbox / 'notes.txt'
    source.write_text('hello')
    ingest_text.side_effect = RuntimeError('llm down')
    config = _config(inbox)
    folder_ingest.ingest_once(config)

    folder_ingest.ingest_once(config)

    assert ingest_text.call_count == 1
    assert source.exists()


def test_deferred_file_retried_once_due(inbox, ingest_text, _ledger_dir):
    source = inbox / 'notes.txt'
    source.write_text('hello')
    ingest_text.side_effect = [RuntimeError('llm down'), {'transcript_path': 't', 'summary_path': 's'}]
    config = _config(inbox)
    folder_ingest.ingest_once(config)
    _age_last_attempt(_ledger_dir, str(source), hours=2)

    written = folder_ingest.ingest_once(config)

    assert written == [{'transcript_path': 't', 'summary_path': 's'}]
    assert (inbox / 'processed' / 'notes.txt').exists()


def test_abandonment_moves_to_failed_and_notifies_once(inbox, ingest_text, _ledger_dir):
    source = inbox / 'notes.txt'
    source.write_text('hello')
    error = RuntimeError('llm down')
    ingest_text.side_effect = error
    config = _config(inbox, max_attempts=2)
    on_failure = Mock()

    folder_ingest.ingest_once(config, on_failure=on_failure)
    _age_last_attempt(_ledger_dir, str(source), hours=2)
    folder_ingest.ingest_once(config, on_failure=on_failure)
    folder_ingest.ingest_once(config, on_failure=on_failure)

    on_failure.assert_called_once_with(str(source), error)
    assert not source.exists()
    assert (inbox / 'failed' / 'notes.txt').read_text() == 'hello'
    assert ingest_text.call_count == 2


def test_decode_error_goes_through_the_failure_path(inbox, ingest_text, _ledger_dir):
    source = inbox / 'binary.txt'
    source.write_bytes(b'\xff\xfe\x00bad')
    on_failure = Mock()

    folder_ingest.ingest_once(_config(inbox, max_attempts=1), on_failure=on_failure)

    ingest_text.assert_not_called()
    on_failure.assert_called_once()
    assert isinstance(on_failure.call_args.args[1], UnicodeDecodeError)
    assert (inbox / 'failed' / 'binary.txt').exists()


def test_empty_file_goes_through_the_failure_path(inbox, ingest_text, _ledger_dir):
    source = inbox / 'empty.md'
    source.write_text('  \n')

    folder_ingest.ingest_once(_config(inbox))

    ingest_text.assert_not_called()
    assert source.exists()
    assert _ledger_entries(_ledger_dir)[str(source)]['status'] == 'deferred'


@pytest.mark.parametrize('subdir', ['processed', 'failed'])
def test_move_collision_gets_numeric_suffix(inbox, ingest_text, subdir):
    (inbox / subdir).mkdir()
    (inbox / subdir / 'notes.txt').write_text('older')
    (inbox / subdir / 'notes-1.txt').write_text('older still')
    (inbox / 'notes.txt').write_text('new')
    if subdir == 'failed':
        ingest_text.side_effect = RuntimeError('boom')

    folder_ingest.ingest_once(_config(inbox, max_attempts=1))

    assert (inbox / subdir / 'notes.txt').read_text() == 'older'
    assert (inbox / subdir / 'notes-1.txt').read_text() == 'older still'
    assert (inbox / subdir / 'notes-2.txt').read_text() == 'new'
    assert not (inbox / 'notes.txt').exists()


def test_missing_directory_does_not_abort_other_directories(tmp_path, inbox, ingest_text):
    (inbox / 'notes.txt').write_text('hello')

    written = folder_ingest.ingest_once(_config(tmp_path / 'missing', inbox))

    assert len(written) == 1
    assert (inbox / 'processed' / 'notes.txt').exists()


def test_one_failing_file_does_not_block_the_next(inbox, ingest_text):
    (inbox / 'a.txt').write_text('bad')
    (inbox / 'b.txt').write_text('good')
    ingest_text.side_effect = [RuntimeError('boom'), {'transcript_path': 't', 'summary_path': 's'}]

    written = folder_ingest.ingest_once(_config(inbox))

    assert written == [{'transcript_path': 't', 'summary_path': 's'}]
    assert (inbox / 'a.txt').exists()
    assert (inbox / 'processed' / 'b.txt').exists()
