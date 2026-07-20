import base64
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from html.parser import HTMLParser

import httpx
from openai import OpenAI
from slugify import slugify

from meet_recorder import calendar
from meet_recorder.config import load_config

logger = logging.getLogger(__name__)

AUDIO_SAMPLE_RATE = 16000
AUDIO_BITRATE = '32k'
TITLE_MAX_LENGTH = 60
TITLE_MAX_ATTEMPTS = 3
EVENT_DESCRIPTION_MAX_LENGTH = 500
FILENAME_TIMESTAMP_FORMAT = '%Y-%m-%d_%H-%M-%S'
MONTH_FORMAT = '%Y-%m'


class TranscriptionError(Exception):
    pass


def _api_key():
    api_key = os.environ.get('OPENROUTER_API_KEY')
    if not api_key:
        raise TranscriptionError('OPENROUTER_API_KEY is not set (add it to .env)')
    return api_key


def _run_ffmpeg(args):
    try:
        subprocess.run(['ffmpeg', *args], capture_output=True, check=True)
    except FileNotFoundError:
        raise TranscriptionError('ffmpeg binary not found on PATH; install ffmpeg to enable transcription')
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode(errors='replace') if e.stderr else ''
        raise TranscriptionError(f'ffmpeg failed: {stderr}')


def _get_audio_duration(path):
    try:
        result = subprocess.run(
            [
                'ffprobe', '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                path,
            ],
            capture_output=True, check=True, text=True,
        )
    except FileNotFoundError:
        raise TranscriptionError('ffprobe binary not found on PATH; install ffmpeg (includes ffprobe) to enable transcription')
    except subprocess.CalledProcessError as e:
        raise TranscriptionError(f'ffprobe failed: {e.stderr}')

    return float(result.stdout.strip())


def _preprocess_audio(wav_path):
    tmp_dir = tempfile.mkdtemp(prefix='meet-recorder-transcribe-')
    mp3_path = os.path.join(tmp_dir, 'audio.mp3')

    _run_ffmpeg(['-y', '-i', wav_path, '-ac', '1', '-ar', str(AUDIO_SAMPLE_RATE), '-b:a', AUDIO_BITRATE, mp3_path])

    return mp3_path


def _split_into_chunks(mp3_path, chunk_duration):
    duration = _get_audio_duration(mp3_path)

    if duration <= chunk_duration:
        return [mp3_path]

    chunk_dir = os.path.dirname(mp3_path)
    chunks = []
    offset = 0.0
    index = 0

    while offset < duration:
        chunk_path = os.path.join(chunk_dir, f'chunk_{index:03d}.mp3')
        _run_ffmpeg(['-y', '-ss', str(offset), '-t', str(chunk_duration), '-i', mp3_path, '-c', 'copy', chunk_path])
        chunks.append(chunk_path)
        offset += chunk_duration
        index += 1

    return chunks


def _transcribe_chunk(chunk_path, config, event=None):
    with open(chunk_path, 'rb') as f:
        audio_b64 = base64.b64encode(f.read()).decode('ascii')

    payload = {
        'model': config.transcription_model,
        'input_audio': {'data': audio_b64, 'format': 'mp3'},
        'language': 'pt',
    }

    prompt = config.transcription_prompt or ''
    if event is not None:
        prompt = _event_context(event) + prompt
    if prompt:
        payload['prompt'] = prompt

    url = f'{config.base_url.rstrip("/")}/audio/transcriptions'
    headers = {'Authorization': f'Bearer {_api_key()}', 'Content-Type': 'application/json'}

    try:
        response = httpx.post(url, json=payload, headers=headers, timeout=120)
        response.raise_for_status()
    except httpx.HTTPError as e:
        raise TranscriptionError(f'Transcription request failed: {e}')

    return response.json().get('text', '')


def _transcribe_audio(mp3_path, config, event=None):
    chunks = _split_into_chunks(mp3_path, config.chunk_duration)
    texts = [_transcribe_chunk(chunk, config, event) for chunk in chunks]

    return '\n'.join(texts)


def _chat_completion(model, system_prompt, user_content, config):
    client = OpenAI(base_url=config.base_url, api_key=_api_key())

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_content},
            ],
        )
    except Exception as e:
        raise TranscriptionError(f'Chat completion request failed: {e}')

    return response.choices[0].message.content.strip()


def _generate_title(summary_text, config):
    prompt = config.title_prompt
    title = ''

    for attempt in range(TITLE_MAX_ATTEMPTS):
        if attempt > 0:
            prompt = f'{config.title_prompt}\n\nO título anterior excedeu {TITLE_MAX_LENGTH} caracteres. Gere um título mais curto.'

        title = _chat_completion(config.title_model, prompt, summary_text, config)

        if len(title) <= TITLE_MAX_LENGTH:
            return title

    logger.warning(f'Title exceeded {TITLE_MAX_LENGTH} chars after {TITLE_MAX_ATTEMPTS} attempts, truncating')
    return title[:TITLE_MAX_LENGTH]


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._chunks = []

    def handle_data(self, data):
        self._chunks.append(data)

    def text(self):
        return ''.join(self._chunks)


def _strip_html(text):
    parser = _HTMLTextExtractor()
    parser.feed(text)
    return parser.text()


def _clean_event_description(description):
    text = _strip_html(description)
    text = re.sub(r'\n\s*\n+', '\n', text).strip()
    if len(text) > EVENT_DESCRIPTION_MAX_LENGTH:
        text = text[:EVENT_DESCRIPTION_MAX_LENGTH].rstrip() + '…'
    return text


