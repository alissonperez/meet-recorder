import asyncio
import os
import subprocess
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import yaml

from meet_recorder import transcriber


def _event(**overrides):
    base = dict(
        title='Weekly Sync',
        calendar='personal',
        start_dt=None,
        end_dt=None,
        start_raw='2024-03-15T10:00:00+00:00',
        end_raw='2024-03-15T11:00:00+00:00',
        attendees=['Alice', 'Bob'],
        description=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)

FILENAME_TIMESTAMP_FORMAT = transcriber.FILENAME_TIMESTAMP_FORMAT
TITLE_MAX_LENGTH = transcriber.TITLE_MAX_LENGTH
TITLE_MAX_ATTEMPTS = transcriber.TITLE_MAX_ATTEMPTS


def test_resolve_timestamp_parses_matching_filename(tmp_path):
    stem = '2024-03-15_10-30-00'
    wav_path = tmp_path / f'{stem}.wav'
    wav_path.write_bytes(b'')

    timestamp = transcriber._resolve_timestamp(str(wav_path))

    assert timestamp == datetime.strptime(stem, FILENAME_TIMESTAMP_FORMAT)


def test_resolve_timestamp_parses_titled_filename_prefix(tmp_path):
    stem = '2024-03-15_10-30-00'
    wav_path = tmp_path / f'{stem} - Weekly-Planning.wav'
    wav_path.write_bytes(b'')

    timestamp = transcriber._resolve_timestamp(str(wav_path))

    assert timestamp == datetime.strptime(stem, FILENAME_TIMESTAMP_FORMAT)
    # Explicitly not the mtime fallback, which is what the whole-stem parse used to give here.
    assert timestamp != datetime.fromtimestamp(os.path.getmtime(str(wav_path)))


def test_resolve_timestamp_falls_back_to_mtime(tmp_path):
    wav_path = tmp_path / 'not-a-timestamp.wav'
    wav_path.write_bytes(b'')

    timestamp = transcriber._resolve_timestamp(str(wav_path))

    expected = datetime.fromtimestamp(os.path.getmtime(str(wav_path)))
    assert timestamp == expected


def test_build_base_filename_includes_timestamp_title_and_suffix():
    timestamp = datetime(2024, 3, 15, 10, 30, 0).astimezone()

    filename = transcriber._build_base_filename(timestamp, 'My Meeting Title', suffix='RESUMO')

    expected_ts = transcriber._format_display_timestamp(timestamp)
    assert filename == f'{expected_ts} RESUMO - My-Meeting-Title'


def test_build_base_filename_without_suffix():
    timestamp = datetime(2024, 3, 15, 10, 30, 0).astimezone()

    filename = transcriber._build_base_filename(timestamp, 'Title')

    assert 'RESUMO' not in filename


def test_transcript_markdown_has_frontmatter_and_content():
    markdown = transcriber._transcript_markdown('My Title', 'the transcript text')

    assert markdown.startswith('---\ntitle: "My Title"\n---\n\n')
    assert 'the transcript text' in markdown


def test_summary_markdown_has_frontmatter_and_content():
    markdown = transcriber._summary_markdown('My Title', 'the summary text')

    assert markdown.startswith('---\ntitle: "My Title"\n---\n\n')
    assert 'the summary text' in markdown


def test_frontmatter_without_event_is_title_only():
    assert transcriber._frontmatter('My Title', None) == '---\ntitle: "My Title"\n---'


def test_frontmatter_with_event_includes_calendar_fields():
    frontmatter = transcriber._frontmatter('My Title', _event())

    assert 'calendar: "personal"' in frontmatter
    assert 'event_start: "2024-03-15T10:00:00+00:00"' in frontmatter
    assert 'event_end: "2024-03-15T11:00:00+00:00"' in frontmatter
    assert 'attendees:' in frontmatter
    assert '  - "Alice"' in frontmatter
    assert '  - "Bob"' in frontmatter


def test_frontmatter_is_valid_yaml_with_special_characters():
    event = _event(title='1:1: Sync "urgente" \\ #tag', attendees=['José: QA'])
    frontmatter = transcriber._frontmatter('1:1: Sync "urgente" \\ #tag', event)

    body = frontmatter.removeprefix('---\n').removesuffix('\n---')
    parsed = yaml.safe_load(body)

    assert parsed['title'] == '1:1: Sync "urgente" \\ #tag'
    assert parsed['attendees'] == ['José: QA']


