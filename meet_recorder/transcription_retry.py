'''Deferred retry (layer 2) for transcriptions that failed their immediate retries.

Keyed by the recording's `.wav` path as it was when the entry was created. A successful
run renames the recording to carry its meeting title as its last step, so entries stay
keyed by the pre-rename path and a succeeding retry must be marked done under that same
path - the rename happens only on success, where the entry is being cleared anyway. The
menu bar app is the only caller: it owns the long-running process whose timer fires the
scan (a CLI run exits before any retry could happen, so it keeps failing terminally).
'''

import math

from meet_recorder import ledger
from meet_recorder.config import DEFAULT_TRANSCRIPTION_MAX_RETRIES

LEDGER_FILENAME = 'pending_transcriptions.json'
RETRY_INTERVAL_HOURS = 1


def _max_retries(config):
    '''The configured attempt budget, falling back to the default when config failed to load.'''
    if config is None:
        return DEFAULT_TRANSCRIPTION_MAX_RETRIES
    return config.transcription_max_retries


def _ledger(config):
    '''Build the transcription ledger, sized so retention outlives the full retry span.'''
    max_retries = _max_retries(config)
    retention_days = math.ceil(max_retries / 24) + 1
    return ledger.Ledger(
        LEDGER_FILENAME,
        retention_days=retention_days,
        retry_interval_hours=RETRY_INTERVAL_HOURS,
        prune_missing_paths=True,
    )


def defer(path, config):
    '''Record a failed transcription for a later retry.

    Returns the resulting LedgerEntry so the caller can tell `deferred` (stay quiet)
    from `abandoned` (notify the user, once).'''
    return _ledger(config).record_failure(path, _max_retries(config))


def due_paths(config):
    '''Return every deferred `.wav` path whose retry interval has elapsed.'''
    return _ledger(config).due_keys()


def mark_done(path, config):
    '''Mark a deferred transcription as finally succeeded, so it is not retried again.'''
    _ledger(config).mark_done(path)
