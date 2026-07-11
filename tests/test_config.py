import os

import pytest

from meet_recorder.config import (
    DEFAULT_BASE_URL,
    DEFAULT_CHUNK_DURATION_SECONDS,
    ConfigError,
    load_config,
)

VALID_CONFIG = '''
transcription_model: whisper-1
summary_model: gpt-4
title_model: gpt-4
transcription_prompt: transcribe this
summary_prompt: summarize this
title_prompt: title this
transcript_dir: /tmp/transcripts
summary_dir: /tmp/summaries
'''


def test_load_config_missing_file(tmp_path):
    missing_path = tmp_path / 'does-not-exist.yaml'

    with pytest.raises(ConfigError, match=str(missing_path)):
        load_config(str(missing_path))


def test_load_config_invalid_yaml(tmp_path):
    config_path = tmp_path / 'config.yaml'
    config_path.write_text('transcription_model: [unterminated')

    with pytest.raises(ConfigError):
        load_config(str(config_path))


def test_load_config_missing_required_fields(tmp_path):
    config_path = tmp_path / 'config.yaml'
    config_path.write_text('transcription_model: whisper-1\nsummary_model: gpt-4\n')

    with pytest.raises(ConfigError) as exc_info:
        load_config(str(config_path))

    message = str(exc_info.value)
    assert 'title_model' in message
    assert 'transcript_dir' in message


def test_load_config_applies_defaults(tmp_path):
    config_path = tmp_path / 'config.yaml'
    config_path.write_text(VALID_CONFIG)

    config = load_config(str(config_path))

    assert config.chunk_duration == DEFAULT_CHUNK_DURATION_SECONDS
    assert config.base_url == DEFAULT_BASE_URL


def test_load_config_expands_home_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))

    config_path = tmp_path / 'config.yaml'
    config_path.write_text(VALID_CONFIG.replace(
        'transcript_dir: /tmp/transcripts', 'transcript_dir: ~/transcripts',
    ).replace(
        'summary_dir: /tmp/summaries', 'summary_dir: ~/summaries',
    ))

    config = load_config(str(config_path))

    assert config.transcript_dir == os.path.join(str(tmp_path), 'transcripts')
    assert config.summary_dir == os.path.join(str(tmp_path), 'summaries')
