import asyncio
import logging
import os
import threading
from datetime import datetime

import rumps
from AppKit import NSAlert, NSApplication, NSImage, NSPopUpButton, NSStatusWindowLevel
from Foundation import NSMakeRect
from PyObjCTools import AppHelper

from meet_recorder import calendar, drive, meet_ingest, recorder, transcriber, transcription_retry
from meet_recorder.config import load_config

logger = logging.getLogger(__name__)

ASSET_DIR = os.path.join(os.path.dirname(__file__), 'assets')
# Matches the canvas the icons were generated at (see assets/build script): fixed for every
# state so switching between them never resizes the NSStatusItem and shifts neighboring
# menu-bar icons ("falling").
ICON_SIZE_PT = (23.75, 28.75)
ICON_STATES = ('idle', 'recording', 'transcribing', 'recording_transcribing')

RECOVERY_SCAN_DELAY_SECONDS = 1
AUTORECORD_FAILURE_NOTIFY_THRESHOLD = 3
MEET_INGEST_FAILURE_NOTIFY_THRESHOLD = 3
# Well under the ledger's 1h retry interval, so a due entry is picked up promptly;
# a scan with nothing due is just one ledger read.
TRANSCRIPTION_RETRY_SCAN_INTERVAL_SECONDS = 5 * 60
# A scan can find a large backlog due at once (days offline, an expired API key). Each retry
# runs a full chunked-LLM transcription, so cap how many start per scan instead of fanning out
# one thread per due path; the rest are picked up by the next scan.
MAX_TRANSCRIPTION_RETRIES_PER_SCAN = 3
# Icon blink interval while the microphone needs attention (silent, or paused for a switch).
MIC_ATTENTION_BLINK_INTERVAL_SECONDS = 0.6


