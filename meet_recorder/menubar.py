import logging

import rumps

from meet_recorder import recorder

logger = logging.getLogger(__name__)

IDLE_TITLE = '\U0001f3a4'
RECORDING_TITLE = '\U0001f534'


class MenubarApp(rumps.App):
    def __init__(self):
        super().__init__('MeetRecorder', title=IDLE_TITLE, quit_button=None)

        self.start_item = rumps.MenuItem('Iniciar', callback=self.on_start)
        self.stop_item = rumps.MenuItem('Parar', callback=None)
        self.quit_item = rumps.MenuItem('Sair', callback=self.on_quit)

        self.menu = [self.start_item, self.stop_item, self.quit_item]

        recorder.on_silence_warning = self.on_silence_warning

    def _set_recording_state(self, recording):
        self.title = RECORDING_TITLE if recording else IDLE_TITLE
        self.start_item.set_callback(None if recording else self.on_start)
        self.stop_item.set_callback(self.on_stop if recording else None)

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

    def on_silence_warning(self):
        rumps.notification(
            title='Meet Recorder',
            subtitle='System audio may be silent',
            message='Check that system output is routed to the Multi-Output Device',
        )

    def on_quit(self, _):
        if self.stop_item.callback is not None:
            recorder.stop_recording_and_save()

        rumps.quit_application()
