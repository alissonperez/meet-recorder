import logging
import urllib.parse

logger = logging.getLogger(__name__)


class DriveError(Exception):
    pass


class DriveScopeError(DriveError):
    '''The account token lacks the Drive scope — a run-level failure needing re-auth.'''
    pass


class DriveAccessError(DriveError):
    '''A specific Doc could not be read (per-file permission) — a per-occurrence failure.'''
    pass


# --- URL parsing -------------------------------------------------------------

def doc_id_from_url(file_url):
    '''Extract the Doc id from a `/document/d/<ID>/...` URL using urllib (no regex).

    Returns None for empty input or non-Google-Docs URLs (e.g. a Drive `/file/d/` URL).'''
    if not file_url:
        return None

    parts = urllib.parse.urlparse(file_url).path.split('/')
    for i, segment in enumerate(parts):
        if segment == 'document' and i + 2 < len(parts) and parts[i + 1] == 'd':
            return parts[i + 2] or None
    return None


# --- Doc export --------------------------------------------------------------

def _build_service(account):
    from googleapiclient.discovery import build

    # Imported lazily to avoid a circular import: calendar imports this module.
    from meet_recorder import calendar

    creds = calendar.build_credentials(account)
    return build('drive', 'v3', credentials=creds, cache_discovery=False)


def _classify_http_error(error, account, file_id):
    status = getattr(getattr(error, 'resp', None), 'status', None)
    detail = str(error).lower()
    scope_markers = (
        'insufficient authentication scope',
        'insufficientpermissions',
        'access_token_scope_insufficient',
    )

    if str(status) == '403' and any(marker in detail for marker in scope_markers):
        return DriveScopeError(
            f'Account "{account}" token lacks Drive access; '
            f're-run `calendar_auth --account {account}` to grant Drive access'
        )

    return DriveAccessError(
        f'Could not read Drive doc {file_id} for account "{account}": {error}'
    )


def export_doc_markdown(account, file_id):
    '''Export a Google Doc (by file id) to Markdown text via the Drive API.

    Raises DriveScopeError when the account token predates the Drive scope, and
    DriveAccessError when the specific doc cannot be read.'''
    from googleapiclient.errors import HttpError

    service = _build_service(account)
    try:
        content = service.files().export(fileId=file_id, mimeType='text/markdown').execute()
    except HttpError as e:
        raise _classify_http_error(e, account, file_id)

    if isinstance(content, bytes):
        return content.decode('utf-8')
    return content
