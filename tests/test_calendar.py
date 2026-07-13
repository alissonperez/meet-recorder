import json
import os
import stat
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from meet_recorder import calendar
from meet_recorder.calendar import CalendarError

UTC = timezone.utc


def _config(**overrides):
    base = dict(
        calendars=['personal'],
        calendar_match_before_minutes=60,
        calendar_match_after_minutes=15,
        ignored_event_slugs=[],
        max_attendees=20,
        calendar_enabled=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _event(summary, start, end=None, attendees=None, event_id='e1'):
    node = {
        'id': event_id,
        'summary': summary,
        'start': {'dateTime': start.isoformat()},
        'end': {'dateTime': (end or start).isoformat()},
    }
    if attendees is not None:
        node['attendees'] = attendees
    return node


# --- filters -----------------------------------------------------------------

def test_is_declined_true_only_for_self_declined():
    declined = {'attendees': [{'self': True, 'responseStatus': 'declined'}]}
    accepted = {'attendees': [{'self': True, 'responseStatus': 'accepted'}]}
    other_declined = {'attendees': [{'self': False, 'responseStatus': 'declined'}]}

    assert calendar._is_declined(declined) is True
    assert calendar._is_declined(accepted) is False
    assert calendar._is_declined(other_declined) is False
    assert calendar._is_declined({}) is False


def test_matches_ignore_slug():
    event = {'summary': 'Team Lunch Break'}

    assert calendar._matches_ignore_slug(event, ['lunch']) is True
    assert calendar._matches_ignore_slug(event, ['standup']) is False
    assert calendar._matches_ignore_slug(event, []) is False


def test_parse_boundary_datetime_and_date():
    dt = calendar._parse_boundary({'dateTime': '2024-03-15T10:30:00+00:00'})
    assert dt == datetime(2024, 3, 15, 10, 30, tzinfo=UTC)

    all_day = calendar._parse_boundary({'date': '2024-03-15'})
    assert all_day.tzinfo is not None
    assert calendar._parse_boundary({}) is None


def test_parse_boundary_handles_none_node():
    assert calendar._parse_boundary(None) is None


def test_parse_boundary_makes_naive_datetime_aware():
    dt = calendar._parse_boundary({'dateTime': '2024-03-15T10:30:00'})

    assert dt is not None
    assert dt.tzinfo is not None


def test_raw_boundary_handles_none_node():
    assert calendar._raw_boundary(None) is None
    assert calendar._raw_boundary({'dateTime': '2024-03-15T10:30:00+00:00'}) == '2024-03-15T10:30:00+00:00'


def test_filters_handle_none_attendees():
    event = {'attendees': None, 'summary': 'Sync'}

    assert calendar._is_declined(event) is False
    assert calendar._attendee_names(event, max_attendees=20) == []


def test_attendee_names_prefers_display_name_and_caps():
    event = {
        'attendees': [
            {'displayName': 'Alice'},
            {'email': 'bob@example.com'},
            {'resource': True, 'displayName': 'Room A'},
            {'displayName': 'Carol'},
        ]
    }

    assert calendar._attendee_names(event, max_attendees=20) == ['Alice', 'bob@example.com', 'Carol']
    assert calendar._attendee_names(event, max_attendees=1) == ['Alice']


def test_extract_event_captures_fields():
    start = datetime(2024, 3, 15, 10, 0, tzinfo=UTC)
    end = datetime(2024, 3, 15, 11, 0, tzinfo=UTC)
    raw = _event('Sync', start, end, attendees=[{'displayName': 'Alice'}], event_id='abc')

    result = calendar._extract_event(raw, 'personal', max_attendees=20)

    assert result.id == 'abc'
    assert result.title == 'Sync'
    assert result.calendar == 'personal'
    assert result.start_dt == start
    assert result.end_dt == end
    assert result.start_raw == start.isoformat()
    assert result.attendees == ['Alice']


# --- find_event --------------------------------------------------------------

def test_find_event_returns_none_when_unconfigured():
    assert calendar.find_event(datetime.now(UTC), _config(calendar_enabled=False)) is None


def test_find_event_picks_closest_across_accounts(monkeypatch):
    anchor = datetime(2024, 3, 15, 10, 0, tzinfo=UTC)

    near = _event('Near', anchor + timedelta(minutes=2), event_id='near')
    far = _event('Far', anchor - timedelta(minutes=40), event_id='far')

    def fake_query(account, time_min, time_max):
        return {'personal': [far], 'work': [near]}[account]

    monkeypatch.setattr(calendar, '_query_events', fake_query)

    result = calendar.find_event(anchor, _config(calendars=['personal', 'work']))

    assert result.id == 'near'
    assert result.calendar == 'work'


def test_find_event_excludes_declined_and_ignored(monkeypatch):
    anchor = datetime(2024, 3, 15, 10, 0, tzinfo=UTC)

    declined = _event('Sync', anchor, attendees=[{'self': True, 'responseStatus': 'declined'}], event_id='d')
    ignored = _event('Daily Lunch', anchor + timedelta(minutes=1), event_id='i')
    good = _event('Planning', anchor + timedelta(minutes=5), event_id='g')

    monkeypatch.setattr(calendar, '_query_events', lambda a, mn, mx: [declined, ignored, good])

    result = calendar.find_event(anchor, _config(ignored_event_slugs=['lunch']))

    assert result.id == 'g'


def test_find_event_late_start_still_matches(monkeypatch):
    event_start = datetime(2024, 3, 15, 10, 0, tzinfo=UTC)
    anchor = event_start + timedelta(minutes=25)  # started recording 25 min late

    monkeypatch.setattr(calendar, '_query_events', lambda a, mn, mx: [_event('Sync', event_start)])

    result = calendar.find_event(anchor, _config())

    assert result is not None
    assert result.title == 'Sync'


def test_find_event_returns_none_on_error(monkeypatch):
    def boom(account, mn, mx):
        raise RuntimeError('network down')

    monkeypatch.setattr(calendar, '_query_events', boom)

    # per-account failure is swallowed -> no candidates -> None
    assert calendar.find_event(datetime.now(UTC), _config()) is None


def test_find_event_none_when_no_candidates(monkeypatch):
    monkeypatch.setattr(calendar, '_query_events', lambda a, mn, mx: [])
    assert calendar.find_event(datetime.now(UTC), _config()) is None


def test_is_accepted_true_only_for_self_accepted():
    accepted = {'attendees': [{'self': True, 'responseStatus': 'accepted'}]}
    tentative = {'attendees': [{'self': True, 'responseStatus': 'tentative'}]}
    no_response = {'attendees': [{'self': True, 'responseStatus': 'needsAction'}]}
    other_accepted = {'attendees': [{'self': False, 'responseStatus': 'accepted'}]}

    assert calendar._is_accepted(accepted) is True
    assert calendar._is_accepted(tentative) is False
    assert calendar._is_accepted(no_response) is False
    assert calendar._is_accepted(other_accepted) is False
    assert calendar._is_accepted({}) is False


def test_find_event_prefers_accepted_over_closer_tentative(monkeypatch):
    anchor = datetime(2024, 3, 15, 10, 0, tzinfo=UTC)

    tentative = _event(
        'Maybe Sync', anchor + timedelta(minutes=1),
        attendees=[{'self': True, 'responseStatus': 'tentative'}], event_id='tentative',
    )
    accepted = _event(
        'Yes Sync', anchor + timedelta(minutes=10),
        attendees=[{'self': True, 'responseStatus': 'accepted'}], event_id='accepted',
    )

    monkeypatch.setattr(calendar, '_query_events', lambda a, mn, mx: [tentative, accepted])

    result = calendar.find_event(anchor, _config())

    assert result.id == 'accepted'


def test_find_event_falls_back_to_tentative_when_no_accepted_qualifies(monkeypatch):
    anchor = datetime(2024, 3, 15, 10, 0, tzinfo=UTC)

    tentative_near = _event(
        'Maybe Near', anchor + timedelta(minutes=1),
        attendees=[{'self': True, 'responseStatus': 'tentative'}], event_id='near',
    )
    tentative_far = _event(
        'Maybe Far', anchor + timedelta(minutes=10),
        attendees=[{'self': True, 'responseStatus': 'tentative'}], event_id='far',
    )

    monkeypatch.setattr(calendar, '_query_events', lambda a, mn, mx: [tentative_near, tentative_far])

    result = calendar.find_event(anchor, _config())

    assert result.id == 'near'


def test_find_event_still_excludes_declined_and_ignored_across_tiers(monkeypatch):
    anchor = datetime(2024, 3, 15, 10, 0, tzinfo=UTC)

    declined = _event(
        'Declined', anchor,
        attendees=[{'self': True, 'responseStatus': 'declined'}], event_id='declined',
    )
    ignored = _event(
        'Daily Lunch', anchor + timedelta(minutes=1),
        attendees=[{'self': True, 'responseStatus': 'accepted'}], event_id='ignored',
    )
    tentative = _event(
        'Maybe Planning', anchor + timedelta(minutes=5),
        attendees=[{'self': True, 'responseStatus': 'tentative'}], event_id='good',
    )

    monkeypatch.setattr(calendar, '_query_events', lambda a, mn, mx: [declined, ignored, tentative])

    result = calendar.find_event(anchor, _config(ignored_event_slugs=['lunch']))

    assert result.id == 'good'


# --- upcoming_events ---------------------------------------------------------

def test_upcoming_events_filters_and_sorts(monkeypatch):
    now = datetime.now(UTC)
    later = _event('Later', now + timedelta(minutes=8), event_id='l')
    sooner = _event('Sooner', now + timedelta(minutes=2), event_id='s')
    declined = _event('Skip', now + timedelta(minutes=3),
                      attendees=[{'self': True, 'responseStatus': 'declined'}], event_id='x')

    monkeypatch.setattr(calendar, '_query_events', lambda a, mn, mx: [later, sooner, declined])

    events = calendar.upcoming_events(_config(), within_minutes=10)

    assert [e.id for e in events] == ['s', 'l']


def test_upcoming_events_propagates_errors(monkeypatch):
    monkeypatch.setattr(calendar, '_query_events', Mock(side_effect=RuntimeError('boom')))

    with pytest.raises(RuntimeError):
        calendar.upcoming_events(_config(), within_minutes=10)


# --- credentials -------------------------------------------------------------

def test_build_credentials_missing_token_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(calendar.config_module, 'token_path', lambda a: str(tmp_path / 'missing.json'))

    with pytest.raises(CalendarError, match='Token file not found'):
        calendar.build_credentials('personal')


def test_build_credentials_malformed_token_raises(monkeypatch, tmp_path):
    token_file = tmp_path / 'personal.json'
    token_file.write_text('{ not valid json')
    monkeypatch.setattr(calendar.config_module, 'token_path', lambda a: str(token_file))

    with pytest.raises(CalendarError, match='invalid'):
        calendar.build_credentials('personal')


def test_write_token_uses_owner_only_permissions(monkeypatch, tmp_path):
    token_file = tmp_path / 'tokens' / 'personal.json'
    monkeypatch.setattr(calendar.config_module, 'token_path', lambda a: str(token_file))

    creds = Mock()
    creds.to_json = Mock(return_value=json.dumps({'token': 'abc'}))

    calendar._write_token('personal', creds)

    assert os.path.isfile(token_file)
    mode = stat.S_IMODE(os.stat(token_file).st_mode)
    assert mode == 0o600
    assert json.loads(token_file.read_text()) == {'token': 'abc'}
