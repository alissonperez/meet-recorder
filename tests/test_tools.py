from meet_recorder.tools import handler


def test_verbose_and_dryrun_stripped_from_kwargs():
    received = {}

    @handler
    def func(a, b=None):
        received['a'] = a
        received['b'] = b

    func(1, b=2, verbose=True, dryrun=True)

    assert received == {'a': 1, 'b': 2}


def test_verbose_and_dryrun_stripped_positionally():
    received = {}

    @handler
    def func(a, b):
        received['args'] = (a, b)

    func(1, 2, True, True)

    assert received == {'args': (1, 2)}


def test_dryrun_logs_warning(capsys):
    @handler
    def func():
        pass

    func(dryrun=True)

    assert 'DRYRUN' in capsys.readouterr().out


def test_async_function_runs_via_asyncio_run():
    @handler
    async def func(a):
        return a * 2

    result = func(21)

    assert result == 42


def test_existing_verbose_dryrun_params_not_double_injected():
    received = {}

    @handler
    def func(verbose=False, dryrun=False):
        received['verbose'] = verbose
        received['dryrun'] = dryrun

    func(verbose=True, dryrun=True)

    assert received == {'verbose': True, 'dryrun': True}
