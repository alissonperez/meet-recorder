import os

import yaml

CONFIG_PATH = '~/.config/meet-recorder/config.yaml'

DEFAULT_BASE_URL = 'https://openrouter.ai/api/v1'
DEFAULT_CHUNK_DURATION_SECONDS = 7 * 60

REQUIRED_FIELDS = (
    'transcription_model',
    'summary_model',
    'title_model',
    'transcription_prompt',
    'summary_prompt',
    'title_prompt',
    'transcript_dir',
    'summary_dir',
)


class ConfigError(Exception):
    pass


class Config:
    def __init__(self, data):
        self.transcription_model = data['transcription_model']
        self.summary_model = data['summary_model']
        self.title_model = data['title_model']
        self.transcription_prompt = data['transcription_prompt']
        self.summary_prompt = data['summary_prompt']
        self.title_prompt = data['title_prompt']
        self.transcript_dir = os.path.expanduser(data['transcript_dir'])
        self.summary_dir = os.path.expanduser(data['summary_dir'])
        self.chunk_duration = int(data.get('chunk_duration', DEFAULT_CHUNK_DURATION_SECONDS))
        self.base_url = data.get('base_url', DEFAULT_BASE_URL)


def load_config(path=None):
    config_path = os.path.expanduser(path or CONFIG_PATH)

    if not os.path.isfile(config_path):
        raise ConfigError(f'Config file not found at {config_path}')

    with open(config_path, 'r') as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise ConfigError(f'Failed to parse config file at {config_path}: {e}')

    if not isinstance(data, dict):
        raise ConfigError(f'Config file at {config_path} must contain a YAML mapping')

    missing = [field for field in REQUIRED_FIELDS if field not in data]
    if missing:
        raise ConfigError(f'Config file at {config_path} is missing required fields: {", ".join(missing)}')

    return Config(data)
