from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from meet_recorder import menubar as menubar_module
from meet_recorder.calendar import CalendarEvent


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(menubar_module.MenubarApp, '_load_config_safe', lambda self: None)
    monkeypatch.setattr(menubar_module.MenubarApp, '_build_autorecord_timer', lambda self: None)
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
