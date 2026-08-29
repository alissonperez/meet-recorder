import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from meet_recorder import config as config_module
from meet_recorder import ledger, transcription_retry


@pytest.fixture(autouse=True)
def _ledger_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(ledger.config_module, 'config_dir', lambda: str(tmp_path))
    return tmp_path


@pytest.fixture
def wav(tmp_path):
    path = tmp_path / 'recording.wav'
    path.write_bytes(b'')
    return str(path)


def _config(max_retries=3):
    return SimpleNamespace(transcription_max_retries=max_retries)


def _ledger_file(ledger_dir):
    return json.loads((ledger_dir / transcription_retry.LEDGER_FILENAME).read_text())


def _age_last_attempt(ledger_dir, key, hours):
    '''Backdate an entry\'s last attempt so it reads as due without waiting.'''
    path = ledger_dir / transcription_retry.LEDGER_FILENAME
    entries = json.loads(path.read_text())
    entries[key]['last_attempt'] = (datetime.now().astimezone() - timedelta(hours=hours)).isoformat()
    path.write_text(json.dumps(entries))


def test_defer_records_a_deferred_entry(wav, _ledger_dir):
    entry = transcription_retry.defer(wav, _config())

    assert entry.status == 'deferred'
    assert entry.attempts == 1
    assert _ledger_file(_ledger_dir)[wav]['status'] == 'deferred'


def test_attempt_count_progresses_across_failures(wav):
    config = _config(max_retries=5)

    assert transcription_retry.defer(wav, config).attempts == 1
    assert transcription_retry.defer(wav, config).attempts == 2
    assert transcription_retry.defer(wav, config).attempts == 3


def test_abandoned_at_the_configured_maximum(wav):
    config = _config(max_retries=3)

    assert transcription_retry.defer(wav, config).status == 'deferred'
    assert transcription_retry.defer(wav, config).status == 'deferred'

    final = transcription_retry.defer(wav, config)
    assert final.status == 'abandoned'
    assert final.attempts == 3
    # An abandoned entry is never returned as due again.
    assert transcription_retry.due_paths(config) == []


def test_state_persists_across_a_simulated_restart(wav, _ledger_dir):
    config = _config(max_retries=5)
    transcription_retry.defer(wav, config)

    # A fresh Ledger instance re-reads the same file: what a relaunch sees.
    assert transcription_retry.defer(wav, config).attempts == 2
    assert _ledger_file(_ledger_dir)[wav]['attempts'] == 2


def test_due_paths_respects_the_hourly_interval(wav, _ledger_dir):
    config = _config(max_retries=5)
    transcription_retry.defer(wav, config)

    # Just deferred: throttled until the interval elapses.
    assert transcription_retry.due_paths(config) == []

    _age_last_attempt(_ledger_dir, wav, hours=2)

    assert transcription_retry.due_paths(config) == [wav]


def test_mark_done_stops_further_retries(wav):
    config = _config(max_retries=5)
    transcription_retry.defer(wav, config)
    transcription_retry.mark_done(wav, config)

    assert transcription_retry.due_paths(config) == []


def test_deleted_recording_is_dropped_instead_of_retried(tmp_path):
    config = _config(max_retries=5)
    missing = str(tmp_path / 'gone.wav')
    transcription_retry.defer(missing, config)

    assert transcription_retry.due_paths(config) == []


def test_falls_back_to_the_default_limit_without_a_config(wav):
    assert transcription_retry._max_retries(None) == config_module.DEFAULT_TRANSCRIPTION_MAX_RETRIES

    entry = transcription_retry.defer(wav, None)
    assert entry.status == 'deferred'
    assert entry.attempts == 1


def test_retention_outlives_the_full_retry_span():
    # 72 hourly attempts span 3 days; retention must be wider so an inactive
    # window (the app quit over a weekend) cannot prune a still-live entry.
    assert transcription_retry._ledger(_config(max_retries=72)).retention_days == 4
    assert transcription_retry._ledger(_config(max_retries=1)).retention_days == 2
