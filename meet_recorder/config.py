import os

import yaml
from slugify import slugify

CONFIG_PATH = '~/.config/meet-recorder/config.yaml'
CONFIG_DIR = '~/.config/meet-recorder'

DEFAULT_BASE_URL = 'https://openrouter.ai/api/v1'
DEFAULT_CHUNK_DURATION_SECONDS = 7 * 60

DEFAULT_MATCH_BEFORE_MINUTES = 60
DEFAULT_MATCH_AFTER_MINUTES = 15
DEFAULT_MAX_ATTENDEES = 20

DEFAULT_AUTORECORD_CALENDAR_POLL_INTERVAL_MINUTES = 5
DEFAULT_AUTORECORD_NOTIFY_BEFORE_MINUTES = 5
DEFAULT_AUTORECORD_CHECK_INTERVAL_SECONDS = 60
DEFAULT_AUTORECORD_MAX_MEETING_AGE_MINUTES = 20

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


class AutoRecordConfig:
    def __init__(self, data):
        data = data or {}
        self.enabled = bool(data.get('enabled', False))
        self.calendar_poll_interval_minutes = max(1, int(
            data.get('calendar_poll_interval_minutes', DEFAULT_AUTORECORD_CALENDAR_POLL_INTERVAL_MINUTES)
        ))
        self.notify_before_minutes = int(
            data.get('notify_before_minutes', DEFAULT_AUTORECORD_NOTIFY_BEFORE_MINUTES)
        )
        self.check_interval_seconds = max(1, int(
            data.get('check_interval_seconds', DEFAULT_AUTORECORD_CHECK_INTERVAL_SECONDS)
        ))
        self.max_meeting_age_minutes = max(0, int(
            data.get('max_meeting_age_minutes', DEFAULT_AUTORECORD_MAX_MEETING_AGE_MINUTES)
        ))


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

        # Optional, additive Google Calendar section. Absent -> feature disabled.
        self.calendars = [c['name'] for c in (data.get('calendars') or [])]
        self.calendar_match_before_minutes = int(
            data.get('calendar_match_before_minutes', DEFAULT_MATCH_BEFORE_MINUTES)
        )
        self.calendar_match_after_minutes = int(
            data.get('calendar_match_after_minutes', DEFAULT_MATCH_AFTER_MINUTES)
        )
        self.ignored_event_slugs = [slugify(i) for i in list(data.get('ignored_event_slugs') or [])]
        self.max_attendees = int(data.get('calendar_max_attendees', DEFAULT_MAX_ATTENDEES))
        self.autorecord = AutoRecordConfig(data.get('autorecord'))

    @property
    def calendar_enabled(self):
        return bool(self.calendars)


def config_dir():
    return os.path.expanduser(CONFIG_DIR)


def credentials_path(account):
    return os.path.join(config_dir(), 'credentials', f'{account}.json')


def token_path(account):
    return os.path.join(config_dir(), 'tokens', f'{account}.json')


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
