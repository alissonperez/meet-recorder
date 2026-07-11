import os
import subprocess
from datetime import datetime
from unittest.mock import Mock

from meet_recorder import transcriber

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

    assert markdown.startswith('---\ntitle: My Title\n---\n\n')
    assert 'the transcript text' in markdown


def test_summary_markdown_has_frontmatter_and_content():
    markdown = transcriber._summary_markdown('My Title', 'the summary text')

    assert markdown.startswith('---\ntitle: My Title\n---\n\n')
    assert 'the summary text' in markdown


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
