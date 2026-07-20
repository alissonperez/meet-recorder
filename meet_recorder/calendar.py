import json
import logging
import os
import threading
from collections import namedtuple
from datetime import datetime, timedelta

from slugify import slugify

from meet_recorder import config as config_module
from meet_recorder import drive

logger = logging.getLogger(__name__)

CALENDAR_SCOPES = [
    'https://www.googleapis.com/auth/calendar.readonly',
    'https://www.googleapis.com/auth/drive.readonly',
]

OccurrenceAttachments = namedtuple('OccurrenceAttachments', ['transcript_ids', 'gemini_id'])

# Serializes token file read/refresh/write: menubar transcription threads and the
# main-thread autorecord poll can both hit the same token file concurrently.
_token_lock = threading.Lock()


class CalendarError(Exception):
    pass


class CalendarEvent:
    def __init__(self, event_id, title, calendar, start_dt, end_dt, start_raw, end_raw, attendees,
                 attachments=None):
        self.id = event_id
        self.title = title
        self.calendar = calendar
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.start_raw = start_raw
        self.end_raw = end_raw
        self.attendees = attendees
        self.attachments = attachments or []


# --- Credentials / token persistence ----------------------------------------

def _write_token(account, creds):
    path = config_module.token_path(account)
    os.makedirs(os.path.dirname(path), exist_ok=True)

    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write(creds.to_json())
    os.chmod(path, 0o600)


def build_credentials(account):
    '''Load an account's OAuth credentials, refreshing and persisting if expired.

    Raises CalendarError on missing or malformed token files.'''
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    path = config_module.token_path(account)
    if not os.path.isfile(path):
        raise CalendarError(
            f'Token file not found for account "{account}" at {path}; run calendar_auth first'
        )

    with _token_lock:
        try:
            creds = Credentials.from_authorized_user_file(path, CALENDAR_SCOPES)
        except (ValueError, KeyError, json.JSONDecodeError) as e:
            raise CalendarError(f'Token file for account "{account}" is invalid: {e}')

        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception as e:
                raise CalendarError(f'Failed to refresh token for account "{account}": {e}')
            _write_token(account, creds)

    return creds


def run_auth_flow(account):
    '''Run the interactive OAuth flow for an account and write its token file (0600).'''
    from google_auth_oauthlib.flow import InstalledAppFlow

    creds_path = config_module.credentials_path(account)
    if not os.path.isfile(creds_path):
        raise CalendarError(
            f'Credentials file not found for account "{account}" at {creds_path}'
        )

    flow = InstalledAppFlow.from_client_secrets_file(creds_path, CALENDAR_SCOPES)
    creds = flow.run_local_server()
    _write_token(account, creds)

    return config_module.token_path(account)


# --- Event querying / filtering ---------------------------------------------

def _build_service(account):
    from googleapiclient.discovery import build

    creds = build_credentials(account)
    return build('calendar', 'v3', credentials=creds, cache_discovery=False)


def _query_events(account, time_min, time_max):
    service = _build_service(account)
    result = service.events().list(
        calendarId='primary',
        timeMin=time_min.isoformat(),
        timeMax=time_max.isoformat(),
        singleEvents=True,
        orderBy='startTime',
    ).execute()

    return result.get('items', [])


def _is_declined(event):
    for attendee in (event.get('attendees') or []):
        if attendee.get('self') and attendee.get('responseStatus') == 'declined':
            return True
    return False


def _is_accepted(event):
    if (event.get('organizer') or {}).get('self'):
        return True
    for attendee in (event.get('attendees') or []):
        if attendee.get('self'):
            return attendee.get('responseStatus') == 'accepted'
    return False


def _matches_ignore_slug(event, ignored_slugs):
    if not ignored_slugs:
        return False

    title_slug = slugify(event.get('summary', ''))
    return any(ignored in title_slug for ignored in ignored_slugs)


def _parse_boundary(node):
    if not node:
        return None
    if 'dateTime' in node:
        dt = datetime.fromisoformat(node['dateTime'])
        return dt.astimezone() if dt.tzinfo is None else dt
    if 'date' in node:
        return datetime.strptime(node['date'], '%Y-%m-%d').astimezone()
    return None


