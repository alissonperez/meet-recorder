import threading
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
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
        self.prompt_delay_seconds = 0
        for key, value in kwargs.items():
            setattr(self, key, value)


class _StubMeetTranscriptsConfig:
    def __init__(self, **kwargs):
        self.enabled = False
        self.poll_interval_minutes = 15
        self.lookback_hours = 12
        self.max_access_retries = 3
        for key, value in kwargs.items():
            setattr(self, key, value)


class _StubConfig:
    def __init__(self, meet_transcripts=None, calendars=('personal',), **autorecord_kwargs):
        self.autorecord = _StubAutorecordConfig(**autorecord_kwargs)
        self.calendars = list(calendars)
        self.meet_transcripts = meet_transcripts or _StubMeetTranscriptsConfig()

    @property
    def calendar_enabled(self):
        return bool(self.calendars)


class _SyncThread:
    '''Stand-in for threading.Thread that runs its target immediately on .start(), so tests
    exercising the background-start path stay synchronous and deterministic.'''

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._target = target
        self._args = args
        self._kwargs = kwargs or {}

    def start(self):
        self._target(*self._args, **self._kwargs)

    def join(self, timeout=None):
        pass


class _SyncThreadingModule:
    '''Stands in for the `threading` module reference inside menubar_module: every other
    attribute (Lock, Event, Timer, ...) delegates to the real threading module, but Thread
    is replaced so patching it doesn't mutate the real threading.Thread class used elsewhere
    (e.g. by real background threads spawned in other tests).'''
    Thread = _SyncThread

    def __getattr__(self, name):
        return getattr(threading, name)


def _run_start_synchronously(monkeypatch):
    # start_recording() is dispatched to a background thread with the result marshaled back
    # via AppHelper.callAfter; run both inline so assertions can observe the result immediately.
    monkeypatch.setattr(menubar_module, 'threading', _SyncThreadingModule())
    monkeypatch.setattr(menubar_module.AppHelper, 'callAfter', lambda func, *a, **k: func(*a, **k))


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(menubar_module.MenubarApp, '_load_config_safe', lambda self: _StubConfig(enabled=False))
    monkeypatch.setattr(menubar_module.MenubarApp, '_build_calendar_poll_timer', lambda self: None)
    monkeypatch.setattr(
        menubar_module.rumps.Timer, '__init__', lambda self, *a, **k: None,
    )
    _run_start_synchronously(monkeypatch)

    instance = menubar_module.MenubarApp()
    instance._show_alert = MagicMock()
    instance._notify = MagicMock()
    instance._blink_timer = MagicMock()
    return instance


@pytest.fixture
def app_with_calendar(monkeypatch):
    monkeypatch.setattr(menubar_module.MenubarApp, '_load_config_safe', lambda self: _StubConfig())
    monkeypatch.setattr(
        menubar_module.rumps.Timer, '__init__', lambda self, *a, **k: None,
    )
    _run_start_synchronously(monkeypatch)

    instance = menubar_module.MenubarApp()
    instance._show_alert = MagicMock()
    instance._notify = MagicMock()
    return instance


def _event(event_id='evt-1', title='Standup', minutes_from_now=0, seconds_from_now=None):
    delta = timedelta(seconds=seconds_from_now) if seconds_from_now is not None else timedelta(minutes=minutes_from_now)
    start = datetime.now().astimezone() + delta
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


def test_prompt_start_skips_before_prompt_delay_elapses(app):
    app.config.autorecord.prompt_delay_seconds = 60
    event = _event(seconds_from_now=-10)

    app._maybe_prompt_start(event, datetime.now().astimezone())

    app._show_alert.assert_not_called()
    assert event.id not in app._prompted_events


def test_prompt_start_shows_after_prompt_delay_elapses(app):
    app.config.autorecord.prompt_delay_seconds = 60
    app._show_alert.return_value = 0
    event = _event(seconds_from_now=-90)

    app._maybe_prompt_start(event, datetime.now().astimezone())

    app._show_alert.assert_called_once()
    assert event.id in app._prompted_events


