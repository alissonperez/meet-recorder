from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from meet_recorder import menubar as menubar_module
from meet_recorder.calendar import CalendarEvent


class _StubAutorecordConfig:
    def __init__(self, **kwargs):
        self.enabled = True
        self.calendar_poll_interval_minutes = 5
        self.notify_before_minutes = 5
        self.check_interval_seconds = 60
        self.max_meeting_age_minutes = 20
        for key, value in kwargs.items():
            setattr(self, key, value)


class _StubConfig:
    def __init__(self, **autorecord_kwargs):
        self.autorecord = _StubAutorecordConfig(**autorecord_kwargs)
        self.calendars = ['personal']

    @property
    def calendar_enabled(self):
        return bool(self.calendars)


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(menubar_module.MenubarApp, '_load_config_safe', lambda self: _StubConfig(enabled=False))
    monkeypatch.setattr(menubar_module.MenubarApp, '_build_calendar_poll_timer', lambda self: None)
    monkeypatch.setattr(
        menubar_module.rumps.Timer, '__init__', lambda self, *a, **k: None,
    )

    instance = menubar_module.MenubarApp()
    instance._show_alert = MagicMock()
    instance._notify = MagicMock()
    return instance


@pytest.fixture
def app_with_calendar(monkeypatch):
    monkeypatch.setattr(menubar_module.MenubarApp, '_load_config_safe', lambda self: _StubConfig())
    monkeypatch.setattr(
        menubar_module.rumps.Timer, '__init__', lambda self, *a, **k: None,
    )

    instance = menubar_module.MenubarApp()
    instance._show_alert = MagicMock()
    instance._notify = MagicMock()
    return instance


def _event(event_id='evt-1', title='Standup', minutes_from_now=0):
    start = datetime.now().astimezone() + timedelta(minutes=minutes_from_now)
    return CalendarEvent(
        event_id=event_id, title=title, calendar='personal',
        start_dt=start, end_dt=start + timedelta(minutes=30),
        start_raw=start.isoformat(), end_raw=None, attendees=[],
    )


def test_prompt_start_shows_modal_and_starts_recording_on_confirm(app, monkeypatch):
    event = _event(minutes_from_now=-1)
    app._show_alert.return_value = 1
    start_recording = MagicMock()
    monkeypatch.setattr(menubar_module.recorder, 'start_recording', start_recording)

    app._maybe_prompt_start(event, datetime.now().astimezone())

    app._show_alert.assert_called_once()
    kwargs = app._show_alert.call_args.kwargs
    assert event.title in kwargs['message']
    assert kwargs['ok'] == 'Iniciar gravação'
    start_recording.assert_called_once()
    assert app.is_recording is True


def test_prompt_start_does_not_record_when_dismissed(app, monkeypatch):
    event = _event(minutes_from_now=-1)
    app._show_alert.return_value = 0
    start_recording = MagicMock()
    monkeypatch.setattr(menubar_module.recorder, 'start_recording', start_recording)

    app._maybe_prompt_start(event, datetime.now().astimezone())

    start_recording.assert_not_called()
    assert app.is_recording is False


def test_prompt_start_skips_future_events(app):
    event = _event(minutes_from_now=5)

    app._maybe_prompt_start(event, datetime.now().astimezone())

    app._show_alert.assert_not_called()


def test_prompt_start_only_fires_once_per_event(app, monkeypatch):
    event = _event(minutes_from_now=-1)
    app._show_alert.return_value = 0
    now = datetime.now().astimezone()

    app._maybe_prompt_start(event, now)
    app._maybe_prompt_start(event, now)

    app._show_alert.assert_called_once()


def test_prompt_start_skips_modal_when_already_recording(app):
    app.is_recording = True
    event = _event(minutes_from_now=-1)

    app._maybe_prompt_start(event, datetime.now().astimezone())

    app._show_alert.assert_not_called()


def test_prompt_start_failed_recording_does_not_set_recording_state(app, monkeypatch):
    event = _event(minutes_from_now=-1)
    app._show_alert.return_value = 1
    monkeypatch.setattr(
        menubar_module.recorder, 'start_recording',
        MagicMock(side_effect=RuntimeError('boom')),
    )
    monkeypatch.setattr(menubar_module.rumps, 'alert', MagicMock())

    app._maybe_prompt_start(event, datetime.now().astimezone())

    assert app.is_recording is False


def test_prompt_start_skips_when_older_than_max_age(app):
    app.config.autorecord.max_meeting_age_minutes = 20
    event = _event(minutes_from_now=-30)

    app._maybe_prompt_start(event, datetime.now().astimezone())

    app._show_alert.assert_not_called()
    assert event.id not in app._prompted_events


def test_prompt_start_shows_when_within_max_age(app):
    app.config.autorecord.max_meeting_age_minutes = 20
    app._show_alert.return_value = 0
    event = _event(minutes_from_now=-10)

    app._maybe_prompt_start(event, datetime.now().astimezone())

    app._show_alert.assert_called_once()
    assert event.id in app._prompted_events


def test_run_calendar_poll_only_fetches_and_does_not_notify_or_prompt(app_with_calendar, monkeypatch):
    events = [_event(minutes_from_now=-1)]
    monkeypatch.setattr(menubar_module.calendar, 'upcoming_events', MagicMock(return_value=events))
    app_with_calendar._maybe_notify_upcoming = MagicMock()
    app_with_calendar._maybe_prompt_start = MagicMock()

    app_with_calendar._run_calendar_poll(sender=None)

    assert app_with_calendar._cached_events == events
    app_with_calendar._maybe_notify_upcoming.assert_not_called()
    app_with_calendar._maybe_prompt_start.assert_not_called()


def test_run_meeting_check_evaluates_cached_events_without_polling(app_with_calendar, monkeypatch):
    events = [_event(event_id='evt-1', minutes_from_now=-1), _event(event_id='evt-2', minutes_from_now=-2)]
    app_with_calendar._cached_events = events
    upcoming_events = MagicMock()
    monkeypatch.setattr(menubar_module.calendar, 'upcoming_events', upcoming_events)
    app_with_calendar._maybe_notify_upcoming = MagicMock()
    app_with_calendar._maybe_prompt_start = MagicMock()

    app_with_calendar._run_meeting_check(sender=None)

    upcoming_events.assert_not_called()
    assert app_with_calendar._maybe_notify_upcoming.call_count == 2
    assert app_with_calendar._maybe_prompt_start.call_count == 2


def test_calendar_poll_kickoff_seeds_cache_and_runs_immediate_check(app_with_calendar, monkeypatch):
    event = _event(minutes_from_now=-5)
    monkeypatch.setattr(menubar_module.calendar, 'upcoming_events', MagicMock(return_value=[event]))
    app_with_calendar._show_alert.return_value = 0
    sender = MagicMock()

    app_with_calendar._run_calendar_poll_kickoff(sender)

    sender.stop.assert_called_once()
    assert app_with_calendar._cached_events == [event]
    app_with_calendar._show_alert.assert_called_once()
    assert event.id in app_with_calendar._prompted_events