class MenubarApp(rumps.App):
    def __init__(self):
        super().__init__('MeetRecorder', quit_button=None)

        self.is_recording = False
        self.active_transcriptions = 0
        self._transcriptions_lock = threading.Lock()
        # Paths whose transcription is running right now, so a retry scan can't start
        # a second attempt for a file an earlier attempt is still working on.
        self._inflight_transcriptions = set()
        self._inflight_lock = threading.Lock()
        self._start_in_progress = False

        self._mic_attention_reasons = set()
        self._blink_phase = False
        self._blink_timer = rumps.Timer(self._on_blink_tick, MIC_ATTENTION_BLINK_INTERVAL_SECONDS)
        self._mic_switch_in_progress = False

        self._icons = self._load_icons()
        self._refresh_icon()

        self.start_item = rumps.MenuItem('Iniciar', callback=self.on_start)
        self.stop_item = rumps.MenuItem('Parar', callback=None)
        self.stop_no_transcribe_item = rumps.MenuItem('Parar e não transcrever', callback=None)
        self.discard_item = rumps.MenuItem('Descartar', callback=None)
        self.switch_mic_item = rumps.MenuItem('Trocar microfone…', callback=None)
        self.quit_item = rumps.MenuItem('Sair', callback=self.on_quit)

        self.menu = [
            self.start_item, self.stop_item, self.stop_no_transcribe_item, self.discard_item,
            self.switch_mic_item, self.quit_item,
        ]

        recorder.on_silence_warning = self.on_silence_warning
        recorder.on_silence_recovered = self.on_silence_recovered
        recorder.on_sys_capture_interrupted = self.on_sys_capture_interrupted
        recorder.on_sys_capture_restored = self.on_sys_capture_restored

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

        self._transcription_retry_timer = rumps.Timer(
            self._run_transcription_retry_scan, TRANSCRIPTION_RETRY_SCAN_INTERVAL_SECONDS
        )

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

    def _load_icons(self):
        return {state: self._build_nsimage(os.path.join(ASSET_DIR, f'{state}.png')) for state in ICON_STATES}

    @staticmethod
    def _build_nsimage(path):
        image = NSImage.alloc().initByReferencingFile_(path)
        image.setScalesWhenResized_(True)
        image.setSize_(ICON_SIZE_PT)
        return image

    def run(self, **options):
        self._recovery_timer.start()
        if self._calendar_poll_timer is not None:
            self._calendar_poll_timer.start()
            self._meeting_check_timer.start()
            self._calendar_poll_kickoff_timer.start()
        if self._meet_poll_timer is not None:
            self._meet_poll_timer.start()
            self._meet_poll_kickoff_timer.start()
        self._transcription_retry_timer.start()
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

        def on_failure(error):
            logger.error(f'Failed to start recording for "{event.title}": {error}')
            self._on_start_failure(error, alert_title='Falha ao iniciar gravação')

        self._start_recording_async(on_failure=on_failure)

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
        for orphan_dir in orphan_dirs:
            mic_path = os.path.join(orphan_dir, 'mic.wav')
            sys_path = os.path.join(orphan_dir, 'sys.wav')
            path = recorder.merge_and_cleanup(mic_path, sys_path, orphan_dir)
            logger.info(f'Recovered recording saved to {path}')

            self._transcribe_recording(path)

    def _begin_transcription(self):
        # active_transcriptions is mutated by several background threads; += / -= are
        # read-modify-write and not atomic, so serialize under a lock.
        with self._transcriptions_lock:
            self.active_transcriptions += 1
        self._refresh_icon()

    def _end_transcription(self):
        with self._transcriptions_lock:
            self.active_transcriptions -= 1
        self._refresh_icon()

    def _current_state_name(self):
        if self.is_recording and self.active_transcriptions > 0:
            base = 'recording_transcribing'
        elif self.is_recording:
            base = 'recording'
        elif self.active_transcriptions > 0:
            base = 'transcribing'
        else:
            base = 'idle'

        if self._mic_attention_reasons and self._blink_phase:
            return 'idle'
        return base

    def _on_blink_tick(self, sender):
        self._blink_phase = not self._blink_phase
        self._refresh_icon()

    def _add_mic_attention_reason(self, reason):
        was_active = bool(self._mic_attention_reasons)
        self._mic_attention_reasons.add(reason)
        if not was_active:
            self._blink_phase = False
            self._blink_timer.start()
            self._refresh_icon()

    def _clear_mic_attention_reason(self, reason):
        self._mic_attention_reasons.discard(reason)
        if not self._mic_attention_reasons:
            self._blink_timer.stop()
            self._blink_phase = False
            self._refresh_icon()

    def _refresh_icon(self):
        # Bypass the rumps `icon` property: it forces a fixed 20x20pt size via
        # _nsimage_from_file, which would squash our custom-aspect-ratio icons. Setting the
        # private _icon_nsimage attribute directly (same one that property assigns to) and
        # nudging the status item is the same mechanism rumps uses internally.
        self._icon_nsimage = self._icons[self._current_state_name()]
        nsapp = getattr(self, '_nsapp', None)
        if nsapp is not None:
            nsapp.setStatusBarIcon()

    def _set_recording_state(self, recording):
        self.is_recording = recording
        self._refresh_icon()
        self.start_item.set_callback(None if recording else self.on_start)
        self.stop_item.set_callback(self.on_stop if recording else None)
        self.stop_no_transcribe_item.set_callback(self.on_stop_no_transcribe if recording else None)
        self.discard_item.set_callback(self.on_discard if recording else None)
        self.switch_mic_item.set_callback(self.on_switch_mic if recording else None)
        if not recording:
            self._mic_switch_in_progress = False
            if self._mic_attention_reasons:
                self._mic_attention_reasons.clear()
                self._blink_timer.stop()
            self._blink_phase = False

    def _start_recording_async(self, on_failure=None):
        # recorder.start_recording() can block for a long time (or hang) on a stale
        # CoreAudio device reference; running it inline here would freeze the AppKit
        # run loop and the whole menu bar with it. Run it on a daemon thread instead and
        # marshal the result back via AppHelper.callAfter, same pattern as
        # _transcribe_in_background/_show_alert_on_main.
        if self._start_in_progress:
            return

        self._start_in_progress = True
        self.start_item.set_callback(None)

        def worker():
            try:
                recorder.start_recording()
            except Exception as e:
                AppHelper.callAfter(on_failure or self._on_start_failure, e)
            else:
                AppHelper.callAfter(self._on_start_success)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def _on_start_success(self):
        self._start_in_progress = False
        self._set_recording_state(True)

    def _on_start_failure(self, error, alert_title='Failed to start recording'):
        self._start_in_progress = False
        self.start_item.set_callback(self.on_start)
        rumps.alert(title=alert_title, message=str(error))

    def on_start(self, _):
        self._start_recording_async()

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

    def on_discard(self, _):
        response = self._show_alert(
            title='Descartar gravação?', message='', ok='Descartar', cancel='Cancelar',
        )
        if response != 1:
            return

        recorder.discard_recording()
        logger.info('Recording discarded')

        self._set_recording_state(False)

    def _transcribe_in_background(self, path):
        self._transcribe_recording(path)

    def _transcribe_recording(self, path, is_retry=False):
        '''Run the full pipeline for one recording, deferring to a later retry on failure.

        Shared by the normal stop flow, crash recovery, and the deferred-retry scan, so
        every entry point gets the same resilience. A recording already being transcribed
        is skipped rather than attempted twice.'''
        if not self._claim_transcription(path):
            logger.debug(f'Transcription already in progress for {path}; skipping this attempt')
            return

        self._begin_transcription()
        try:
            asyncio.run(transcriber.transcribe(path))
            logger.info(f'Transcription finished for {path}')
            if is_retry:
                # Deliberately the pre-rename path: a successful run renames the recording to
                # carry its title, but the ledger entry was created under the path this retry
                # started with, so that is the key that has to be cleared.
                transcription_retry.mark_done(path, self.config)
        except Exception as e:
            self._defer_transcription(path, e)
        finally:
            self._end_transcription()
            self._release_transcription(path)

    def _defer_transcription(self, path, error):
        '''Queue a failed transcription for a later retry, notifying only once it is abandoned.'''
        logger.error(f'Transcription failed for {path}: {error}')

        try:
            entry = transcription_retry.defer(path, self.config)
        except Exception as e:
            # Without a ledger entry nothing will ever retry, so fail loudly as before.
            logger.error(f'Could not defer transcription for {path}: {e}')
            self._notify('Transcription failed', str(error))
            return

        if entry.status == 'abandoned':
            logger.error(f'Giving up on {path} after {entry.attempts} attempt(s)')
            self._notify('Transcription failed', str(error))
        else:
            logger.info(f'Transcription for {path} deferred after attempt {entry.attempts}; will retry')

    def _claim_transcription(self, path):
        '''Reserve a recording for transcription; False when an attempt is already running.'''
        with self._inflight_lock:
            if path in self._inflight_transcriptions:
                return False
            self._inflight_transcriptions.add(path)
            return True

    def _release_transcription(self, path):
        with self._inflight_lock:
            self._inflight_transcriptions.discard(path)

    def _run_transcription_retry_scan(self, sender):
        try:
            due = transcription_retry.due_paths(self.config)
        except Exception as e:
            logger.warning(f'Deferred-transcription scan failed: {e}')
            return

        # due_paths is ordered oldest deferral first, and every attempt bumps its ledger
        # timestamp, so a backlog drains oldest-first across scans without starving anyone.
        paths = due[:MAX_TRANSCRIPTION_RETRIES_PER_SCAN]
        if len(due) > len(paths):
            logger.info(
                f'{len(due)} deferred transcriptions due; starting {len(paths)}, '
                'remaining left for the next scan'
            )

        for path in paths:
            logger.info(f'Retrying deferred transcription for {path}')
            thread = threading.Thread(
                target=self._transcribe_recording, args=(path,), kwargs={'is_retry': True}, daemon=True,
            )
            thread.start()

    def on_silence_warning(self, channel):
        # recorder's silence monitor calls this from its own background thread; both branches
        # below touch AppKit (the blink timer, the status bar icon), which - unlike the plain
        # rumps.notification() call in _notify() - must run on the main thread. Marshal instead
        # of executing inline, following the _show_alert_on_main pattern.
        AppHelper.callAfter(self._handle_silence_warning, channel)

    def _handle_silence_warning(self, channel):
        if channel == 'mic':
            self._add_mic_attention_reason('silence')
            self._notify(
                'Microphone may be silent',
                'Try switching the microphone input device from the menu bar.',
            )
        else:
            self._notify(
                'System audio may be silent',
                'Check that system output is routed to the Multi-Output Device',
            )

    def on_silence_recovered(self, channel):
        AppHelper.callAfter(self._handle_silence_recovered, channel)

    def _handle_silence_recovered(self, channel):
        if channel == 'mic':
            self._clear_mic_attention_reason('silence')

    def on_sys_capture_interrupted(self, error):
        # Called from the recorder's restart-supervisor thread; marshal to the main thread
        # like on_silence_warning, since _notify touches AppKit.
        AppHelper.callAfter(self._handle_sys_capture_interrupted, error)

    def _handle_sys_capture_interrupted(self, error):
        self._notify(
            'System audio interrupted',
            'System audio capture stopped; attempting to reconnect…',
        )

    def on_sys_capture_restored(self):
        AppHelper.callAfter(self._handle_sys_capture_restored)

    def _handle_sys_capture_restored(self):
        self._notify('System audio restored', 'System audio capture reconnected.')

    def _show_mic_selection_dialog(self, devices):
        if not devices:
            self._show_alert(
                title='Nenhum microfone encontrado', message='Nenhum dispositivo de entrada disponível.', ok='OK',
            )
            self._resume_mic_async(None)
            return

        chosen_device = self._run_mic_selection_alert(devices)
        self._resume_mic_async(chosen_device)

    def _run_mic_selection_alert(self, devices):
        # Isolated from _show_mic_selection_dialog so tests can stub the AppKit interaction
        # without touching NSAlert/NSPopUpButton directly (PyObjC-bridged classes cannot be
        # monkeypatched safely). Returns the selected device index, or None if cancelled.
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

        popup = NSPopUpButton.alloc().initWithFrame_pullsDown_(NSMakeRect(0, 0, 300, 24), False)
        for device in devices:
            popup.addItemWithTitle_(device['name'])

        alert = NSAlert.alertWithMessageText_defaultButton_alternateButton_otherButton_informativeTextWithFormat_(
            'Trocar microfone', 'Selecionar', 'Cancelar', None, '',
        )
        alert.setAccessoryView_(popup)
        alert.window().setLevel_(NSStatusWindowLevel)
        alert.window().orderFrontRegardless()

        response = alert.runModal()

        if response == 1:
            return devices[popup.indexOfSelectedItem()]['index']
        return None

    def _resume_mic_async(self, device):
        # Terminal path: success or MicResumeFallbackError both leave the microphone capturing
        # again, and a plain Exception here means resume_mic()'s own internal fallback also
        # failed - there is no further device left to retry, so report and stop rather than
        # calling back into this method again (which could otherwise loop forever).
        def worker():
            try:
                recorder.resume_mic(device)
            except recorder.MicResumeFallbackError as e:
                AppHelper.callAfter(self._on_mic_switch_fallback, e)
                return
            except Exception as e:
                AppHelper.callAfter(self._on_mic_switch_terminal_failure, e)
                return
            AppHelper.callAfter(self._on_mic_switch_success)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def _on_mic_switch_success(self):
        self._mic_switch_in_progress = False
        self.switch_mic_item.set_callback(self.on_switch_mic if self.is_recording else None)
        self._clear_mic_attention_reason('paused')

    def _on_mic_switch_fallback(self, error):
        self._on_mic_switch_success()
        self._show_alert_on_main(title='Falha ao trocar microfone', message=str(error))

    def _on_mic_switch_terminal_failure(self, error):
        logger.error(f'Failed to resume microphone: {error}')
        self._mic_switch_in_progress = False
        self.switch_mic_item.set_callback(self.on_switch_mic if self.is_recording else None)
        self._clear_mic_attention_reason('paused')
        self._show_alert_on_main(title='Microfone indisponível', message=str(error))

    def _on_mic_switch_setup_failure(self, error):
        logger.error(f'Microphone switch failed: {error}')
        # Never leave the recording without a microphone because pausing or enumeration failed:
        # fall back to whichever device was in use before the attempt.
        self._resume_mic_async(None)
        self._show_alert_on_main(title='Falha ao trocar microfone', message=str(error))

    def on_switch_mic(self, _):
        if self._mic_switch_in_progress:
            return

        self._mic_switch_in_progress = True
        self.switch_mic_item.set_callback(None)
        self._add_mic_attention_reason('paused')

        def worker():
            try:
                recorder.pause_mic()
                devices = recorder.list_input_devices()
            except Exception as e:
                AppHelper.callAfter(self._on_mic_switch_setup_failure, e)
                return
            AppHelper.callAfter(self._show_mic_selection_dialog, devices)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

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
