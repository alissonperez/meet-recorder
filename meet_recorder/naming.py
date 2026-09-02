import logging
import os
from datetime import datetime

from slugify import slugify

logger = logging.getLogger(__name__)

# Meeting titles are slugified into both the recording filename and the transcript/summary
# filenames. Keeping the rule here (rather than duplicating it in transcriber.py's two
# callers) is what keeps a recording sorting next to, and reading like, its transcript.
TITLE_SLUG_MAX_LENGTH = 80

RECORDING_TIMESTAMP_FORMAT = '%Y-%m-%d_%H-%M-%S'
# The format renders at a fixed width, so the timestamp that prefixes a recording filename can
# be sliced off unambiguously whether or not a meeting-title suffix follows it. Derived from
# the format itself so the two cannot drift apart.
RECORDING_TIMESTAMP_LENGTH = len(datetime(2000, 1, 1).strftime(RECORDING_TIMESTAMP_FORMAT))

TITLE_SEPARATOR = ' - '


def slugify_title(title):
    '''Slugified, length-capped, filesystem-safe form of a meeting title.

    Returns '' for a title that is empty or slugifies to nothing (e.g. all punctuation or
    emoji), so callers can treat "no usable title" as a single case.'''
    if not title:
        return ''

    return slugify(title, lowercase=False)[:TITLE_SLUG_MAX_LENGTH]


def timestamp_prefix(path):
    '''The leading start-timestamp slice of a recording filename, or None if it doesn't parse.

    Returned as the original string rather than a datetime: callers renaming the file need to
    reproduce it byte-for-byte, and re-formatting a parsed value would be a chance to drift.'''
    stem = os.path.splitext(os.path.basename(path))[0]
    prefix = stem[:RECORDING_TIMESTAMP_LENGTH]

    try:
        datetime.strptime(prefix, RECORDING_TIMESTAMP_FORMAT)
    except ValueError:
        return None

    return prefix


def rename_recording_with_title(path, title):
    '''Rename a recording in place to '<start timestamp> - <title slug>.wav', returning the
    resulting path.

    Cosmetic by nature and always run after the audio and any derived output are already safe
    on disk, so it must never cost the user a recording: every reason not to rename - an empty
    slug, a filename with no parseable timestamp prefix, a name that is already correct, a
    taken destination, an OS-level failure - is logged where it is worth knowing about and
    returns `path` unchanged.'''
    try:
        slug = slugify_title(title)
        if not slug:
            return path

        # Rebuilt from the filename's own prefix, never from a parsed timestamp: a recording
        # whose name carries no timestamp is left alone rather than being given one derived
        # from its mtime, which would assert a start time the system does not actually know.
        prefix = timestamp_prefix(path)
        if prefix is None:
            logger.warning(f'Not renaming {path}: no start timestamp in its filename')
            return path

        extension = os.path.splitext(path)[1]
        titled_path = os.path.join(
            os.path.dirname(path), f'{prefix}{TITLE_SEPARATOR}{slug}{extension}',
        )

        if titled_path == path:
            return path

        # os.rename() replaces the destination silently on POSIX. A collision needs two
        # recordings sharing a start second *and* a title, but the cost of being wrong is a
        # destroyed recording, so check rather than rely on it never happening.
        if os.path.exists(titled_path):
            logger.warning(f'Not renaming {path} to {titled_path}: destination already exists')
            return path

        os.rename(path, titled_path)
        logger.info(f'Renamed recording to {titled_path}')
        return titled_path
    except Exception as e:
        logger.warning(f'Could not rename {path} with its meeting title: {e}')
        return path
