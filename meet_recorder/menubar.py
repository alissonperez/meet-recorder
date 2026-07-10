import asyncio
import logging
import os
import threading

import rumps
from AppKit import NSAlert, NSApplication, NSStatusWindowLevel

from meet_recorder import recorder, transcriber

logger = logging.getLogger(__name__)

IDLE_TITLE = '\U0001f3a4'
RECORDING_TITLE = '\U0001f534'
TRANSCRIBING_TITLE = '⏳'
RECORDING_TRANSCRIBING_TITLE = '\U0001f534⏳'

RECOVERY_SCAN_DELAY_SECONDS = 1


class MenubarApp(rumps.App):
    def __init__(self):
        super().__init__('MeetRecorder', title=IDLE_TITLE, quit_button=None)

        self.is_recording = False
        self.active_transcriptions = 0

        self.start_item = rumps.MenuItem('Iniciar', callback=self.on_start)
        self.stop_item = rumps.MenuItem('Parar', callback=None)
        self.stop_no_transcribe_item = rumps.MenuItem('Parar e não transcrever', callback=None)
        self.quit_item = rumps.MenuItem('Sair', callback=self.on_quit)

        self.menu = [self.start_item, self.stop_item, self.stop_no_transcribe_item, self.quit_item]

        recorder.on_silence_warning = self.on_silence_warning

        self._recovery_timer = rumps.Timer(self._run_recovery_scan, RECOVERY_SCAN_DELAY_SECONDS)

    def run(self, **options):
        self._recovery_timer.start()
        super().run(**options)

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

    def _recover_in_background(self, orphan_dirs):
        self.active_transcriptions += 1
        self._refresh_title()

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
                    rumps.notification(
                        title='Meet Recorder',
                        subtitle='Transcription failed',
                        message=str(e),
                    )
        finally:
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
        self.active_transcriptions += 1
        self._refresh_title()

        try:
            asyncio.run(transcriber.transcribe(path))
            logger.info(f'Transcription finished for {path}')
        except Exception as e:
            logger.error(f'Transcription failed for {path}: {e}')
            rumps.notification(
                title='Meet Recorder',
                subtitle='Transcription failed',
                message=str(e),
            )
        finally:
            self.active_transcriptions -= 1
            self._refresh_title()

    def on_silence_warning(self):
        rumps.notification(
            title='Meet Recorder',
            subtitle='System audio may be silent',
            message='Check that system output is routed to the Multi-Output Device',
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
