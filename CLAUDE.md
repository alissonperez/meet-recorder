# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup and commands

- Setup (installs deps via Poetry): `make setup` or `poetry install`
- Lint: `make lint` (runs `ruff check .`)
- Clean env: `make clear`
- Run the CLI: `poetry run python main.py <command> [args...] [--verbose] [--dryrun]`
  - e.g. `poetry run python main.py quotation`
  - e.g. `poetry run python main.py read_csv --filename=sample.csv`
  - `--help` lists all available commands (`poetry run python main.py --help`)
- Requires Python 3.13.0 (see `.python-version`); a `.env` file (based on `.env.example`) must exist since `main.py` calls `load_dotenv()` before any handler runs.

- Test suite: `poetry run pytest` (tests live under `tests/`; `pytest` and
  `pytest-cov` are dev dependencies).

## Contribution checklist

- When a change modifies what dynamic context is sent alongside any of the
  three configurable prompts (transcription, summary, title), update
  `docs/prompts.md` in the same change so it stays in sync with actual
  behavior.

## Architecture

This is a small [python-fire](https://github.com/google/python-fire)-based CLI. The command surface is generated automatically, not registered by hand:

- `main.py` introspects `meet_recorder/handlers.py` for every module-level function whose name starts with `handler_`, strips that prefix, and hands the resulting `{name: func}` dict to `fire.Fire(...)`. So a new CLI subcommand is added by writing a new `handler_<name>` function in `handlers.py` — no other wiring is needed.
- `meet_recorder/tools.py` defines the `@handler` decorator used on handler functions (see `handler_quotation` in `handlers.py`). It injects two implicit CLI flags, `verbose` and `dryrun`, into the function signature (only if not already present), and on invocation:
  - Calls `logger.setup(...)` to configure logging/colors based on `verbose`.
  - Logs a warning if `dryrun` is truthy.
  - Strips the injected `verbose`/`dryrun` values back out before calling the wrapped function, so undecorated handlers never need to accept them.
  - Runs the wrapped function via `asyncio.run(...)` if it's a coroutine function.
  - Not all handlers use `@handler` (e.g. `handler_read_csv` is plain), so `verbose`/`dryrun` support is opt-in per handler.
- `meet_recorder/data.py` holds side-effecting logic (HTTP calls, file I/O) kept separate from the handlers/CLI layer, e.g. `get_quotation` (calls `QUOTATION_API_ENDPOINT` from env) and `read_csv`.
- `meet_recorder/logger.py` builds a `logging.config.dictConfig` setup with a custom `CustomFormatter` that colorizes the `%(levelname)s` field per level; `meet_recorder/consolecolor.py` provides the underlying ANSI color helpers (`green`, `red`, `blue`, etc.) and a module-level `enabled` flag that turns coloring off globally when set to `False`.
- `icecream`'s `ic()` is used throughout for ad-hoc debug prints (e.g. at the top of handlers).
