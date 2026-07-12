import main


def test_handler_functions_are_discovered_and_renamed():
    handlers_by_name = main.handlers_by_name

    assert 'record' in handlers_by_name
    assert 'recover' in handlers_by_name
    assert handlers_by_name['record'] is main.handlers.handler_record


def test_non_handler_module_members_are_excluded():
    handlers_by_name = main.handlers_by_name

    assert 'logger' not in handlers_by_name
    assert not any(name in handlers_by_name for name in ('recorder', 'transcriber', 'data'))