def _raw_boundary(node):
    return (node.get('dateTime') or node.get('date')) if node else None


def _attendee_names(event, max_attendees):
    names = []
    for attendee in (event.get('attendees') or []):
        if attendee.get('resource'):
            continue
        name = attendee.get('displayName') or attendee.get('email')
        if name:
            names.append(name)
        if len(names) >= max_attendees:
            break
    return names


def _extract_event(event, account, max_attendees):
    return CalendarEvent(
        event_id=event.get('id'),
        title=event.get('summary', '(sem título)'),
        calendar=account,
        start_dt=_parse_boundary(event.get('start', {})),
        end_dt=_parse_boundary(event.get('end', {})),
        start_raw=_raw_boundary(event.get('start', {})),
        end_raw=_raw_boundary(event.get('end', {})),
        attendees=_attendee_names(event, max_attendees),
        attachments=list(event.get('attachments') or []),
    )


def _eligible_events(events, config):
    '''Filter raw API events by decline/ignore status, keeping those with a parseable start.'''
    for event in events:
        title = event.get('summary', '(sem título)')
        if _is_declined(event):
            logger.debug(f'"{title}": dropped (declined)')
            continue
        if _matches_ignore_slug(event, config.ignored_event_slugs):
            logger.debug(f'"{title}": dropped (matches ignored_event_slugs)')
            continue
        if _parse_boundary(event.get('start', {})) is None:
            logger.debug(f'"{title}": dropped (no parseable start)')
            continue
        yield event


# --- Public lookup APIs ------------------------------------------------------

def find_event(anchor, config):
    '''Return the best-matching event closest to `anchor` across all accounts, or None.

    Accepted events are preferred over tentative/unanswered ones; within the winning
    tier the closest by start-time distance wins. Non-fatal: any error (unconfigured,
    auth, network) logs a warning and returns None.'''
    if not config.calendar_enabled:
        return None

    try:
        return _find_event(anchor, config)
    except Exception as e:
        logger.warning(f'Calendar lookup failed: {e}')
        return None


def _find_event(anchor, config):
    if anchor.tzinfo is None:
        anchor = anchor.astimezone()

    time_min = anchor - timedelta(minutes=config.calendar_match_before_minutes)
    time_max = anchor + timedelta(minutes=config.calendar_match_after_minutes)

    candidates = []
    for account in config.calendars:
        try:
            events = _query_events(account, time_min, time_max)
        except Exception as e:
            logger.warning(f'Calendar query failed for account "{account}": {e}')
            continue

        for event in _eligible_events(events, config):
            start = _parse_boundary(event.get('start', {}))
            distance = abs((start - anchor).total_seconds())
            candidates.append((distance, account, event))

    if not candidates:
        return None

    accepted_candidates = [c for c in candidates if _is_accepted(c[2])]
    tier = accepted_candidates if accepted_candidates else candidates

    distance, account, event = min(tier, key=lambda c: c[0])
    return _extract_event(event, account, config.max_attendees)


def upcoming_events(config, within_minutes):
    '''Return non-declined, non-ignored events starting within [now, now + within_minutes].

    Raises on hard failure so the scheduler can surface it; sorted by start time.'''
    now = datetime.now().astimezone()
    time_max = now + timedelta(minutes=within_minutes)
    logger.debug(f'Querying upcoming events between {now} and {time_max} for accounts: {config.calendars}')

    results = []
    for account in config.calendars:
        raw_events = _query_events(account, now, time_max)
        logger.debug(f'Account "{account}": {len(raw_events)} raw event(s) from the API')
        for event in _eligible_events(raw_events, config):
            results.append(_extract_event(event, account, config.max_attendees))

    results.sort(key=lambda e: e.start_dt)
    return results