def _event_context(event):
    lines = [f'Título da reunião: {event.title}']
    description = getattr(event, 'description', None)
    if description:
        cleaned = _clean_event_description(description)
        if cleaned:
            lines.append(f'Descrição: {cleaned}')
    if event.attendees:
        lines.append('Participantes: ' + ', '.join(event.attendees))
    return '\n'.join(lines) + '\n\n'


def _gemini_context(gemini_text):
    return f'Notas do Gemini (contexto adicional):\n{gemini_text}\n\n'


def _generate_summary(transcript_text, config, event=None, summary_prompt=None, gemini_context=None):
    prompt = summary_prompt if summary_prompt is not None else config.summary_prompt

    user_content = transcript_text
    if gemini_context:
        user_content = _gemini_context(gemini_context) + user_content
    if event is not None:
        user_content = _event_context(event) + user_content

    return _chat_completion(config.summary_model, prompt, user_content, config)


def _resolve_timestamp(wav_path):
    stem = os.path.splitext(os.path.basename(wav_path))[0]

    try:
        return datetime.strptime(stem, FILENAME_TIMESTAMP_FORMAT)
    except ValueError:
        return datetime.fromtimestamp(os.path.getmtime(wav_path))


def _format_display_timestamp(timestamp):
    return timestamp.astimezone().replace(microsecond=0).isoformat().replace(':', '-')


def _build_base_filename(timestamp, title, suffix=None):
    ts_str = _format_display_timestamp(timestamp)
    title_slug = slugify(title, lowercase=False)[:80]
    suffix_str = f' {suffix}' if suffix else ''

    return f'{ts_str}{suffix_str} - {title_slug}'


def _write_markdown(base_dir, timestamp, base_filename, content):
    month_dir = os.path.join(base_dir, timestamp.strftime(MONTH_FORMAT))
    os.makedirs(month_dir, exist_ok=True)

    path = os.path.join(month_dir, f'{base_filename}.md')
    with open(path, 'w') as f:
        f.write(content)

    return path


def _yaml_str(value):
    # JSON string escaping is a subset of YAML double-quoted scalars, so this keeps
    # frontmatter valid for values with colons, quotes, etc. ensure_ascii=False
    # preserves accented characters common in Portuguese titles/names.
    return json.dumps(value, ensure_ascii=False)


def _frontmatter(title, event):
    lines = [f'title: {_yaml_str(title)}']

    if event is not None:
        lines.append(f'calendar: {_yaml_str(event.calendar)}')
        if event.start_raw:
            lines.append(f'event_start: {_yaml_str(event.start_raw)}')
        if event.end_raw:
            lines.append(f'event_end: {_yaml_str(event.end_raw)}')
        if event.attendees:
            lines.append('attendees:')
            lines.extend(f'  - {_yaml_str(name)}' for name in event.attendees)

    return '---\n' + '\n'.join(lines) + '\n---'


def _transcript_markdown(title, transcript_text, event=None):
    return f'{_frontmatter(title, event)}\n\n{transcript_text}\n'


def _summary_markdown(title, summary_text, event=None):
    return f'{_frontmatter(title, event)}\n\n{summary_text}\n'


async def transcribe(wav_path, config=None):
    if config is None:
        config = load_config()

    timestamp = _resolve_timestamp(wav_path)
    event = calendar.find_event(timestamp, config)
    tmp_dir = None

    try:
        mp3_path = _preprocess_audio(wav_path)
        tmp_dir = os.path.dirname(mp3_path)

        transcript_text = _transcribe_audio(mp3_path, config, event)
        summary_text = _generate_summary(transcript_text, config, event)
        title = event.title if event is not None else _generate_title(summary_text, config)

        transcript_path = _write_markdown(
            config.transcript_dir, timestamp, _build_base_filename(timestamp, title),
            _transcript_markdown(title, transcript_text, event),
        )
        summary_path = _write_markdown(
            config.summary_dir, timestamp, _build_base_filename(timestamp, title, suffix='RESUMO'),
            _summary_markdown(title, summary_text, event),
        )

        return {'transcript_path': transcript_path, 'summary_path': summary_path}
    finally:
        if tmp_dir and os.path.isdir(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)


def write_meet_output(event, transcript_text, config, gemini_context=None):
    '''Write transcript + summary files from ready (Meet-sourced) transcript text.

    Reuses the recording pipeline's summary/output layer: the summary is generated with the
    speaker-aware `meet_summary_prompt` (fed the Gemini notes as extra context when present),
    the title is the calendar event title, and the timestamp is the occurrence start time.
    Existing files at the target paths are overwritten by design.'''
    logger.info(
        f'"{event.title}": generating Meet summary with {config.summary_model} '
        f'({len(transcript_text)} transcript chars, '
        f'gemini context: {"yes" if gemini_context else "no"})'
    )
    summary_text = _generate_summary(
        transcript_text, config, event=event,
        summary_prompt=config.meet_summary_prompt, gemini_context=gemini_context,
    )
    title = event.title
    timestamp = event.start_dt

    transcript_path = _write_markdown(
        config.transcript_dir, timestamp, _build_base_filename(timestamp, title),
        _transcript_markdown(title, transcript_text, event),
    )
    logger.debug(f'"{event.title}": wrote Meet transcript -> {transcript_path}')

    summary_path = _write_markdown(
        config.summary_dir, timestamp, _build_base_filename(timestamp, title, suffix='RESUMO'),
        _summary_markdown(title, summary_text, event),
    )
    logger.debug(f'"{event.title}": wrote Meet summary -> {summary_path}')

    return {'transcript_path': transcript_path, 'summary_path': summary_path}
