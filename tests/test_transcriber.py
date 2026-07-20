import asyncio
import os
import subprocess
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

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
