import logging

from meet_recorder import calendar, drive, ledger, transcriber

logger = logging.getLogger(__name__)


def _process_occurrence(event, config):
    '''Export the occurrence's docs and write output; return the written paths, or None.

    None means nothing is attached yet (transcript not available) — the caller leaves such
    an occurrence unrecorded so it is retried on the next poll. Raises drive.DriveScopeError
    (run-level) or drive.DriveAccessError (per-file) on export failures.'''
    attachments = calendar.attachments_for_occurrence(event)
    if not attachments.transcript_ids and not attachments.gemini_id:
        logger.debug(f'"{event.title}": no transcript/notes attached yet, leaving unrecorded')
        return None

    logger.info(
        f'"{event.title}": processing occurrence '
        f'({len(attachments.transcript_ids)} transcript doc(s), '
        f'gemini notes: {"yes" if attachments.gemini_id else "no"})'
    )

    gemini_context = None
    if attachments.gemini_id:
        logger.debug(f'"{event.title}": exporting Gemini notes doc {attachments.gemini_id}')
        gemini_context = drive.export_doc_markdown(event.calendar, attachments.gemini_id)

    if attachments.transcript_ids:
        parts = []
        for doc_id in attachments.transcript_ids:
            logger.debug(f'"{event.title}": exporting transcript doc {doc_id}')
            parts.append(drive.export_doc_markdown(event.calendar, doc_id))
        transcript_text = '\n\n'.join(parts)
        logger.debug(f'"{event.title}": transcript assembled ({len(transcript_text)} chars)')
    else:
        # Gemini-only occurrence: the notes become the transcript body (Decision 7); they are
        # not also passed as extra summary context since they already are the content.
        transcript_text = gemini_context or ''
        logger.debug(f'"{event.title}": no transcript docs, using Gemini notes as transcript body ({len(transcript_text)} chars)')
        gemini_context = None

    return transcriber.write_meet_output(
        event, transcript_text, config, gemini_context=gemini_context,
    )


def ingest_once(config, on_access_error=None):
    '''Ingest Meet transcripts for eligible past occurrences once over the look-back window.

    Returns the list of {transcript_path, summary_path} dicts written this run. A request-level
    missing-scope error aborts the whole run (raised as drive.DriveScopeError) without counting
    an attempt against any occurrence. A per-file access error defers that occurrence (throttled
    hourly retry, abandoned after max_access_retries) and invokes on_access_error(event) once —
    on the first failure only. Other per-occurrence errors are logged and do not abort the batch.'''
    events = calendar.past_events(config, config.meet_transcripts.lookback_hours)
    logger.debug(f'Meet ingest: {len(events)} past occurrence(s) in the look-back window')

    written = []
    for event in events:
        if ledger.should_skip(event.id):
            logger.debug(f'"{event.title}": skipped (ledger)')
            continue

        try:
            result = _process_occurrence(event, config)
        except drive.DriveScopeError:
            # A scope error hits every occurrence at once: abort the run, penalize no one.
            raise
        except drive.DriveAccessError as e:
            entry = ledger.record_access_failure(event.id, config.meet_transcripts.max_access_retries)
            logger.warning(f'"{event.title}": transcript not accessible ({e}); status={entry.status}')
            if entry.attempts == 1 and on_access_error is not None:
                on_access_error(event)
            continue
        except Exception as e:
            logger.error(f'"{event.title}": ingestion failed: {e}')
            continue

        if result is None:
            continue

        ledger.mark_done(event.id)
        logger.info(f'"{event.title}": ingested -> {result["transcript_path"]}')
        written.append(result)

    return written