def past_events(config, lookback_hours):
    '''Return occurrences whose end time is within [now - lookback_hours, now], all accounts.

    Applies the same decline/ignore filtering as elsewhere; a per-account query failure is
    logged and skipped so other accounts still return. Sorted by start time.'''
    now = datetime.now().astimezone()
    time_min = now - timedelta(hours=lookback_hours)
    logger.debug(f'Querying past events between {time_min} and {now} for accounts: {config.calendars}')

    results = []
    for account in config.calendars:
        try:
            raw_events = _query_events(account, time_min, now)
        except Exception as e:
            logger.warning(f'Past-events query failed for account "{account}": {e}')
            continue

        for event in _eligible_events(raw_events, config):
            occurrence = _extract_event(event, account, config.max_attendees)
            if occurrence.end_dt is not None and time_min <= occurrence.end_dt <= now:
                results.append(occurrence)

    results.sort(key=lambda e: e.start_dt)
    return results


# --- Attachment classification / occurrence binding -------------------------

def _parse_transcript_title(title):
    '''Parse `... - YYYY/MM/DD HH:MM GMT±HH:MM - Transcript[ N]` -> (date, index).

    Returns (None, None) when the title is not a transcript title; the date is None (but
    the index still set) when the embedded date cannot be parsed. No regex: split on the
    trailing ` - ` markers and let datetime do the parsing.'''
    left, sep, last = title.rpartition(' - ')
    if not sep or not last.startswith('Transcript'):
        return (None, None)

    suffix = last[len('Transcript'):].strip()
    if suffix == '':
        index = 1
    elif suffix.isdigit():
        index = int(suffix)
    else:
        return (None, None)

    date_part = left.rpartition(' - ')[2].strip().split(' ')[0]
    try:
        title_date = datetime.strptime(date_part, '%Y/%m/%d').date()
    except ValueError:
        title_date = None

    return (title_date, index)


def classify_attachment(att):
    '''Classify a raw attachment dict.

    Transcripts are identified by their Google-generated title structure
    (`... - YYYY/MM/DD HH:MM GMT±HH:MM - Transcript[ N]`), not by the undocumented
    `usp=` URL marker. Gemini notes carry no such structure, so they stay keyed on the
    `usp=meet_tnfm_calendar` marker; an unrecognised `meet_*` marker is logged as a
    warning (a signal Google renamed it and this needs updating).

    Returns ('transcript', doc_id, title_date) / ('gemini', doc_id, None) / None.'''
    file_url = att.get('fileUrl') or ''
    title = att.get('title') or ''
    doc_id = drive.doc_id_from_url(file_url) or att.get('fileId')
    if not doc_id:
        return None

    title_date, index = _parse_transcript_title(title)
    if index is not None:
        return ('transcript', doc_id, title_date)

    if 'usp=meet_tnfm_calendar' in file_url:
        return ('gemini', doc_id, None)

    if 'usp=meet_' in file_url:
        logger.warning(
            f'{title!r}: unrecognised Meet attachment marker in {file_url!r}; '
            'Gemini-notes classification may need updating'
        )

    return None


def attachments_for_occurrence(event):
    '''Resolve the transcript + Gemini doc ids that belong to this occurrence.

    Transcript docs are bound only when their title date matches the occurrence start
    date (guarding against recurring events accumulating historical transcripts), merged
    in trailing-index order. The single Gemini notes doc is included when exactly one is
    present; more than one is skipped with a warning (they carry no date to disambiguate).'''
    occurrence_date = event.start_dt.date() if event.start_dt else None

    transcripts = []
    gemini_ids = []
    for att in (event.attachments or []):
        classified = classify_attachment(att)
        if classified is None:
            logger.debug(f'"{event.title}": ignoring unclassified attachment {att.get("title")!r}')
            continue

        kind, doc_id, title_date = classified
        if kind == 'transcript':
            if occurrence_date is not None and title_date == occurrence_date:
                _, index = _parse_transcript_title(att.get('title') or '')
                transcripts.append((index or 1, doc_id))
        elif kind == 'gemini':
            gemini_ids.append(doc_id)

    transcripts.sort(key=lambda t: t[0])
    transcript_ids = [doc_id for _, doc_id in transcripts]

    gemini_id = None
    if len(gemini_ids) == 1:
        gemini_id = gemini_ids[0]
    elif len(gemini_ids) > 1:
        logger.warning(
            f'"{event.title}": {len(gemini_ids)} Gemini notes attachments; '
            'skipping notes (cannot disambiguate without a date)'
        )

    return OccurrenceAttachments(transcript_ids, gemini_id)