def test_event_context_includes_title_and_attendees():
    context = transcriber._event_context(_event())

    assert 'Weekly Sync' in context
    assert 'Alice, Bob' in context


def test_event_context_includes_description_when_present():
    context = transcriber._event_context(_event(description='Agenda: revisar roadmap'))

    assert 'Descrição: Agenda: revisar roadmap' in context


def test_event_context_omits_description_when_absent():
    context = transcriber._event_context(_event(description=None))

    assert 'Descrição' not in context


def test_event_context_strips_html_from_description():
    description = '<b>Agenda:</b> revisar roadmap<br>Link: <a href="https://x.test">aqui</a>'
    context = transcriber._event_context(_event(description=description))

    assert '<' not in context
    assert '>' not in context
    assert 'Agenda: revisar roadmap' in context
    assert 'Link: aqui' in context


def test_event_context_truncates_long_description():
    description = 'x' * 1000
    context = transcriber._event_context(_event(description=description))

    line = next(line for line in context.splitlines() if line.startswith('Descrição:'))
    body = line.removeprefix('Descrição: ')

    assert body == ('x' * transcriber.EVENT_DESCRIPTION_MAX_LENGTH) + '…'


def test_event_context_omits_description_when_only_html():
    context = transcriber._event_context(_event(description='<br><br>  '))

    assert 'Descrição' not in context


def test_generate_summary_prepends_event_context(monkeypatch):
    captured = {}

    def fake_chat(model, system_prompt, user_content, config):
        captured['user_content'] = user_content
        return 'summary'

    monkeypatch.setattr(transcriber, '_chat_completion', fake_chat)
    config = Mock(summary_model='m', summary_prompt='p')

    transcriber._generate_summary('the transcript', config, _event())

    assert captured['user_content'].startswith('Título da reunião: Weekly Sync')
    assert 'the transcript' in captured['user_content']


def test_generate_summary_without_event_passes_transcript_only(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        transcriber, '_chat_completion',
        lambda model, sp, uc, cfg: captured.update(user_content=uc) or 'summary',
    )
    config = Mock(summary_model='m', summary_prompt='p')

    transcriber._generate_summary('the transcript', config)

    assert captured['user_content'] == 'the transcript'


def test_generate_summary_uses_override_prompt_and_gemini_context(monkeypatch):
    captured = {}

    def fake_chat(model, system_prompt, user_content, config):
        captured['system_prompt'] = system_prompt
        captured['user_content'] = user_content
        return 'summary'

    monkeypatch.setattr(transcriber, '_chat_completion', fake_chat)
    config = Mock(summary_model='m', summary_prompt='default prompt')

    transcriber._generate_summary(
        'the transcript', config, _event(),
        summary_prompt='meet prompt', gemini_context='gemini notes body',
    )

    assert captured['system_prompt'] == 'meet prompt'
    assert 'gemini notes body' in captured['user_content']
    assert captured['user_content'].startswith('Título da reunião: Weekly Sync')
    assert 'the transcript' in captured['user_content']


def _meet_config(tmp_path):
    return Mock(
        transcript_dir=str(tmp_path / 'transcripts'),
        summary_dir=str(tmp_path / 'summaries'),
        summary_model='m',
        summary_prompt='default prompt',
        meet_summary_prompt='meet prompt',
    )


def test_write_meet_output_writes_files_with_event_title_and_start_time(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        transcriber, '_chat_completion',
        lambda model, sp, uc, cfg: captured.update(system_prompt=sp, user_content=uc) or 'summary text',
    )
    start = datetime(2026, 7, 15, 10, 0, 0).astimezone()
    event = _event(title='Real Meeting', start_dt=start)

    result = transcriber.write_meet_output(
        event, 'transcript body', _meet_config(tmp_path), gemini_context='notes',
    )

    # Meet summary prompt + Gemini context flow into the summary call.
    assert captured['system_prompt'] == 'meet prompt'
    assert 'notes' in captured['user_content']

    transcript = open(result['transcript_path']).read()
    assert 'title: "Real Meeting"' in transcript
    assert 'transcript body' in transcript
    assert '2026-07' in result['transcript_path']
    assert 'Real-Meeting' in os.path.basename(result['summary_path'])


