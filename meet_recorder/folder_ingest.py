'''Ingest `.txt`/`.md` transcripts/notes dropped into configured local directories.

Each configured directory's top level is scanned (never its subdirectories). A file that
goes through the standard summary/output pipeline is moved into `<directory>/processed/`,
which is the whole dedup mechanism: the next scan simply no longer sees it, so success
never touches the ledger. A failure is recorded in a path-keyed ledger and retried on a
fixed hourly interval until `max_attempts`, after which the file is moved into
`<directory>/failed/` and left there.
'''

import logging
import math
import os
import shutil
from datetime import datetime

from meet_recorder import ledger, transcriber

logger = logging.getLogger(__name__)

LEDGER_FILENAME = 'processed_folder_ingest.json'
RETRY_INTERVAL_HOURS = 1
EXTENSIONS = ('.txt', '.md')
PROCESSED_DIRNAME = 'processed'
FAILED_DIRNAME = 'failed'


def _ledger(config):
    '''Build the folder-ingest ledger, sized so retention outlives the full retry span.'''
    retention_days = math.ceil(config.folder_ingest.max_attempts / 24) + 1
    return ledger.Ledger(
        LEDGER_FILENAME,
        retention_days=retention_days,
        retry_interval_hours=RETRY_INTERVAL_HOURS,
        prune_missing_paths=True,
    )


def scan_directory(directory):
    '''Return the absolute paths of the `.txt`/`.md` files at the directory's top level,
    sorted by filename. A missing or unreadable directory logs a warning and yields [].'''
    try:
        with os.scandir(directory) as entries:
            names = [
                entry.name for entry in entries
                if entry.is_file() and os.path.splitext(entry.name)[1].lower() in EXTENSIONS
            ]
    except OSError as e:
        logger.warning(f'Folder ingest: cannot list {directory} ({e}); skipping it this scan')
        return []

    return [os.path.abspath(os.path.join(directory, name)) for name in sorted(names)]


def _move_into(path, subdir_name):
    '''Move a file into a subdirectory next to it, adding `-1`, `-2`, ... before the
    extension when the destination name is taken. Returns the destination path.'''
    dest_dir = os.path.join(os.path.dirname(path), subdir_name)
    os.makedirs(dest_dir, exist_ok=True)

    stem, ext = os.path.splitext(os.path.basename(path))
    dest = os.path.join(dest_dir, f'{stem}{ext}')
    suffix = 1
    while os.path.exists(dest):
        dest = os.path.join(dest_dir, f'{stem}-{suffix}{ext}')
        suffix += 1

    shutil.move(path, dest)
    return dest


def _read_text(path):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    if not text.strip():
        raise ValueError('file is empty')
    return text


def _process_file(path, config):
    text = _read_text(path)
    timestamp = datetime.fromtimestamp(os.path.getmtime(path))
    return transcriber.ingest_text(text, config, timestamp=timestamp)


def _handle_failure(path, error, config, failures, on_failure):
    entry = failures.record_failure(path, config.folder_ingest.max_attempts)

    if entry.status != 'abandoned':
        logger.warning(
            f'Folder ingest: {path} failed ({error}); attempt {entry.attempts}/'
            f'{config.folder_ingest.max_attempts}, will retry in {RETRY_INTERVAL_HOURS}h'
        )
        return

    logger.error(f'Folder ingest: giving up on {path} after {entry.attempts} attempt(s): {error}')
    try:
        dest = _move_into(path, FAILED_DIRNAME)
        logger.info(f'Folder ingest: moved {path} -> {dest}')
    except OSError as e:
        logger.error(f'Folder ingest: could not move {path} into {FAILED_DIRNAME}/: {e}')

    if on_failure is not None:
        on_failure(path, error)


def ingest_once(config, on_failure=None):
    '''Scan every configured directory once and ingest each eligible file.

    Returns the list of {transcript_path, summary_path} dicts written this run. A per-file
    failure (undecodable/empty file, or any pipeline error) is recorded in the retry ledger
    and does not abort the batch; on_failure(path, error) is invoked once, when the file is
    abandoned and moved into `failed/`.'''
    failures = _ledger(config)
    written = []

    for directory in config.folder_ingest.directories:
        for path in scan_directory(directory):
            if failures.should_skip(path):
                logger.debug(f'Folder ingest: {path} skipped (ledger)')
                continue

            logger.info(f'Folder ingest: processing {path}')
            try:
                result = _process_file(path, config)
            except Exception as e:
                _handle_failure(path, e, config, failures, on_failure)
                continue

            try:
                dest = _move_into(path, PROCESSED_DIRNAME)
                logger.info(f'Folder ingest: {path} ingested -> {result["transcript_path"]}; moved to {dest}')
            except OSError as e:
                # The output is already written; leaving the file in place means it is
                # re-ingested on the next scan, so make the reason visible.
                logger.error(f'Folder ingest: could not move {path} into {PROCESSED_DIRNAME}/: {e}')

            written.append(result)

    return written
