import json
from datetime import datetime, timedelta, timezone

import pytest

from meet_recorder import ledger

UTC = timezone.utc


@pytest.fixture(autouse=True)
def _ledger_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(ledger.config_module, 'config_dir', lambda: str(tmp_path))
    return tmp_path


@pytest.fixture
def meet():
    '''A ledger shaped exactly like the Meet-ingest namespace.'''
    return ledger.Ledger('processed_meet.json', retention_days=2, retry_interval_hours=1)


def _now():
    return datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def test_missing_file_tolerated(meet):
    assert meet.get('e1', now=_now()) is None
    assert meet.should_skip('e1', now=_now()) is False


def test_corrupt_file_tolerated(meet, _ledger_dir):
    (_ledger_dir / meet.filename).write_text('{ not json')

    assert meet.get('e1', now=_now()) is None


def test_mark_done_is_terminal(meet):
    now = _now()
    meet.mark_done('e1', now=now)

    assert meet.get('e1', now=now).status == 'done'
    assert meet.should_skip('e1', now=now) is True


def test_failure_defers_then_abandons(meet):
    now = _now()

    first = meet.record_failure('e1', max_retries=3, now=now)
    assert first.status == 'deferred'
    assert first.attempts == 1

    second = meet.record_failure('e1', max_retries=3, now=now + timedelta(hours=1))
    assert second.status == 'deferred'
    assert second.attempts == 2

    third = meet.record_failure('e1', max_retries=3, now=now + timedelta(hours=2))
    assert third.status == 'abandoned'
    assert third.attempts == 3
    assert meet.should_skip('e1', now=now + timedelta(hours=2)) is True


def test_deferred_throttled_within_the_hour(meet):
    now = _now()
    meet.record_failure('e1', max_retries=3, now=now)

    # Fresh deferred is skipped within the retry interval...
    assert meet.should_skip('e1', now=now + timedelta(minutes=5)) is True
    # ...and retried once an hour has elapsed.
    assert meet.should_skip('e1', now=now + timedelta(hours=1, minutes=1)) is False


def test_rotation_drops_stale_entries(meet, _ledger_dir):
    now = _now()
    stale = (now - timedelta(days=3)).isoformat()
    fresh = (now - timedelta(hours=1)).isoformat()
    (_ledger_dir / meet.filename).write_text(json.dumps({
        'old': {'status': 'done', 'attempts': 0, 'last_attempt': stale},
        'recent': {'status': 'done', 'attempts': 0, 'last_attempt': fresh},
    }))

    # A load prunes and rewrites.
    assert meet.get('recent', now=now).status == 'done'
    assert meet.get('old', now=now) is None

    on_disk = json.loads((_ledger_dir / meet.filename).read_text())
    assert 'old' not in on_disk
    assert 'recent' in on_disk


def test_write_is_atomic_and_owner_readable(meet, _ledger_dir):
    now = _now()
    meet.mark_done('e1', now=now)

    on_disk = json.loads((_ledger_dir / meet.filename).read_text())
    assert on_disk['e1']['status'] == 'done'
    # No leftover temp files from the atomic replace.
    assert [p.name for p in _ledger_dir.iterdir()] == [meet.filename]


def test_meet_ledger_reproduces_the_shipped_constants():
    assert ledger.MEET_LEDGER.filename == 'processed_meet.json'
    assert ledger.MEET_LEDGER.retention_days == 2
    assert ledger.MEET_LEDGER.retry_interval_hours == 1
    assert ledger.MEET_LEDGER.prune_missing_paths is False


def test_namespaces_are_isolated(meet, _ledger_dir):
    other = ledger.Ledger('pending_transcriptions.json', retention_days=4, retry_interval_hours=1)
    now = _now()

    meet.mark_done('e1', now=now)

    assert other.get('e1', now=now) is None
    assert sorted(p.name for p in _ledger_dir.iterdir()) == ['processed_meet.json']


def test_due_keys_only_returns_elapsed_deferred_entries(meet):
    now = _now()
    meet.record_failure('due', max_retries=5, now=now - timedelta(hours=2))
    meet.record_failure('not-due', max_retries=5, now=now - timedelta(minutes=10))
    meet.mark_done('finished', now=now)
    meet.record_failure('spent', max_retries=1, now=now - timedelta(hours=2))

    assert meet.due_keys(now=now) == ['due']


def test_due_keys_is_empty_without_a_ledger_file(meet):
    assert meet.due_keys(now=_now()) == []


def test_missing_paths_pruned_when_enabled(tmp_path):
    paths = ledger.Ledger(
        'pending_transcriptions.json', retention_days=4,
        retry_interval_hours=1, prune_missing_paths=True,
    )
    now = _now()
    present = tmp_path / 'present.wav'
    present.write_bytes(b'')
    missing = str(tmp_path / 'gone.wav')

    paths.record_failure(str(present), max_retries=5, now=now - timedelta(hours=2))
    paths.record_failure(missing, max_retries=5, now=now - timedelta(hours=2))

    assert paths.due_keys(now=now) == [str(present)]
    assert paths.get(missing, now=now) is None


def test_missing_paths_kept_when_pruning_is_off(meet):
    now = _now()
    meet.record_failure('/no/such/file.wav', max_retries=5, now=now - timedelta(hours=2))

    assert meet.due_keys(now=now) == ['/no/such/file.wav']