def test_write_meet_output_overwrites_existing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(transcriber, '_chat_completion', lambda model, sp, uc, cfg: 'summary')
    start = datetime(2026, 7, 15, 10, 0, 0).astimezone()
    event = _event(title='Real Meeting', start_dt=start)
    config = _meet_config(tmp_path)

    first = transcriber.write_meet_output(event, 'first body', config)
    second = transcriber.write_meet_output(event, 'second body', config)

    assert first['transcript_path'] == second['transcript_path']
    assert 'second body' in open(second['transcript_path']).read()


def _ingest_config(tmp_path):
    return Mock(
        transcript_dir=str(tmp_path / 'transcripts'),
        summary_dir=str(tmp_path / 'summaries'),
        summary_model='m',
        summary_prompt='default prompt',
    )


def test_ingest_doc_raises_when_url_is_not_a_doc_link(tmp_path):
    try:
        transcriber.ingest_doc('https://drive.google.com/file/d/abc123/view', _ingest_config(tmp_path), 'acc')
        assert False, 'expected TranscriptionError'
    except transcriber.TranscriptionError as e:
        assert 'Could not extract' in str(e)


def test_ingest_doc_exports_and_writes_files_with_explicit_title(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        transcriber.drive, 'export_doc_markdown',
        lambda account, doc_id: captured.update(account=account, doc_id=doc_id) or 'transcript body',
    )
    monkeypatch.setattr(transcriber, '_generate_summary', lambda t, c: 'summary body')
    gen_title = Mock()
    monkeypatch.setattr(transcriber, '_generate_title', gen_title)

    url = 'https://docs.google.com/document/d/doc123/edit'
    result = transcriber.ingest_doc(url, _ingest_config(tmp_path), 'work-account', title='Interview With X')

    assert captured == {'account': 'work-account', 'doc_id': 'doc123'}
    gen_title.assert_not_called()

    transcript = open(result['transcript_path']).read()
    assert 'title: "Interview With X"' in transcript
    assert 'transcript body' in transcript
    assert 'calendar:' not in transcript

    summary = open(result['summary_path']).read()
    assert 'title: "Interview With X"' in summary
    assert 'summary body' in summary


def test_ingest_doc_falls_back_to_llm_title_when_not_given(monkeypatch, tmp_path):
    monkeypatch.setattr(transcriber.drive, 'export_doc_markdown', lambda account, doc_id: 'transcript body')
    monkeypatch.setattr(transcriber, '_generate_summary', lambda t, c: 'summary body')
    monkeypatch.setattr(transcriber, '_generate_title', Mock(return_value='LLM Title'))

    url = 'https://docs.google.com/document/d/doc123/edit'
    result = transcriber.ingest_doc(url, _ingest_config(tmp_path), 'work-account')

    transcript = open(result['transcript_path']).read()
    assert 'title: "LLM Title"' in transcript


def _chunk_config():
    return Mock(
        transcription_model='stt',
        transcription_prompt='Transcreva o áudio.',
        base_url='https://example.test/v1',
    )


def _stub_transcription_post(monkeypatch, captured):
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')

    def fake_post(url, json, headers, timeout):
        captured['payload'] = json
        return Mock(raise_for_status=lambda: None, json=lambda: {'text': 'chunk text'})

    monkeypatch.setattr(transcriber.httpx, 'post', fake_post)


def test_transcribe_chunk_prepends_event_context_to_prompt(monkeypatch, tmp_path):
    chunk = tmp_path / 'chunk.mp3'
    chunk.write_bytes(b'audio')
    captured = {}
    _stub_transcription_post(monkeypatch, captured)

    text = transcriber._transcribe_chunk(str(chunk), _chunk_config(), _event(description='Agenda X'))

    assert text == 'chunk text'
    prompt = captured['payload']['prompt']
    assert prompt.startswith('Título da reunião: Weekly Sync')
    assert 'Descrição: Agenda X' in prompt
    assert 'Alice, Bob' in prompt
    assert prompt.endswith('Transcreva o áudio.')


def test_transcribe_chunk_sends_prompt_as_is_without_event(monkeypatch, tmp_path):
    chunk = tmp_path / 'chunk.mp3'
    chunk.write_bytes(b'audio')
    captured = {}
    _stub_transcription_post(monkeypatch, captured)

    transcriber._transcribe_chunk(str(chunk), _chunk_config())

    assert captured['payload']['prompt'] == 'Transcreva o áudio.'


