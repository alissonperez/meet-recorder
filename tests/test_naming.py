import os

from meet_recorder import naming

START_TIMESTAMP = '2026-03-04_11-05-00'


def _recording(tmp_path, name=f'{START_TIMESTAMP}.wav', contents=b'recorded-audio'):
    path = tmp_path / name
    path.write_bytes(contents)
    return path


def test_slugify_title_slugifies_preserving_case():
    assert naming.slugify_title('Weekly Planning') == 'Weekly-Planning'


def test_slugify_title_truncates_to_the_cap():
    slug = naming.slugify_title('Very Long Meeting Title ' * 10)

    assert len(slug) == naming.TITLE_SLUG_MAX_LENGTH


def test_slugify_title_strips_path_unsafe_characters():
    slug = naming.slugify_title('Q3/Q4 Review: "Roadmap" Sync')

    for unsafe in ('/', ':', '"', '\\'):
        assert unsafe not in slug
    assert slug == 'Q3-Q4-Review-Roadmap-Sync'


def test_slugify_title_returns_empty_string_for_punctuation_only_title():
    assert naming.slugify_title('!!! ... ???') == ''


def test_slugify_title_returns_empty_string_for_missing_title():
    assert naming.slugify_title('') == ''
    assert naming.slugify_title(None) == ''


def test_timestamp_prefix_reads_a_bare_timestamp_stem():
    assert naming.timestamp_prefix(f'/recordings/{START_TIMESTAMP}.wav') == START_TIMESTAMP


def test_timestamp_prefix_reads_a_titled_stem():
    path = f'/recordings/{START_TIMESTAMP} - Weekly-Planning.wav'

    assert naming.timestamp_prefix(path) == START_TIMESTAMP


def test_timestamp_prefix_is_none_for_an_unparseable_stem():
    assert naming.timestamp_prefix('/recordings/meeting-audio.wav') is None


def test_rename_recording_with_title_renames_in_place(tmp_path):
    path = _recording(tmp_path)

    result = naming.rename_recording_with_title(str(path), 'Weekly Planning')

    assert os.path.basename(result) == f'{START_TIMESTAMP} - Weekly-Planning.wav'
    assert os.path.dirname(result) == str(tmp_path)
    assert open(result, 'rb').read() == b'recorded-audio'
    assert not os.path.exists(path)


def test_rename_recording_with_title_is_a_noop_when_the_name_is_already_right(tmp_path):
    path = _recording(tmp_path, name=f'{START_TIMESTAMP} - Weekly-Planning.wav')

    result = naming.rename_recording_with_title(str(path), 'Weekly Planning')

    assert result == str(path)
    assert open(result, 'rb').read() == b'recorded-audio'


def test_rename_recording_with_title_replaces_a_different_title(tmp_path):
    path = _recording(tmp_path, name=f'{START_TIMESTAMP} - Old-Title.wav')

    result = naming.rename_recording_with_title(str(path), 'New Title')

    assert os.path.basename(result) == f'{START_TIMESTAMP} - New-Title.wav'
    assert open(result, 'rb').read() == b'recorded-audio'
    assert not os.path.exists(path)


def test_rename_recording_with_title_keeps_the_name_for_an_empty_slug(tmp_path):
    path = _recording(tmp_path)

    result = naming.rename_recording_with_title(str(path), '!!! ???')

    assert result == str(path)
    assert open(result, 'rb').read() == b'recorded-audio'


def test_rename_recording_with_title_keeps_the_name_without_a_timestamp_prefix(tmp_path):
    # Renaming would have to invent a start time the system does not know.
    path = _recording(tmp_path, name='meeting-audio.wav')

    result = naming.rename_recording_with_title(str(path), 'Weekly Planning')

    assert result == str(path)
    assert open(result, 'rb').read() == b'recorded-audio'


def test_rename_recording_with_title_does_not_overwrite_an_existing_destination(tmp_path):
    path = _recording(tmp_path)
    existing = tmp_path / f'{START_TIMESTAMP} - Weekly-Planning.wav'
    existing.write_bytes(b'someone-elses-recording')

    result = naming.rename_recording_with_title(str(path), 'Weekly Planning')

    assert result == str(path)
    assert open(result, 'rb').read() == b'recorded-audio'
    assert existing.read_bytes() == b'someone-elses-recording'


def test_rename_recording_with_title_absorbs_a_rename_failure(tmp_path, monkeypatch):
    path = _recording(tmp_path)

    def boom(src, dst):
        raise OSError('rename failed')

    monkeypatch.setattr(naming.os, 'rename', boom)

    result = naming.rename_recording_with_title(str(path), 'Weekly Planning')

    assert result == str(path)
    assert open(result, 'rb').read() == b'recorded-audio'


def test_rename_recording_with_title_bounds_overlong_and_unsafe_titles(tmp_path):
    path = _recording(tmp_path)

    result = naming.rename_recording_with_title(
        str(path), 'Q3/Q4 "Roadmap": ' + 'Planning ' * 20,
    )

    title_part = os.path.basename(result)[len(f'{START_TIMESTAMP} - '):-len('.wav')]
    assert len(title_part) == naming.TITLE_SLUG_MAX_LENGTH
    for unsafe in ('/', ':', '"', os.sep):
        assert unsafe not in title_part
    assert os.path.dirname(result) == str(tmp_path)
    assert os.path.isfile(result)
