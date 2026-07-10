import logging
import os
import time

from icecream import ic

from meet_recorder import consolecolor as ccolor, data, menubar, recorder, transcriber
from meet_recorder.tools import handler


logger = logging.getLogger(__name__)


@handler
def handler_quotation(dryrun=False):
    '''Simple method to show current quotation of USD / BRL'''

    ic('getting quotation', dryrun)

    quotation = data.get_quotation(True, dryrun)

    logger.info('Quotation USD-BRL, ask for: {}'.format(ccolor.green('R$ {}'.format(quotation['USDBRL']['ask']))))
    logger.warn('Quotation USD-BRL, ask for: {}'.format(ccolor.green('R$ {}'.format(quotation['USDBRL']['ask']))))
    logger.error('Quotation USD-BRL, ask for: {}'.format(ccolor.green('R$ {}'.format(quotation['USDBRL']['ask']))))


def handler_read_csv(filename, verbose=True, dryrun=False):
    '''Read a CSV file and print its content'''

    ic('reading CSV file')

    for line in data.read_csv(filename):
        logger.info(f'Content: {ccolor.green(line)}')


@handler
def handler_record(duration=30):
    '''Record microphone + system audio for `duration` seconds and save as a stereo WAV file'''

    ic('starting recording', duration)

    recorder.start_recording()
    logger.info(f'Recording started, will stop in {duration}s...')

    try:
        time.sleep(duration)
    finally:
        path = recorder.stop_recording_and_save()
        logger.info(f'Recording saved to {ccolor.green(path)}')


@handler
def handler_menubar():
    '''Launch the macOS menu bar app for starting/stopping recordings'''

    ic('starting menubar app')

    menubar.MenubarApp().run()


@handler
async def handler_transcribe(path):
    '''Transcribe an existing WAV recording and generate a title + summary'''

    ic('transcribing recording', path)

    result = await transcriber.transcribe(path)

    logger.info(f'Transcript saved to {ccolor.green(result["transcript_path"])}')
    logger.info(f'Summary saved to {ccolor.green(result["summary_path"])}')


@handler
async def handler_recover():
    '''Scan for orphaned in-progress recordings left behind by a crash, then process/ignore/delete them'''

    ic('scanning for orphaned recordings')

    candidates = recorder.list_orphan_candidates()
    valid_orphans = recorder.discard_invalid_orphans(candidates)

    if not valid_orphans:
        logger.info('Nothing to recover')
        return

    count = len(valid_orphans)
    noun = 'gravação pendente' if count == 1 else 'gravações pendentes'
    choice = input(f'{count} {noun} encontrada(s). Processar (p), Ignorar (i) ou Apagar (a)? [p/i/a]: ').strip().lower()

    if choice == 'p':
        for orphan_dir in valid_orphans:
            mic_path = os.path.join(orphan_dir, 'mic.wav')
            sys_path = os.path.join(orphan_dir, 'sys.wav')
            path = recorder.merge_and_cleanup(mic_path, sys_path, orphan_dir)
            logger.info(f'Recovered recording saved to {ccolor.green(path)}')

            result = await transcriber.transcribe(path)
            logger.info(f'Transcript saved to {ccolor.green(result["transcript_path"])}')
            logger.info(f'Summary saved to {ccolor.green(result["summary_path"])}')
    elif choice == 'a':
        for orphan_dir in valid_orphans:
            recorder.delete_orphan(orphan_dir)
        logger.info('Pending recordings deleted')
    else:
        logger.info('Pending recordings left untouched')