def test_transcribe_audio_threads_event_to_each_chunk(monkeypatch):
    received = []
    monkeypatch.setattr(transcriber, '_split_into_chunks', lambda path, dur: ['c0', 'c1'])
    monkeypatch.setattr(
        transcriber, '_transcribe_chunk',
        lambda chunk, config, event=None: received.append(event) or 'x',
    )
    config = Mock(chunk_duration=420)
    event = _event()

    transcriber._transcribe_audio('audio.mp3', config, event)

    assert received == [event, event]


def _transcribe_config(tmp_path):
    return Mock(
        transcript_dir=str(tmp_path / 'transcripts'),
        summary_dir=str(tmp_path / 'summaries'),
    )


def test_transcribe_uses_event_title_and_skips_llm(monkeypatch, tmp_path):
    work_dir = tmp_path / 'work'
    work_dir.mkdir()
    monkeypatch.setattr(transcriber, '_preprocess_audio', lambda p: str(work_dir / 'a.mp3'))
    monkeypatch.setattr(transcriber, '_transcribe_audio', lambda m, c, e=None: 'transcript text')
    monkeypatch.setattr(transcriber, '_generate_summary', lambda t, c, e=None: 'summary text')

    gen_title = Mock(return_value='LLM Title')
    monkeypatch.setattr(transcriber, '_generate_title', gen_title)
    monkeypatch.setattr(transcriber.calendar, 'find_event', lambda ts, c: _event(title='Real Meeting'))

    wav = tmp_path / '2024-03-15_10-00-00.wav'
    wav.write_bytes(b'')

    result = asyncio.run(transcriber.transcribe(str(wav), config=_transcribe_config(tmp_path)))

    gen_title.assert_not_called()
    transcript = open(result['transcript_path']).read()
    assert 'title: "Real Meeting"' in transcript
    assert 'calendar: "personal"' in transcript
    assert 'Real-Meeting' in os.path.basename(result['transcript_path'])


def test_transcribe_derives_filenames_and_month_folder_from_start_time_filename(monkeypatch, tmp_path):
    work_dir = tmp_path / 'work'
    work_dir.mkdir()
    monkeypatch.setattr(transcriber, '_preprocess_audio', lambda p: str(work_dir / 'a.mp3'))
    monkeypatch.setattr(transcriber, '_transcribe_audio', lambda m, c, e=None: 'transcript text')
    monkeypatch.setattr(transcriber, '_generate_summary', lambda t, c, e=None: 'summary text')
    monkeypatch.setattr(transcriber, '_generate_title', Mock(return_value='LLM Title'))
    monkeypatch.setattr(transcriber.calendar, 'find_event', lambda ts, c: None)

    # Filename reflects the recording's start time; wav mtime (stop/save time) differs, e.g.
    # for a long recording that crossed into the next month.
    wav = tmp_path / '2024-03-15_10-00-00.wav'
    wav.write_bytes(b'')
    later_mtime = datetime(2024, 4, 1, 2, 0, 0).timestamp()
    os.utime(str(wav), (later_mtime, later_mtime))

    result = asyncio.run(transcriber.transcribe(str(wav), config=_transcribe_config(tmp_path)))

    expected_timestamp = transcriber._resolve_timestamp(str(wav))
    expected_display_ts = transcriber._format_display_timestamp(expected_timestamp)

    assert '2024-03' in result['transcript_path']
    assert '2024-04' not in result['transcript_path']
    assert expected_display_ts in os.path.basename(result['transcript_path'])
    assert '2024-03' in result['summary_path']
    assert expected_display_ts in os.path.basename(result['summary_path'])


def test_transcribe_falls_back_to_llm_title_without_event(monkeypatch, tmp_path):
    work_dir = tmp_path / 'work'
    work_dir.mkdir()
    monkeypatch.setattr(transcriber, '_preprocess_audio', lambda p: str(work_dir / 'a.mp3'))
    monkeypatch.setattr(transcriber, '_transcribe_audio', lambda m, c, e=None: 'transcript text')
    monkeypatch.setattr(transcriber, '_generate_summary', lambda t, c, e=None: 'summary text')

    gen_title = Mock(return_value='LLM Title')
    monkeypatch.setattr(transcriber, '_generate_title', gen_title)
    monkeypatch.setattr(transcriber.calendar, 'find_event', lambda ts, c: None)

    wav = tmp_path / '2024-03-15_10-00-00.wav'
    wav.write_bytes(b'')

    result = asyncio.run(transcriber.transcribe(str(wav), config=_transcribe_config(tmp_path)))

    gen_title.assert_called_once()
    transcript = open(result['transcript_path']).read()
    assert 'title: "LLM Title"' in transcript
    assert 'calendar:' not in transcript


