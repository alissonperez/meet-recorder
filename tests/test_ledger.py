import json
from datetime import datetime, timedelta, timezone

import pytest

from meet_recorder import ledger

UTC = timezone.utc


@pytest.fixture(autouse=True)
def _ledger_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(ledger.config_module, 'config_dir', lambda: str(tmp_path))
    return tmp_path


def _now():
    return datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def test_missing_file_tolerated():
    assert ledger.get('e1', now=_now()) is None
    assert ledger.should_skip('e1', now=_now()) is False


def test_corrupt_file_tolerated(_ledger_dir):
    (_ledger_dir / ledger.LEDGER_FILENAME).write_text('{ not json')

    assert ledger.get('e1', now=_now()) is None


def test_mark_done_is_terminal():
    now = _now()
    ledger.mark_done('e1', now=now)

    assert ledger.get('e1', now=now).status == 'done'
    assert ledger.should_skip('e1', now=now) is True


def test_access_failure_defers_then_abandons():
    now = _now()

    first = ledger.record_access_failure('e1', max_retries=3, now=now)
    assert first.status == 'deferred'
    assert first.attempts == 1

    second = ledger.record_access_failure('e1', max_retries=3, now=now + timedelta(hours=1))
    assert second.status == 'deferred'
    assert second.attempts == 2

    third = ledger.record_access_failure('e1', max_retries=3, now=now + timedelta(hours=2))
    assert third.status == 'abandoned'
    assert third.attempts == 3
    assert ledger.should_skip('e1', now=now + timedelta(hours=2)) is True


def test_deferred_throttled_within_the_hour():
    now = _now()
    ledger.record_access_failure('e1', max_retries=3, now=now)

    # Fresh deferred is skipped within the retry interval...
    assert ledger.should_skip('e1', now=now + timedelta(minutes=5)) is True
    # ...and retried once an hour has elapsed.
    assert ledger.should_skip('e1', now=now + timedelta(hours=1, minutes=1)) is False


def test_rotation_drops_stale_entries(_ledger_dir):
    now = _now()
    stale = (now - timedelta(days=3)).isoformat()
    fresh = (now - timedelta(hours=1)).isoformat()
    (_ledger_dir / ledger.LEDGER_FILENAME).write_text(json.dumps({
        'old': {'status': 'done', 'attempts': 0, 'last_attempt': stale},
        'recent': {'status': 'done', 'attempts': 0, 'last_attempt': fresh},
    }))

    # A load prunes and rewrites.
    assert ledger.get('recent', now=now).status == 'done'
    assert ledger.get('old', now=now) is None

    on_disk = json.loads((_ledger_dir / ledger.LEDGER_FILENAME).read_text())
    assert 'old' not in on_disk
    assert 'recent' in on_disk


def test_write_is_atomic_and_owner_readable(_ledger_dir):
    now = _now()
    ledger.mark_done('e1', now=now)

    on_disk = json.loads((_ledger_dir / ledger.LEDGER_FILENAME).read_text())
    assert on_disk['e1']['status'] == 'done'
    # No leftover temp files from the atomic replace.
    assert [p.name for p in _ledger_dir.iterdir()] == [ledger.LEDGER_FILENAME]
