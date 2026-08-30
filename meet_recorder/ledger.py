import json
import logging
import os
import re
import tempfile
import threading
from collections import namedtuple
from datetime import datetime, timedelta

from meet_recorder import config as config_module

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = ('done', 'abandoned')

LedgerEntry = namedtuple('LedgerEntry', ['status', 'attempts'])


def _now():
    return datetime.now().astimezone()


def _parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


class Ledger:
    '''A namespaced, on-disk record of per-key processing status.

    Each namespace is one JSON file in the config directory, keyed by an opaque
    string (a Meet event id, a recording's .wav path), storing the entry shape
    ``{status, attempts, last_attempt}``. Retention and the deferred-retry
    throttle are per-namespace so unrelated callers can't disturb each other.
    '''

    def __init__(self, filename, retention_days, retry_interval_hours, prune_missing_paths=False):
        self.filename = filename
        self.retention_days = retention_days
        self.retry_interval_hours = retry_interval_hours
        self.prune_missing_paths = prune_missing_paths
        # Serializes read-modify-write of the ledger file: the CLI handler and the
        # menubar threads can both touch it (an accepted low-probability
        # cross-process race).
        self._lock = threading.Lock()

    # --- Internals -----------------------------------------------------------

    def _path(self):
        return os.path.join(config_module.config_dir(), self.filename)

    def _read_raw(self):
        path = self._path()
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

    def _write(self, entries):
        path = self._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)

        prefix = '.' + re.sub(r'\.json$', '', self.filename) + '-'
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix=prefix, suffix='.json')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(entries, f, indent=2)
            os.replace(tmp, path)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def _prune(self, entries, now):
        cutoff = now - timedelta(days=self.retention_days)
        kept = {}
        for key, entry in entries.items():
            last_attempt = _parse_dt((entry or {}).get('last_attempt'))
            if last_attempt is not None and last_attempt < cutoff:
                continue
            if self.prune_missing_paths and not os.path.exists(key):
                logger.debug(f'Dropping ledger entry for missing path: {key}')
                continue
            kept[key] = entry
        return kept

    def _load_and_prune(self, now):
        '''Load the ledger, drop stale entries, and persist the pruning when it changed.'''
        entries = self._read_raw()
        pruned = self._prune(entries, now)
        if len(pruned) != len(entries):
            self._write(pruned)
        return pruned

    def _is_due(self, entry, now):
        if (entry or {}).get('status') != 'deferred':
            return False
        last_attempt = _parse_dt(entry.get('last_attempt'))
        if last_attempt is None:
            return True
        return now - last_attempt >= timedelta(hours=self.retry_interval_hours)

    # --- Public API ----------------------------------------------------------

    def get(self, key, now=None):
        '''Return the (status, attempts) entry for a key, or None.'''
        now = now or _now()
        with self._lock:
            entry = self._load_and_prune(now).get(key)
        if entry is None:
            return None
        return LedgerEntry(entry.get('status'), int(entry.get('attempts', 0)))

    def should_skip(self, key, now=None):
        '''True when a key is terminal (done/abandoned) or a throttled deferred.'''
        now = now or _now()
        with self._lock:
            entry = self._load_and_prune(now).get(key)

        if entry is None:
            return False

        if entry.get('status') in TERMINAL_STATUSES:
            return True

        return entry.get('status') == 'deferred' and not self._is_due(entry, now)

    def due_keys(self, now=None):
        '''Return every deferred key whose retry interval has elapsed.'''
        now = now or _now()
        with self._lock:
            entries = self._load_and_prune(now)
        return [key for key, entry in entries.items() if self._is_due(entry, now)]

    def mark_done(self, key, now=None):
        '''Record a key as successfully processed (terminal).'''
        now = now or _now()
        with self._lock:
            entries = self._load_and_prune(now)
            existing = entries.get(key) or {}
            entries[key] = {
                'status': 'done',
                'attempts': int(existing.get('attempts', 0)),
                'last_attempt': now.isoformat(),
            }
            self._write(entries)

    def record_failure(self, key, max_retries, now=None):
        '''Record a failure for a key; transition to deferred or abandoned.

        Returns the resulting LedgerEntry so callers can tell a first failure
        (attempts == 1) from a later retry, and deferred from abandoned.'''
        now = now or _now()
        with self._lock:
            entries = self._load_and_prune(now)
            attempts = int((entries.get(key) or {}).get('attempts', 0)) + 1
            status = 'abandoned' if attempts >= max_retries else 'deferred'
            entries[key] = {
                'status': status,
                'attempts': attempts,
                'last_attempt': now.isoformat(),
            }
            self._write(entries)

        return LedgerEntry(status, attempts)


# Meet-transcript ingest namespace: 2-day retention, hourly deferred retry, and
# event-id keys (never filesystem paths, so path pruning stays off).
MEET_LEDGER = Ledger('processed_meet.json', retention_days=2, retry_interval_hours=1)