def test_generate_title_returns_immediately_when_within_limit(monkeypatch):
    mock_chat_completion = Mock(return_value='A short title')
    monkeypatch.setattr(transcriber, '_chat_completion', mock_chat_completion)

    config = Mock(title_prompt='prompt', title_model='model')
    title = transcriber._generate_title('summary text', config)

    assert title == 'A short title'
    assert mock_chat_completion.call_count == 1


def test_generate_title_retries_then_truncates(monkeypatch):
    long_title = 'x' * (TITLE_MAX_LENGTH + 10)
    mock_chat_completion = Mock(return_value=long_title)
    monkeypatch.setattr(transcriber, '_chat_completion', mock_chat_completion)

    config = Mock(title_prompt='prompt', title_model='model')
    title = transcriber._generate_title('summary text', config)

    assert mock_chat_completion.call_count == TITLE_MAX_ATTEMPTS
    assert title == long_title[:TITLE_MAX_LENGTH]
    assert len(title) == TITLE_MAX_LENGTH


def test_split_into_chunks_returns_original_when_under_limit(monkeypatch):
    monkeypatch.setattr(transcriber, '_get_audio_duration', Mock(return_value=100.0))
    run_mock = Mock()
    monkeypatch.setattr(subprocess, 'run', run_mock)

    chunks = transcriber._split_into_chunks('/tmp/audio.mp3', chunk_duration=420)

    assert chunks == ['/tmp/audio.mp3']
    run_mock.assert_not_called()


def test_split_into_chunks_invokes_ffmpeg_per_chunk(monkeypatch):
    monkeypatch.setattr(transcriber, '_get_audio_duration', Mock(return_value=1000.0))
    run_mock = Mock(return_value=Mock(returncode=0))
    monkeypatch.setattr(subprocess, 'run', run_mock)

    chunks = transcriber._split_into_chunks('/tmp/audio.mp3', chunk_duration=420)

    assert len(chunks) == 3
    assert run_mock.call_count == 3
    for call in run_mock.call_args_list:
        args = call.args[0]
        assert args[0] == 'ffmpeg'


# --- Immediate retry (layer 1) ----------------------------------------------

def _status_error(status):
    return transcriber.httpx.HTTPStatusError(
        f'{status}', request=Mock(), response=Mock(status_code=status),
    )


def _flaky_post(monkeypatch, errors):
    '''Stub httpx.post to raise each error in turn, then succeed; records the attempts.'''
    monkeypatch.setenv('OPENROUTER_API_KEY', 'test-key')
    monkeypatch.setattr(transcriber.time, 'sleep', lambda _: None)
    attempts = []

    def fake_post(url, json, headers, timeout):
        attempts.append(json)
        if len(attempts) <= len(errors):
            raise errors[len(attempts) - 1]
        return Mock(raise_for_status=lambda: None, json=lambda: {'text': 'chunk text'})

    monkeypatch.setattr(transcriber.httpx, 'post', fake_post)
    return attempts


@pytest.mark.parametrize('error', [
    transcriber.httpx.ReadTimeout('read operation timed out'),
    transcriber.httpx.ConnectError('connection refused'),
    _status_error(429),
    _status_error(503),
])
def test_transcribe_chunk_retries_retryable_errors_then_succeeds(monkeypatch, tmp_path, error):
    chunk = tmp_path / 'chunk.mp3'
    chunk.write_bytes(b'audio')
    attempts = _flaky_post(monkeypatch, [error])

    assert transcriber._transcribe_chunk(str(chunk), _chunk_config()) == 'chunk text'
    assert len(attempts) == 2


def test_transcribe_chunk_fails_once_retries_are_exhausted(monkeypatch, tmp_path):
    chunk = tmp_path / 'chunk.mp3'
    chunk.write_bytes(b'audio')
    errors = [transcriber.httpx.ReadTimeout('timed out')] * transcriber.TRANSCRIPTION_MAX_ATTEMPTS
    attempts = _flaky_post(monkeypatch, errors)

    with pytest.raises(transcriber.TranscriptionError):
        transcriber._transcribe_chunk(str(chunk), _chunk_config())

    assert len(attempts) == transcriber.TRANSCRIPTION_MAX_ATTEMPTS


