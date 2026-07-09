import inspect
import logging
import asyncio


from meet_recorder import consolecolor as ccolor, logger as i_logger


params_to_add = {
    'verbose': inspect.Parameter('verbose', inspect.Parameter.POSITIONAL_OR_KEYWORD, default=False),
    'dryrun': inspect.Parameter('dryrun', inspect.Parameter.POSITIONAL_OR_KEYWORD, default=False),
}


def _param_or_default(name, params, args, kwargs):
    if name in kwargs:
        return kwargs[name]

    # Check by position...
    if name in params:
        pos = list(params.keys()).index(name)
        if pos < len(args):
            return args[pos]

    return params[name].default


def handler(func):
    original_signature = inspect.signature(func)
    original_params = dict(original_signature.parameters)

    new_params = dict(original_signature.parameters)

    keys_added = set()

    for param_name, param in params_to_add.items():
        if param_name not in original_signature.parameters:
            keys_added.add(param_name)
            new_params[param_name] = param

    def wrapper(*args, **kwargs):
        # Setup logger
        verbose = _param_or_default('verbose', new_params, args, kwargs)
        i_logger.setup(ccolor.enabled, verbose)

        dryrun = _param_or_default('dryrun', new_params, args, kwargs)

        if dryrun:
            logger = logging.getLogger(__name__)
            logger.warn('Running in DRYRUN mode (if implemented as expected, right?!...)')

        kwargs = _clean_kwargs(kwargs, keys_added)
        args = _clean_args(args, original_params)

        if asyncio.iscoroutinefunction(func):
            return asyncio.run(func(*args, **kwargs))

        return func(*args, **kwargs)

    wrapper.__signature__ = original_signature.replace(parameters=list(new_params.values()))

    return wrapper


def _clean_kwargs(kwargs, keys_added):
    return {k: v for k, v in kwargs.items() if k not in keys_added}


def _clean_args(args, params):
    # Remove the last elements from args that were added to the signature
    return tuple([v for k, v in enumerate(args) if k < len(params)])
