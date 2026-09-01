from slugify import slugify

# Meeting titles are slugified into both the recording filename and the transcript/summary
# filenames. Keeping the rule here (rather than duplicating it in recorder.py and
# transcriber.py) is what keeps a recording sorting next to, and reading like, its transcript.
TITLE_SLUG_MAX_LENGTH = 80


def slugify_title(title):
    '''Slugified, length-capped, filesystem-safe form of a meeting title.

    Returns '' for a title that is empty or slugifies to nothing (e.g. all punctuation or
    emoji), so callers can treat "no usable title" as a single case.'''
    if not title:
        return ''

    return slugify(title, lowercase=False)[:TITLE_SLUG_MAX_LENGTH]