@pytest.mark.parametrize('status', [400, 401, 403, 404])
def test_transcribe_chunk_does_not_retry_non_retryable_errors(monkeypatch, tmp_path, status):
    chunk = tmp_path / 'chunk.mp3'
    chunk.write_bytes(b'audio')
    attempts = _flaky_post(monkeypatch, [_status_error(status)] * 3)

    with pytest.raises(transcriber.TranscriptionError):
        transcriber._transcribe_chunk(str(chunk), _chunk_config())

    assert len(attempts) == 1


def test_transcribe_chunk_missing_api_key_never_reaches_the_request(monkeypatch, tmp_path):
    chunk = tmp_path / 'chunk.mp3'
    chunk.write_bytes(b'audio')
    monkeypatch.delenv('OPENROUTER_API_KEY', raising=False)
    posted = Mock()
    monkeypatch.setattr(transcriber.httpx, 'post', posted)

    with pytest.raises(transcriber.TranscriptionError, match='OPENROUTER_API_KEY'):
        transcriber._transcribe_chunk(str(chunk), _chunk_config())

    posted.assert_not_called()


# --- Post-success recording rename -------------------------------------------

RENAME_TIMESTAMP = '2024-03-15_10-00-00'


def _mock_pipeline(monkeypatch, tmp_path, title='Weekly Planning', event=None):
    '''Stub every network/ffmpeg step of transcribe() so only its file-level behavior runs.'''
    work_dir = tmp_path / 'work'
    work_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(transcriber, '_preprocess_audio', lambda p: str(work_dir / 'a.mp3'))
    monkeypatch.setattr(transcriber, '_transcribe_audio', lambda m, c, e=None: 'transcript text')
    monkeypatch.setattr(transcriber, '_generate_summary', lambda t, c, e=None: 'summary text')
    monkeypatch.setattr(transcriber, '_generate_title', Mock(return_value=title))
    monkeypatch.setattr(transcriber.calendar, 'find_event', lambda ts, c: event)


def _recording(tmp_path, name=f'{RENAME_TIMESTAMP}.wav'):
    wav = tmp_path / name
    wav.write_bytes(b'recorded-audio')
    return wav


def _assert_outputs_intact(result):
    for key in ('transcript_path', 'summary_path'):
        assert os.path.isfile(result[key])
        assert open(result[key]).read()


def test_transcribe_renames_the_recording_to_the_run_title(monkeypatch, tmp_path):
    _mock_pipeline(monkeypatch, tmp_path)
    wav = _recording(tmp_path)

    result = asyncio.run(transcriber.transcribe(str(wav), config=_transcribe_config(tmp_path)))

    renamed = tmp_path / f'{RENAME_TIMESTAMP} - Weekly-Planning.wav'
    assert result['recording_path'] == str(renamed)
    assert renamed.read_bytes() == b'recorded-audio'
    assert not wav.exists()
    _assert_outputs_intact(result)
    # The title slug the recording took is the one the outputs were named with.
    assert 'Weekly-Planning' in os.path.basename(result['transcript_path'])


def test_transcribe_uses_the_event_title_for_the_rename(monkeypatch, tmp_path):
    _mock_pipeline(monkeypatch, tmp_path, event=_event(title='Real Meeting'))
    wav = _recording(tmp_path)

    result = asyncio.run(transcriber.transcribe(str(wav), config=_transcribe_config(tmp_path)))

    assert os.path.basename(result['recording_path']) == f'{RENAME_TIMESTAMP} - Real-Meeting.wav'
    _assert_outputs_intact(result)


def test_transcribe_leaves_a_recording_that_already_carries_the_title(monkeypatch, tmp_path):
    _mock_pipeline(monkeypatch, tmp_path)
    wav = _recording(tmp_path, name=f'{RENAME_TIMESTAMP} - Weekly-Planning.wav')

    result = asyncio.run(transcriber.transcribe(str(wav), config=_transcribe_config(tmp_path)))

    assert result['recording_path'] == str(wav)
    assert wav.read_bytes() == b'recorded-audio'
    _assert_outputs_intact(result)


def test_transcribe_keeps_the_name_when_the_title_slugifies_to_nothing(monkeypatch, tmp_path):
    _mock_pipeline(monkeypatch, tmp_path, title='!!! ???')
    wav = _recording(tmp_path)

    result = asyncio.run(transcriber.transcribe(str(wav), config=_transcribe_config(tmp_path)))

    assert result['recording_path'] == str(wav)
    assert wav.read_bytes() == b'recorded-audio'
    _assert_outputs_intact(result)


