from meet_recorder import naming


def test_slugify_title_slugifies_preserving_case():
    assert naming.slugify_title('Weekly Planning') == 'Weekly-Planning'


def test_slugify_title_truncates_to_the_cap():
    title = 'Very Long Meeting Title ' * 10

    slug = naming.slugify_title(title)

    assert len(slug) == naming.TITLE_SLUG_MAX_LENGTH
    assert slug == naming.slugify_title(title)[:naming.TITLE_SLUG_MAX_LENGTH]


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
