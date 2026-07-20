import asyncio
import logging
import os
import threading
from datetime import datetime

import rumps
from AppKit import NSAlert, NSApplication, NSStatusWindowLevel
from PyObjCTools import AppHelper

from meet_recorder import calendar, drive, meet_ingest, recorder, transcriber
from meet_recorder.config import load_config

logger = logging.getLogger(__name__)

IDLE_TITLE = '\U0001f3a4'
RECORDING_TITLE = '\U0001f534'
TRANSCRIBING_TITLE = '⏳'
RECORDING_TRANSCRIBING_TITLE = '\U0001f534⏳'

RECOVERY_SCAN_DELAY_SECONDS = 1
AUTORECORD_FAILURE_NOTIFY_THRESHOLD = 3
MEET_INGEST_FAILURE_NOTIFY_THRESHOLD = 3


class MenubarApp(rumps.App):
    def __init__(self):
        super().__init__('MeetRecorder', title=IDLE_TITLE, quit_button=None)

        self.is_recording = False
        self.active_transcriptions = 0
        self._transcriptions_lock = threading.Lock()

        self.start_item = rumps.MenuItem('Iniciar', callback=self.on_start)
        self.stop_item = rumps.MenuItem('Parar', callback=None)
        self.stop_no_transcribe_item = rumps.MenuItem('Parar e não transcrever', callback=None)
        self.quit_item = rumps.MenuItem('Sair', callback=self.on_quit)

        self.menu = [self.start_item, self.stop_item, self.stop_no_transcribe_item, self.quit_item]

        recorder.on_silence_warning = self.on_silence_warning

        self._recovery_timer = rumps.Timer(self._run_recovery_scan, RECOVERY_SCAN_DELAY_SECONDS)

        self.config = self._load_config_safe()
        self._notified_events = set()
        self._prompted_events = set()
        self._poll_failures = 0
        self._cached_events = []
        self._calendar_poll_timer = self._build_calendar_poll_timer()
        self._meeting_check_timer = (
            rumps.Timer(self._run_meeting_check, self.config.autorecord.check_interval_seconds)
            if self._autorecord_active() else None
        )
        self._calendar_poll_kickoff_timer = rumps.Timer(self._run_calendar_poll_kickoff, RECOVERY_SCAN_DELAY_SECONDS)

        self._meet_poll_failures = 0
        self._meet_poll_timer = self._build_meet_poll_timer()
        self._meet_poll_kickoff_timer = rumps.Timer(self._run_meet_poll_kickoff, RECOVERY_SCAN_DELAY_SECONDS)

        if self._calendar_poll_timer is None:
            logger.info('Meeting prompt inactive (see debug log above for why)')
        else:
            logger.info(
                f'Meeting prompt active: polling every {self.config.autorecord.calendar_poll_interval_minutes}min, '
                f'checking every {self.config.autorecord.check_interval_seconds}s, '
                f'notifying {self.config.autorecord.notify_before_minutes}min before start'
            )

        if self._meet_poll_timer is None:
            logger.info('Meet-transcript ingestion inactive (see debug log above for why)')
        else:
            logger.info(
                'Meet-transcript ingestion active: '
                f'polling every {self.config.meet_transcripts.poll_interval_minutes}min, '
                f'look-back {self.config.meet_transcripts.lookback_hours}h'
            )

    def run(self, **options):
        self._recovery_timer.start()
        if self._calendar_poll_timer is not None:
            self._calendar_poll_timer.start()
            self._meeting_check_timer.start()
            self._calendar_poll_kickoff_timer.start()
        if self._meet_poll_timer is not None:
            self._meet_poll_timer.start()
            self._meet_poll_kickoff_timer.start()
        super().run(**options)

    def _run_calendar_poll_kickoff(self, sender):
        # rumps.Timer only fires for the first time after a full interval, so an
        # in-progress meeting would wait up to calendar_poll_interval_minutes after app
        # start. Run one immediate poll+check so restarting mid-meeting records right away.
        logger.debug('Running immediate meeting-prompt poll on startup')
        sender.stop()
        self._run_calendar_poll(sender)
        self._run_meeting_check(sender)

    def _load_config_safe(self):
        try:
            return load_config()
        except Exception as e:
            logger.warning(f'Could not load config for meeting prompt: {e}')
            return None

    def _autorecord_active(self):
        if self.config is None:
            logger.debug('Meeting prompt disabled: config failed to load')
            return False
        if not self.config.autorecord.enabled:
            logger.debug('Meeting prompt disabled: autorecord.enabled is false in config')
            return False
        if not self.config.calendar_enabled:
            logger.debug('Meeting prompt disabled: no `calendars:` configured')
            return False
        return True

    def _build_calendar_poll_timer(self):
        if not self._autorecord_active():
            return None

        interval = self.config.autorecord.calendar_poll_interval_minutes * 60
        return rumps.Timer(self._run_calendar_poll, interval)

    def _meet_transcripts_active(self):
        if self.config is None:
            logger.debug('Meet-transcript ingestion disabled: config failed to load')
            return False
        meet_transcripts = getattr(self.config, 'meet_transcripts', None)
        if meet_transcripts is None or not meet_transcripts.enabled:
            logger.debug('Meet-transcript ingestion disabled: meet_transcripts.enabled is false in config')
            return False
        if not self.config.calendar_enabled:
            logger.debug('Meet-transcript ingestion disabled: no `calendars:` configured')
            return False
        return True

    def _build_meet_poll_timer(self):
        if not self._meet_transcripts_active():
            return None

        interval = self.config.meet_transcripts.poll_interval_minutes * 60
        return rumps.Timer(self._run_meet_poll, interval)

    def _run_meet_poll_kickoff(self, sender):
        # Mirror the meeting-prompt kickoff: run one immediate ingest so a just-ended meeting
        # is picked up right away instead of waiting a full poll interval after startup.
        logger.debug('Running immediate Meet-transcript ingest on startup')
        sender.stop()
        self._run_meet_poll(sender)

    def _run_meet_poll(self, sender):
        thread = threading.Thread(target=self._ingest_in_background, daemon=True)
        thread.start()

    def _ingest_in_background(self):
        self._begin_transcription()

        try:
            results = meet_ingest.ingest_once(self.config, on_access_error=self._on_meet_access_error)
            self._meet_poll_failures = 0
            for result in results:
                logger.info(f'Meet transcript ingested: {result["transcript_path"]}')
        except drive.DriveScopeError as e:
            logger.error(str(e))
            self._show_alert_on_main(title='Reautorização necessária', message=str(e), ok='OK')
        except Exception as e:
            self._on_meet_poll_failure(e)
        finally:
            self._end_transcription()

    def _on_meet_access_error(self, event):
        self._show_alert_on_main(
            title='Transcrição inacessível',
            message=f'Não foi possível acessar a transcrição de "{event.title}"; tentaremos novamente.',
            ok='OK',
        )

    def _on_meet_poll_failure(self, error):
        self._meet_poll_failures += 1
        logger.warning(f'Meet-transcript ingest poll failed: {error}')

        if self._meet_poll_failures == MEET_INGEST_FAILURE_NOTIFY_THRESHOLD:
            self._notify('Falha na ingestão', f'Não foi possível ingerir transcrições do Meet: {error}')

    def _run_recovery_scan(self, sender):
        sender.stop()

        candidates = recorder.list_orphan_candidates()
        valid_orphans = recorder.discard_invalid_orphans(candidates)

        if not valid_orphans:
            return

        count = len(valid_orphans)
        noun = 'gravação pendente' if count == 1 else 'gravações pendentes'
        message = (
            f'{count} {noun} encontrada(s) de uma sessão anterior encerrada inesperadamente. '
            'O que deseja fazer?'
        )

        response = self._show_alert(
            title='Gravações pendentes encontradas', message=message, ok='Processar', cancel='Ignorar', other='Apagar',
        )

        if response == 1:
            thread = threading.Thread(target=self._recover_in_background, args=(valid_orphans,), daemon=True)
            thread.start()
        elif response == -1:
            for orphan_dir in valid_orphans:
                recorder.delete_orphan(orphan_dir)

    def _notify(self, subtitle, message):
        # Notifications are best-effort: rumps.notification raises when the running
        # environment lacks an Info.plist/CFBundleIdentifier (e.g. a bare venv), and
        # a failed notification must never abort recording or the autorecord poll.
        try:
            rumps.notification(title='Meet Recorder', subtitle=subtitle, message=message)
        except Exception as e:
            logger.warning(f'Notification failed ({subtitle}: {message}): {e}')

    def _autorecord_window_minutes(self):
        autorecord = self.config.autorecord
        return autorecord.notify_before_minutes + autorecord.calendar_poll_interval_minutes

    def _run_calendar_poll(self, sender):
        window_minutes = self._autorecord_window_minutes()
        logger.debug(f'Polling calendar for events within {window_minutes}min')

        try:
            events = calendar.upcoming_events(self.config, window_minutes)
        except Exception as e:
            self._on_poll_failure(e)
            return

        self._poll_failures = 0
        logger.debug(f'Poll returned {len(events)} event(s): {[e.title for e in events]}')
        self._cached_events = events

    def _run_meeting_check(self, sender):
        now = datetime.now().astimezone()
        for event in self._cached_events:
            self._maybe_notify_upcoming(event, now)
            self._maybe_prompt_start(event, now)

    def _on_poll_failure(self, error):
        self._poll_failures += 1
        logger.warning(f'Meeting-prompt poll failed: {error}')

        if self._poll_failures == AUTORECORD_FAILURE_NOTIFY_THRESHOLD:
            self._notify('Falha no calendário', f'Não foi possível consultar o calendário: {error}')

    def _maybe_notify_upcoming(self, event, now):
        if event.id in self._notified_events:
            logger.debug(f'"{event.title}": upcoming notification already shown, skipping')
            return
        if event.start_dt <= now:
            logger.debug(f'"{event.title}": already started ({event.start_dt}), skipping upcoming notification')
            return

        minutes_until = (event.start_dt - now).total_seconds() / 60
        if minutes_until > self.config.autorecord.notify_before_minutes:
            logger.debug(
                f'"{event.title}": starts in {minutes_until:.1f}min, outside '
                f'notify_before_minutes={self.config.autorecord.notify_before_minutes}, skipping'
            )
            return

        self._notified_events.add(event.id)
        logger.info(f'Showing upcoming-meeting notification for "{event.title}" at {event.start_dt}')
        self._notify('Próxima reunião', f'{event.title} às {event.start_dt.strftime("%H:%M")}')

    def _maybe_prompt_start(self, event, now):
        if event.id in self._prompted_events:
            logger.debug(f'"{event.title}": start modal already shown, skipping')
            return
        if event.start_dt > now:
            logger.debug(f'"{event.title}": has not started yet ({event.start_dt} > {now}), skipping')
            return

        age_seconds = (now - event.start_dt).total_seconds()
        if age_seconds < self.config.autorecord.prompt_delay_seconds:
            logger.debug(f'"{event.title}": started {age_seconds:.0f}s ago, waiting for prompt_delay_seconds, skipping')
            return

        age_minutes = age_seconds / 60
        if age_minutes > self.config.autorecord.max_meeting_age_minutes:
            logger.debug(f'"{event.title}": started {age_minutes:.1f}min ago, older than max_meeting_age_minutes, skipping')
            return

        self._prompted_events.add(event.id)

        if self.is_recording:
            logger.debug(f'"{event.title}": already recording, skipping start modal')
            return

        logger.info(f'Showing start-confirmation modal for "{event.title}" ({event.start_dt})')
        response = self._show_alert(
            title='Reunião começando',
            message=f'{event.title} às {event.start_dt.strftime("%H:%M")}',
            ok='Iniciar gravação',
            cancel='Agora não',
        )
        if response != 1:
            logger.info(f'User declined to start recording for "{event.title}" (response={response})')
            return

        logger.info(f'User confirmed recording for "{event.title}", starting')
        try:
            recorder.start_recording()
        except Exception as e:
            logger.error(f'Failed to start recording for "{event.title}": {e}')
            rumps.alert(title='Falha ao iniciar gravação', message=str(e))
            return

        self._set_recording_state(True)

    def _show_alert(self, title, message, ok=None, cancel=None, other=None):
        # This scan runs on a background timer rather than a user-initiated menu click, so
        # unlike the other alerts in this app some other application may be frontmost (even
        # fullscreen) when it fires. rumps.alert()'s plain runModal() would open behind it -
        # still blocking the run loop (and thus the status bar menu) until dismissed, but
        # invisible to the user. Raising the alert window's level and forcing it frontmost
        # (in addition to activating the app) ensures it's actually seen.
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

        alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
            title, ok, cancel, other, message.replace('%', '%%'),
        )
        alert.window().setLevel_(NSStatusWindowLevel)
        alert.window().orderFrontRegardless()

        return alert.runModal()

    def _show_alert_on_main(self, title, message, ok='OK'):
        # AppKit requires NSAlert on the main thread; the Meet-ingest alerts fire from a
        # background poll thread, so marshal the call instead of touching NSAlert directly.
        # These are OK-only alerts whose modal return value is ignored, so async is fine.
        AppHelper.callAfter(self._show_alert, title=title, message=message, ok=ok)

    def _recover_in_background(self, orphan_dirs):
        self._begin_transcription()

        try:
            for orphan_dir in orphan_dirs:
                mic_path = os.path.join(orphan_dir, 'mic.wav')
                sys_path = os.path.join(orphan_dir, 'sys.wav')
                path = recorder.merge_and_cleanup(mic_path, sys_path, orphan_dir)
                logger.info(f'Recovered recording saved to {path}')

                try:
                    asyncio.run(transcriber.transcribe(path))
                    logger.info(f'Transcription finished for {path}')
                except Exception as e:
                    logger.error(f'Transcription failed for {path}: {e}')
                    self._notify('Transcription failed', str(e))
        finally:
            self._end_transcription()

    def _begin_transcription(self):
        # active_transcriptions is mutated by several background threads; += / -= are
        # read-modify-write and not atomic, so serialize under a lock.
        with self._transcriptions_lock:
            self.active_transcriptions += 1
        self._refresh_title()

    def _end_transcription(self):
        with self._transcriptions_lock:
            self.active_transcriptions -= 1
        self._refresh_title()

    def _refresh_title(self):
        if self.is_recording and self.active_transcriptions > 0:
            self.title = RECORDING_TRANSCRIBING_TITLE
        elif self.is_recording:
            self.title = RECORDING_TITLE
        elif self.active_transcriptions > 0:
            self.title = TRANSCRIBING_TITLE
        else:
            self.title = IDLE_TITLE

    def _set_recording_state(self, recording):
        self.is_recording = recording
        self._refresh_title()
        self.start_item.set_callback(None if recording else self.on_start)
        self.stop_item.set_callback(self.on_stop if recording else None)
        self.stop_no_transcribe_item.set_callback(self.on_stop_no_transcribe if recording else None)

    def on_start(self, _):
        try:
            recorder.start_recording()
        except Exception as e:
            rumps.alert(title='Failed to start recording', message=str(e))
            return

        self._set_recording_state(True)

    def on_stop(self, _):
        path = recorder.stop_recording_and_save()
        logger.info(f'Recording saved to {path}')

        self._set_recording_state(False)

        thread = threading.Thread(target=self._transcribe_in_background, args=(path,), daemon=True)
        thread.start()

    def on_stop_no_transcribe(self, _):
        path = recorder.stop_recording_and_save()
        logger.info(f'Recording saved to {path} (transcription skipped)')

        self._set_recording_state(False)

    def _transcribe_in_background(self, path):
        self._begin_transcription()

        try:
            asyncio.run(transcriber.transcribe(path))
            logger.info(f'Transcription finished for {path}')
        except Exception as e:
            logger.error(f'Transcription failed for {path}: {e}')
            self._notify('Transcription failed', str(e))
        finally:
            self._end_transcription()

    def on_silence_warning(self):
        self._notify(
            'System audio may be silent',
            'Check that system output is routed to the Multi-Output Device',
        )

    def on_quit(self, _):
        if self.is_recording:
            recorder.stop_recording_and_save()
            self.is_recording = False

        if self.active_transcriptions > 0:
            response = rumps.alert(
                title='Transcrição em andamento',
                message=(
                    f'{self.active_transcriptions} transcrição(ões) em andamento. Sair mesmo assim? '
                    'A gravação original não será perdida e pode ser reprocessada depois.'
                ),
                ok='Sair',
                cancel='Cancelar',
            )
            if response != 1:
                return

        rumps.quit_application()
