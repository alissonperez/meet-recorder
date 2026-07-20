import json
import logging
import os
import tempfile
import threading
from collections import namedtuple
from datetime import datetime, timedelta

from meet_recorder import config as config_module

logger = logging.getLogger(__name__)

LEDGER_FILENAME = 'processed_meet.json'
LEDGER_RETENTION_DAYS = 2
ACCESS_RETRY_INTERVAL_HOURS = 1

TERMINAL_STATUSES = ('done', 'abandoned')

# Serializes read-modify-write of the ledger file: the CLI handler and the menubar
# ingest thread can both touch it (an accepted low-probability cross-process race).
_LEDGER_LOCK = threading.Lock()

LedgerEntry = namedtuple('LedgerEntry', ['status', 'attempts'])


def _now():
    return datetime.now().astimezone()


def _path():
    return os.path.join(config_module.config_dir(), LEDGER_FILENAME)


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _read_raw():
    path = _path()
    if not os.path.isfile(path):
        return {}

    try:
        with open(path) as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f'Ledger at {path} is unreadable ({e}); starting fresh')
        return {}

    if not isinstance(data, dict):
        logger.warning(f'Ledger at {path} is not a mapping; starting fresh')
        return {}
    return data


def _write(entries):
    path = _path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.processed_meet-', suffix='.json')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(entries, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _prune(entries, now):
    cutoff = now - timedelta(days=LEDGER_RETENTION_DAYS)
    kept = {}
    for event_id, entry in entries.items():
        last_attempt = _parse_dt((entry or {}).get('last_attempt'))
        if last_attempt is None or last_attempt >= cutoff:
            kept[event_id] = entry
    return kept


def _load_and_prune(now):
    '''Load the ledger, drop stale entries, and persist the pruning when it changed.'''
    entries = _read_raw()
    pruned = _prune(entries, now)
    if len(pruned) != len(entries):
        _write(pruned)
    return pruned


# --- Public API --------------------------------------------------------------

def get(event_id, now=None):
    '''Return the (status, attempts) entry for an occurrence, or None.'''
    now = now or _now()
    with _LEDGER_LOCK:
        entry = _load_and_prune(now).get(event_id)
    if entry is None:
        return None
    return LedgerEntry(entry.get('status'), int(entry.get('attempts', 0)))


def should_skip(event_id, now=None):
    '''True when an occurrence is terminal (done/abandoned) or a throttled deferred.'''
    now = now or _now()
    with _LEDGER_LOCK:
        entry = _load_and_prune(now).get(event_id)

    if entry is None:
        return False

    status = entry.get('status')
    if status in TERMINAL_STATUSES:
        return True

    if status == 'deferred':
        last_attempt = _parse_dt(entry.get('last_attempt'))
        if last_attempt is not None and now - last_attempt < timedelta(hours=ACCESS_RETRY_INTERVAL_HOURS):
            return True

    return False


def mark_done(event_id, now=None):
    '''Record an occurrence as successfully processed (terminal).'''
    now = now or _now()
    with _LEDGER_LOCK:
        entries = _load_and_prune(now)
        existing = entries.get(event_id) or {}
        entries[event_id] = {
            'status': 'done',
            'attempts': int(existing.get('attempts', 0)),
            'last_attempt': now.isoformat(),
        }
        _write(entries)


def record_access_failure(event_id, max_retries, now=None):
    '''Record a per-file access failure; transition to deferred or abandoned.

    Returns the resulting LedgerEntry so callers can tell a first failure (attempts == 1,
    which gates the once-per-event access-error callback) from a later retry.'''
    now = now or _now()
    with _LEDGER_LOCK:
        entries = _load_and_prune(now)
        attempts = int((entries.get(event_id) or {}).get('attempts', 0)) + 1
        status = 'abandoned' if attempts >= max_retries else 'deferred'
        entries[event_id] = {
            'status': status,
            'attempts': attempts,
            'last_attempt': now.isoformat(),
        }
        _write(entries)

    return LedgerEntry(status, attempts)