def test_prompt_start_shows_immediately_when_prompt_delay_is_default(app):
    assert app.config.autorecord.prompt_delay_seconds == 0
    app._show_alert.return_value = 0
    event = _event(seconds_from_now=-1)

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


# --- Meet-transcript ingestion poller ---------------------------------------

@pytest.fixture
def meet_app(monkeypatch):
    config = _StubConfig(
        meet_transcripts=_StubMeetTranscriptsConfig(enabled=True), enabled=False,
    )
    monkeypatch.setattr(menubar_module.MenubarApp, '_load_config_safe', lambda self: config)
    monkeypatch.setattr(menubar_module.rumps.Timer, '__init__', lambda self, *a, **k: None)
    # The Meet-ingest alerts marshal to the main thread via AppHelper.callAfter; run it
    # synchronously so assertions on _show_alert still observe the call.
    monkeypatch.setattr(menubar_module.AppHelper, 'callAfter', lambda func, *a, **k: func(*a, **k))

    instance = menubar_module.MenubarApp()
    instance._show_alert = MagicMock()
    instance._notify = MagicMock()
    return instance


def test_meet_poller_active_when_enabled_and_calendars_configured(meet_app):
    assert meet_app._meet_transcripts_active() is True
    assert meet_app._meet_poll_timer is not None


def test_meet_poller_disabled_when_feature_off(app):
    # `app` fixture uses a config with meet_transcripts disabled.
    assert app._meet_transcripts_active() is False
    assert app._meet_poll_timer is None


def test_meet_poller_disabled_when_no_calendars(monkeypatch):
    config = _StubConfig(
        meet_transcripts=_StubMeetTranscriptsConfig(enabled=True), calendars=(), enabled=False,
    )
    monkeypatch.setattr(menubar_module.MenubarApp, '_load_config_safe', lambda self: config)
    monkeypatch.setattr(menubar_module.rumps.Timer, '__init__', lambda self, *a, **k: None)

    instance = menubar_module.MenubarApp()

    assert instance._meet_transcripts_active() is False
    assert instance._meet_poll_timer is None


def test_ingest_in_background_wraps_counter(meet_app, monkeypatch):
    seen = {}

    def fake_ingest(config, on_access_error=None):
        seen['active_during'] = meet_app.active_transcriptions
        return [{'transcript_path': 't.md', 'summary_path': 's.md'}]

    monkeypatch.setattr(menubar_module.meet_ingest, 'ingest_once', fake_ingest)

    meet_app._ingest_in_background()

    assert seen['active_during'] == 1
    assert meet_app.active_transcriptions == 0


def test_ingest_in_background_decrements_counter_on_failure(meet_app, monkeypatch):
    monkeypatch.setattr(
        menubar_module.meet_ingest, 'ingest_once',
        MagicMock(side_effect=RuntimeError('boom')),
    )

    meet_app._ingest_in_background()

    assert meet_app.active_transcriptions == 0


def test_access_error_callback_shows_modal(meet_app):
    event = _event(title='Weekly Sync')

    meet_app._on_meet_access_error(event)

    meet_app._show_alert.assert_called_once()
    assert 'Weekly Sync' in meet_app._show_alert.call_args.kwargs['message']


def test_ingest_access_error_callback_invoked_once_per_event(meet_app, monkeypatch):
    event = _event(title='Weekly Sync')

    def fake_ingest(config, on_access_error=None):
        on_access_error(event)
        return []

    monkeypatch.setattr(menubar_module.meet_ingest, 'ingest_once', fake_ingest)

    meet_app._ingest_in_background()

    meet_app._show_alert.assert_called_once()


def test_scope_error_shows_reauth_alert(meet_app, monkeypatch):
    monkeypatch.setattr(
        menubar_module.meet_ingest, 'ingest_once',
        MagicMock(side_effect=menubar_module.drive.DriveScopeError('re-run calendar_auth')),
    )

    meet_app._ingest_in_background()

    meet_app._show_alert.assert_called_once()
    assert 're-run calendar_auth' in meet_app._show_alert.call_args.kwargs['message']