def test_transcribe_keeps_the_name_without_a_parseable_timestamp_prefix(monkeypatch, tmp_path):
    _mock_pipeline(monkeypatch, tmp_path)
    wav = _recording(tmp_path, name='meeting-audio.wav')

    result = asyncio.run(transcriber.transcribe(str(wav), config=_transcribe_config(tmp_path)))

    assert result['recording_path'] == str(wav)
    assert wav.read_bytes() == b'recorded-audio'
    _assert_outputs_intact(result)


def test_transcribe_does_not_overwrite_an_existing_destination(monkeypatch, tmp_path):
    _mock_pipeline(monkeypatch, tmp_path)
    wav = _recording(tmp_path)
    existing = tmp_path / f'{RENAME_TIMESTAMP} - Weekly-Planning.wav'
    existing.write_bytes(b'someone-elses-recording')

    result = asyncio.run(transcriber.transcribe(str(wav), config=_transcribe_config(tmp_path)))

    assert result['recording_path'] == str(wav)
    assert wav.read_bytes() == b'recorded-audio'
    assert existing.read_bytes() == b'someone-elses-recording'
    _assert_outputs_intact(result)


def test_transcribe_still_succeeds_when_the_rename_fails(monkeypatch, tmp_path):
    _mock_pipeline(monkeypatch, tmp_path)
    wav = _recording(tmp_path)

    def boom(src, dst):
        raise OSError('rename failed')

    monkeypatch.setattr(transcriber.naming.os, 'rename', boom)

    result = asyncio.run(transcriber.transcribe(str(wav), config=_transcribe_config(tmp_path)))

    assert result['recording_path'] == str(wav)
    assert wav.read_bytes() == b'recorded-audio'
    _assert_outputs_intact(result)


def test_transcribe_does_not_rename_when_the_run_fails(monkeypatch, tmp_path):
    _mock_pipeline(monkeypatch, tmp_path)
    monkeypatch.setattr(
        transcriber, '_generate_summary',
        Mock(side_effect=transcriber.TranscriptionError('summary failed')),
    )
    wav = _recording(tmp_path)

    with pytest.raises(transcriber.TranscriptionError):
        asyncio.run(transcriber.transcribe(str(wav), config=_transcribe_config(tmp_path)))

    assert wav.exists()
    assert wav.read_bytes() == b'recorded-audio'
    assert list(tmp_path.glob('*.wav')) == [wav]


def test_transcribe_writes_both_outputs_before_renaming(monkeypatch, tmp_path):
    _mock_pipeline(monkeypatch, tmp_path)
    wav = _recording(tmp_path)
    seen = {}

    real_rename = os.rename

    def observing_rename(src, dst):
        # Both output files must already be complete when the rename runs - the whole point
        # of doing it last is that nothing it can do puts the run's real work at risk.
        seen['transcripts'] = sorted(
            p.name for p in (tmp_path / 'transcripts').rglob('*.md')
        )
        seen['summaries'] = sorted(p.name for p in (tmp_path / 'summaries').rglob('*.md'))
        real_rename(src, dst)

    monkeypatch.setattr(transcriber.naming.os, 'rename', observing_rename)

    result = asyncio.run(transcriber.transcribe(str(wav), config=_transcribe_config(tmp_path)))

    assert len(seen['transcripts']) == 1
    assert len(seen['summaries']) == 1
    assert os.path.basename(result['transcript_path']) == seen['transcripts'][0]
    assert os.path.basename(result['summary_path']) == seen['summaries'][0]


def test_retranscribing_a_renamed_recording_reuses_its_start_timestamp(monkeypatch, tmp_path):
    _mock_pipeline(monkeypatch, tmp_path)
    wav = _recording(tmp_path)
    config = _transcribe_config(tmp_path)

    first = asyncio.run(transcriber.transcribe(str(wav), config=config))
    second = asyncio.run(transcriber.transcribe(first['recording_path'], config=config))

    # Same start timestamp, so same month folder and same output filenames - the rename in
    # between must not push the run onto the file's mtime.
    assert second['transcript_path'] == first['transcript_path']
    assert second['summary_path'] == first['summary_path']
    assert second['recording_path'] == first['recording_path']