def test_access_error_alert_marshaled_to_main_thread(meet_app, monkeypatch):
    call_after = MagicMock()
    monkeypatch.setattr(menubar_module.AppHelper, 'callAfter', call_after)

    meet_app._on_meet_access_error(_event(title='Weekly Sync'))

    # The alert must be dispatched via AppHelper.callAfter (main thread), not called inline.
    meet_app._show_alert.assert_not_called()
    call_after.assert_called_once()
    assert call_after.call_args.args[0] == meet_app._show_alert


def test_scope_error_alert_marshaled_to_main_thread(meet_app, monkeypatch):
    call_after = MagicMock()
    monkeypatch.setattr(menubar_module.AppHelper, 'callAfter', call_after)
    monkeypatch.setattr(
        menubar_module.meet_ingest, 'ingest_once',
        MagicMock(side_effect=menubar_module.drive.DriveScopeError('re-run calendar_auth')),
    )

    meet_app._ingest_in_background()

    meet_app._show_alert.assert_not_called()
    call_after.assert_called_once()
    assert call_after.call_args.args[0] == meet_app._show_alert


def test_active_transcriptions_counter_balances_under_concurrency(meet_app):
    import threading

    def churn():
        for _ in range(200):
            meet_app._begin_transcription()
            meet_app._end_transcription()

    threads = [threading.Thread(target=churn) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert meet_app.active_transcriptions == 0


def test_meet_poll_failure_notifies_on_threshold(meet_app):
    for _ in range(menubar_module.MEET_INGEST_FAILURE_NOTIFY_THRESHOLD - 1):
        meet_app._on_meet_poll_failure(RuntimeError('x'))
    meet_app._notify.assert_not_called()

    meet_app._on_meet_poll_failure(RuntimeError('x'))
    meet_app._notify.assert_called_once()


# --- Folder-transcript ingestion poller ---------------------------------------


def _folder_app(monkeypatch, enabled=True, directories=('/inbox',)):
    config = _StubConfig(enabled=False)
    config.folder_ingest = SimpleNamespace(
        enabled=enabled, directories=list(directories), poll_interval_minutes=5, max_attempts=3,
    )
    monkeypatch.setattr(menubar_module.MenubarApp, '_load_config_safe', lambda self: config)
    monkeypatch.setattr(menubar_module.rumps.Timer, '__init__', lambda self, *a, **k: None)

    instance = menubar_module.MenubarApp()
    instance._notify = MagicMock()
    return instance


def test_folder_poller_active_when_enabled_with_directories(monkeypatch):
    instance = _folder_app(monkeypatch)

    assert instance._folder_ingest_active() is True
    assert instance._folder_poll_timer is not None


def test_folder_poller_disabled_when_feature_off(monkeypatch):
    instance = _folder_app(monkeypatch, enabled=False)

    assert instance._folder_ingest_active() is False
    assert instance._folder_poll_timer is None


def test_folder_poller_disabled_without_directories(monkeypatch):
    instance = _folder_app(monkeypatch, directories=())

    assert instance._folder_ingest_active() is False
    assert instance._folder_poll_timer is None


def test_folder_poller_disabled_when_section_absent(app):
    # `app` fixture's stub config has no folder_ingest attribute at all.
    assert app._folder_ingest_active() is False
    assert app._folder_poll_timer is None


def test_folder_poll_kickoff_stops_itself_and_runs_a_poll(monkeypatch):
    instance = _folder_app(monkeypatch)
    instance._run_folder_poll = MagicMock()
    sender = MagicMock()

    instance._run_folder_poll_kickoff(sender)

    sender.stop.assert_called_once()
    instance._run_folder_poll.assert_called_once_with(sender)


def test_folder_ingest_in_background_wraps_counter(monkeypatch):
    instance = _folder_app(monkeypatch)
    seen = {}

    def fake_ingest(config, on_failure=None):
        seen['active_during'] = instance.active_transcriptions
        return [{'transcript_path': 't.md', 'summary_path': 's.md'}]

    monkeypatch.setattr(menubar_module.folder_ingest, 'ingest_once', fake_ingest)

    instance._folder_ingest_in_background()

    assert seen['active_during'] == 1
    assert instance.active_transcriptions == 0


def test_folder_ingest_in_background_decrements_counter_on_failure(monkeypatch):
    instance = _folder_app(monkeypatch)
    monkeypatch.setattr(
        menubar_module.folder_ingest, 'ingest_once', MagicMock(side_effect=RuntimeError('boom')),
    )

    instance._folder_ingest_in_background()

    assert instance.active_transcriptions == 0
    assert instance._folder_poll_failures == 1


def test_folder_poll_failure_notifies_on_threshold_and_resets_on_success(monkeypatch):
    instance = _folder_app(monkeypatch)
    ingest = MagicMock(side_effect=RuntimeError('x'))
    monkeypatch.setattr(menubar_module.folder_ingest, 'ingest_once', ingest)

    for _ in range(menubar_module.FOLDER_INGEST_FAILURE_NOTIFY_THRESHOLD - 1):
        instance._folder_ingest_in_background()
    instance._notify.assert_not_called()

    instance._folder_ingest_in_background()
    instance._notify.assert_called_once()

    ingest.side_effect = None
    ingest.return_value = []
    instance._folder_ingest_in_background()
    assert instance._folder_poll_failures == 0


def test_folder_file_abandoned_callback_notifies(monkeypatch):
    instance = _folder_app(monkeypatch)

    def fake_ingest(config, on_failure=None):
        on_failure('/inbox/notes.txt', RuntimeError('llm down'))
        return []

    monkeypatch.setattr(menubar_module.folder_ingest, 'ingest_once', fake_ingest)

    instance._folder_ingest_in_background()

    instance._notify.assert_called_once()
    assert 'notes.txt' in instance._notify.call_args.args[1]


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


def test_discard_item_enabled_only_while_recording(app):
    assert app.discard_item.callback is None

    app._set_recording_state(True)
    assert app.discard_item.callback == app.on_discard

    app._set_recording_state(False)
    assert app.discard_item.callback is None


def test_on_discard_confirms_discards_and_resets_state(app, monkeypatch):
    app._set_recording_state(True)
    app._show_alert.return_value = 1
    discard_recording = MagicMock()
    monkeypatch.setattr(menubar_module.recorder, 'discard_recording', discard_recording)

    app.on_discard(None)

    discard_recording.assert_called_once()
    assert app.is_recording is False
    assert app.discard_item.callback is None
    assert app.stop_item.callback is None
    assert app.stop_no_transcribe_item.callback is None
    assert app.start_item.callback == app.on_start


def test_on_start_runs_recording_in_background_without_blocking(app, monkeypatch):
    # Use a real thread here (rather than the fixture's synchronous stub) to prove the menu
    # bar stays responsive while start_recording() is still pending.
    monkeypatch.setattr(menubar_module, 'threading', threading)
    monkeypatch.setattr(menubar_module.AppHelper, 'callAfter', lambda func, *a, **k: func(*a, **k))
    started = threading.Event()
    release = threading.Event()

    def slow_start_recording():
        started.set()
        release.wait(timeout=5)

    monkeypatch.setattr(menubar_module.recorder, 'start_recording', slow_start_recording)

    app.on_start(None)
    assert started.wait(timeout=5) is True

    # While the background start is still pending, other menu actions remain callable
    # (menu state hasn't flipped to "recording" yet, but nothing is frozen/blocked).
    assert app.start_item.callback is None
    assert app._start_in_progress is True
    app.on_discard(None)  # must return immediately rather than blocking on the pending start
    app._show_alert.assert_called_once()

    release.set()
    for _ in range(500):
        if not app._start_in_progress:
            break
        time.sleep(0.01)

    assert app.is_recording is True
    assert app.start_item.callback is None
    assert app.stop_item.callback == app.on_stop


def test_on_start_second_click_while_in_flight_is_noop(app, monkeypatch):
    start_recording = MagicMock()
    monkeypatch.setattr(menubar_module.recorder, 'start_recording', start_recording)
    app._start_in_progress = True
    app.start_item.set_callback(None)

    app.on_start(None)

    start_recording.assert_not_called()


def test_on_start_failure_shows_alert_and_reenables_start(app, monkeypatch):
    start_recording = MagicMock(side_effect=RuntimeError('no mic'))
    monkeypatch.setattr(menubar_module.recorder, 'start_recording', start_recording)
    alert = MagicMock()
    monkeypatch.setattr(menubar_module.rumps, 'alert', alert)

    app.on_start(None)

    alert.assert_called_once_with(title='Failed to start recording', message='no mic')
    assert app._start_in_progress is False
    assert app.start_item.callback == app.on_start


def test_on_start_success_enables_stop_items(app, monkeypatch):
    monkeypatch.setattr(menubar_module.recorder, 'start_recording', MagicMock())

    app.on_start(None)

    assert app._start_in_progress is False
    assert app.is_recording is True
    assert app.start_item.callback is None
    assert app.stop_item.callback == app.on_stop
    assert app.stop_no_transcribe_item.callback == app.on_stop_no_transcribe
    assert app.discard_item.callback == app.on_discard


def test_on_discard_cancel_leaves_recording_running(app, monkeypatch):
    app._set_recording_state(True)
    app._show_alert.return_value = 0
    discard_recording = MagicMock()
    monkeypatch.setattr(menubar_module.recorder, 'discard_recording', discard_recording)

    app.on_discard(None)

    discard_recording.assert_not_called()
    assert app.is_recording is True
    assert app.discard_item.callback == app.on_discard


# --- Deferred transcription retry -------------------------------------------

@pytest.fixture
def retry(monkeypatch, tmp_path):
    '''Stub the transcription pipeline and layer-2 helper; track what each call did.'''
    monkeypatch.setattr(menubar_module.asyncio, 'run', MagicMock())
    monkeypatch.setattr(menubar_module.transcriber, 'transcribe', lambda path: None)

    deferred = MagicMock(return_value=menubar_module.transcription_retry.ledger.LedgerEntry('deferred', 1))
    monkeypatch.setattr(menubar_module.transcription_retry, 'defer', deferred)
    marked_done = MagicMock()
    monkeypatch.setattr(menubar_module.transcription_retry, 'mark_done', marked_done)
    due = MagicMock(return_value=[])
    monkeypatch.setattr(menubar_module.transcription_retry, 'due_paths', due)

    return SimpleNamespace(
        defer=deferred, mark_done=marked_done, due_paths=due,
        run=menubar_module.asyncio.run, wav=str(tmp_path / 'rec.wav'),
    )


def _capture_threads(monkeypatch):
    '''Collect the work a scan hands to background threads, to run it on demand.'''
    started = []

    def fake_thread(target, args=(), kwargs=None, daemon=None):
        started.append(lambda: target(*args, **(kwargs or {})))
        return SimpleNamespace(start=lambda: None)

    monkeypatch.setattr(menubar_module.threading, 'Thread', fake_thread)
    return started


def _fail_transcription(monkeypatch, error=RuntimeError('boom')):
    def fail(_coro):
        raise error

    monkeypatch.setattr(menubar_module.asyncio, 'run', fail)
    return error


def test_failed_transcription_defers_without_notifying(app, retry, monkeypatch):
    _fail_transcription(monkeypatch)

    app._transcribe_in_background(retry.wav)

    retry.defer.assert_called_once_with(retry.wav, app.config)
    app._notify.assert_not_called()


def test_crash_recovery_failure_defers_the_same_way(app, retry, monkeypatch, tmp_path):
    _fail_transcription(monkeypatch)
    orphan = tmp_path / 'orphan'
    orphan.mkdir()
    monkeypatch.setattr(menubar_module.recorder, 'merge_and_cleanup', lambda m, s, d: retry.wav)

    app._recover_in_background([str(orphan)])

    retry.defer.assert_called_once_with(retry.wav, app.config)
    app._notify.assert_not_called()


def test_abandonment_notifies_exactly_once(app, retry, monkeypatch):
    error = _fail_transcription(monkeypatch)
    retry.defer.return_value = menubar_module.transcription_retry.ledger.LedgerEntry('abandoned', 72)

    app._transcribe_in_background(retry.wav)

    app._notify.assert_called_once_with('Transcription failed', str(error))


def test_notifies_when_the_recording_cannot_even_be_deferred(app, retry, monkeypatch):
    error = _fail_transcription(monkeypatch)
    retry.defer.side_effect = OSError('ledger unwritable')

    app._transcribe_in_background(retry.wav)

    app._notify.assert_called_once_with('Transcription failed', str(error))


def test_successful_first_attempt_touches_no_ledger(app, retry):
    app._transcribe_in_background(retry.wav)

    retry.defer.assert_not_called()
    retry.mark_done.assert_not_called()


def test_scan_retries_a_due_entry_and_marks_it_done(app, retry, monkeypatch):
    retry.due_paths.return_value = [retry.wav]
    started = _capture_threads(monkeypatch)

    app._run_transcription_retry_scan(sender=MagicMock())

    assert len(started) == 1
    started[0]()
    retry.mark_done.assert_called_once_with(retry.wav, app.config)


def test_scan_marks_done_under_the_path_it_retried_even_if_the_run_renames_it(
    app, retry, monkeypatch, tmp_path,
):
    # A successful run renames the recording to carry its title, but the ledger entry was
    # created under the pre-rename path - marking done under the new one would strand the
    # original entry and retry it until its budget ran out.
    original = tmp_path / '2024-03-15_10-00-00.wav'
    original.write_bytes(b'recorded-audio')
    renamed = tmp_path / '2024-03-15_10-00-00 - Weekly-Planning.wav'

    def transcribe_and_rename(_coro):
        original.rename(renamed)

    monkeypatch.setattr(menubar_module.asyncio, 'run', transcribe_and_rename)
    retry.due_paths.return_value = [str(original)]
    started = _capture_threads(monkeypatch)

    app._run_transcription_retry_scan(sender=MagicMock())
    started[0]()

    retry.mark_done.assert_called_once_with(str(original), app.config)
    retry.defer.assert_not_called()
    assert renamed.exists()


def test_scan_starts_at_most_the_per_scan_limit(app, retry, monkeypatch):
    limit = menubar_module.MAX_TRANSCRIPTION_RETRIES_PER_SCAN
    retry.due_paths.return_value = [f'/tmp/rec-{i}.wav' for i in range(limit + 2)]
    started = _capture_threads(monkeypatch)

    app._run_transcription_retry_scan(sender=MagicMock())

    assert len(started) == limit


def test_scan_retries_the_oldest_due_entries_first(app, retry, monkeypatch):
    limit = menubar_module.MAX_TRANSCRIPTION_RETRIES_PER_SCAN
    due = [f'/tmp/rec-{i}.wav' for i in range(limit + 2)]
    retry.due_paths.return_value = due
    started = _capture_threads(monkeypatch)
    attempted = []
    monkeypatch.setattr(app, '_transcribe_recording', lambda path, **_: attempted.append(path))

    app._run_transcription_retry_scan(sender=MagicMock())
    for run in started:
        run()

    assert attempted == due[:limit]


def test_scan_skips_a_recording_already_being_transcribed(app, retry):
    app._claim_transcription(retry.wav)

    app._transcribe_recording(retry.wav, is_retry=True)

    retry.mark_done.assert_not_called()
    retry.defer.assert_not_called()


def test_in_flight_claim_is_released_after_an_attempt(app, retry):
    app._transcribe_recording(retry.wav)

    assert app._inflight_transcriptions == set()
    # A later attempt for the same path is therefore not skipped.
    assert app._claim_transcription(retry.wav) is True


def test_in_flight_claim_is_released_after_a_failed_attempt(app, retry, monkeypatch):
    _fail_transcription(monkeypatch)

    app._transcribe_recording(retry.wav)

    assert app._inflight_transcriptions == set()


def test_scan_survives_an_unreadable_ledger(app, retry):
    retry.due_paths.side_effect = OSError('unreadable')

    app._run_transcription_retry_scan(sender=MagicMock())

    app._notify.assert_not_called()
# --- Microphone-attention icon blink ------------------------------------------

def test_blink_toggles_state_name_while_flag_is_set(app):
    app._set_recording_state(True)
    assert app._current_state_name() == 'recording'

    app._add_mic_attention_reason('silence')
    app._blink_timer.start.assert_called_once()
    assert app._current_state_name() == 'recording'

    app._on_blink_tick(None)
    assert app._current_state_name() == 'idle'

    app._on_blink_tick(None)
    assert app._current_state_name() == 'recording'


def test_blink_applies_to_recording_transcribing_state(app):
    app._set_recording_state(True)
    app._begin_transcription()
    assert app._current_state_name() == 'recording_transcribing'

    app._add_mic_attention_reason('paused')
    app._blink_phase = True

    assert app._current_state_name() == 'idle'


def test_blink_stops_on_recovery(app):
    app._set_recording_state(True)
    app._add_mic_attention_reason('silence')
    app._blink_phase = True
    assert app._current_state_name() == 'idle'

    app._clear_mic_attention_reason('silence')

    app._blink_timer.stop.assert_called_once()
    assert app._current_state_name() == 'recording'


def test_blink_reasons_do_not_clear_until_all_cleared(app):
    app._set_recording_state(True)
    app._add_mic_attention_reason('silence')
    app._add_mic_attention_reason('paused')

    app._clear_mic_attention_reason('silence')
    app._blink_timer.stop.assert_not_called()

    app._clear_mic_attention_reason('paused')
    app._blink_timer.stop.assert_called_once()


def test_steady_states_unchanged_when_flag_clear(app):
    assert app._current_state_name() == 'idle'
    app._set_recording_state(True)
    assert app._current_state_name() == 'recording'
    app._begin_transcription()
    assert app._current_state_name() == 'recording_transcribing'
    app._end_transcription()
    app._set_recording_state(False)
    assert app._current_state_name() == 'idle'


def test_on_silence_warning_mic_channel_sets_attention_and_notifies(app):
    app._set_recording_state(True)

    app.on_silence_warning('mic')

    assert 'silence' in app._mic_attention_reasons
    app._notify.assert_called_once()
    assert 'Microphone' in app._notify.call_args.args[0]


def test_on_silence_warning_sys_channel_does_not_set_attention(app):
    app._set_recording_state(True)

    app.on_silence_warning('sys')

    assert 'silence' not in app._mic_attention_reasons
    app._notify.assert_called_once()
    assert 'System audio' in app._notify.call_args.args[0]


def test_on_silence_recovered_clears_mic_attention(app):
    app._set_recording_state(True)
    app._add_mic_attention_reason('silence')

    app.on_silence_recovered('mic')

    assert 'silence' not in app._mic_attention_reasons


def test_on_silence_warning_marshals_to_main_thread(app, monkeypatch):
    # The recorder's silence monitor calls this from its own background thread; the blink
    # timer and status bar icon it touches must be driven from the main thread, so this must
    # not run inline on whatever thread calls it.
    call_after = MagicMock()
    monkeypatch.setattr(menubar_module.AppHelper, 'callAfter', call_after)

    app.on_silence_warning('mic')

    app._notify.assert_not_called()
    call_after.assert_called_once_with(app._handle_silence_warning, 'mic')


def test_on_silence_recovered_marshals_to_main_thread(app, monkeypatch):
    call_after = MagicMock()
    monkeypatch.setattr(menubar_module.AppHelper, 'callAfter', call_after)

    app.on_silence_recovered('mic')

    call_after.assert_called_once_with(app._handle_silence_recovered, 'mic')


# --- Switch microphone from the menu bar --------------------------------------

def test_switch_mic_item_enablement_follows_recording_state(app):
    assert app.switch_mic_item.callback is None

    app._set_recording_state(True)
    assert app.switch_mic_item.callback == app.on_switch_mic

    app._set_recording_state(False)
    assert app.switch_mic_item.callback is None


def test_on_switch_mic_pauses_then_builds_dialog_after_pause(app, monkeypatch):
    app._set_recording_state(True)
    call_order = []
    monkeypatch.setattr(menubar_module.recorder, 'pause_mic', lambda: call_order.append('pause'))
    monkeypatch.setattr(
        menubar_module.recorder, 'list_input_devices',
        lambda: call_order.append('enumerate') or [{'index': 0, 'name': 'Built-in Mic'}],
    )
    dialog = MagicMock()
    monkeypatch.setattr(menubar_module.AppHelper, 'callAfter', lambda func, *a, **k: func(*a, **k))
    monkeypatch.setattr(menubar_module.MenubarApp, '_show_mic_selection_dialog', dialog)

    app.on_switch_mic(None)

    assert call_order == ['pause', 'enumerate']
    dialog.assert_called_once()
    devices_arg = dialog.call_args.args[0]
    assert devices_arg == [{'index': 0, 'name': 'Built-in Mic'}]


def test_switch_mic_cancellation_resumes_capture(app, monkeypatch):
    app._set_recording_state(True)
    resume_mic = MagicMock(return_value=None)
    monkeypatch.setattr(menubar_module.recorder, 'resume_mic', resume_mic)
    monkeypatch.setattr(menubar_module.AppHelper, 'callAfter', lambda func, *a, **k: func(*a, **k))
    monkeypatch.setattr(menubar_module.MenubarApp, '_run_mic_selection_alert', lambda self, devices: None)

    app._show_mic_selection_dialog([{'index': 0, 'name': 'Built-in Mic'}])

    resume_mic.assert_called_once_with(None)
    assert app.switch_mic_item.callback == app.on_switch_mic
    assert 'paused' not in app._mic_attention_reasons


def test_switch_mic_selection_resumes_on_chosen_device(app, monkeypatch):
    app._set_recording_state(True)
    resume_mic = MagicMock(return_value=None)
    monkeypatch.setattr(menubar_module.recorder, 'resume_mic', resume_mic)
    monkeypatch.setattr(menubar_module.AppHelper, 'callAfter', lambda func, *a, **k: func(*a, **k))
    monkeypatch.setattr(menubar_module.MenubarApp, '_run_mic_selection_alert', lambda self, devices: 2)

    app._show_mic_selection_dialog([{'index': 2, 'name': 'AirPods'}])

    resume_mic.assert_called_once_with(2)


def test_switch_mic_empty_device_list_resumes_previous(app, monkeypatch):
    app._set_recording_state(True)
    resume_mic = MagicMock(return_value=None)
    monkeypatch.setattr(menubar_module.recorder, 'resume_mic', resume_mic)
    monkeypatch.setattr(menubar_module.AppHelper, 'callAfter', lambda func, *a, **k: func(*a, **k))

    app._show_mic_selection_dialog([])

    app._show_alert.assert_called_once()
    resume_mic.assert_called_once_with(None)


def test_switch_mic_failure_shows_alert_without_stopping_recording(app, monkeypatch):
    app._set_recording_state(True)
    monkeypatch.setattr(
        menubar_module.recorder, 'resume_mic',
        MagicMock(side_effect=RuntimeError('unsupported sample rate')),
    )
    call_after = MagicMock(side_effect=lambda func, *a, **k: func(*a, **k))
    monkeypatch.setattr(menubar_module.AppHelper, 'callAfter', call_after)

    app._resume_mic_async(3)

    app._show_alert.assert_called_once()
    assert app.is_recording is True


def test_switch_mic_setup_failure_falls_back_and_shows_alert(app, monkeypatch):
    app._set_recording_state(True)
    monkeypatch.setattr(menubar_module.recorder, 'pause_mic', MagicMock(side_effect=RuntimeError('no permission')))
    monkeypatch.setattr(menubar_module.recorder, 'resume_mic', MagicMock(return_value=1))
    monkeypatch.setattr(menubar_module.AppHelper, 'callAfter', lambda func, *a, **k: func(*a, **k))

    app.on_switch_mic(None)

    app._show_alert.assert_called_once()
    assert app.is_recording is True
    assert app.switch_mic_item.callback == app.on_switch_mic
