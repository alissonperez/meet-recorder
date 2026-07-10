## Why

The menu bar app (`menubar-app` capability) must be started manually from a terminal every time, as documented in the README ("must be started manually each time — it does not launch at login"). This is friction for a tool meant to be always available before a meeting starts. macOS `launchd` can start it automatically at login, following the same LaunchAgent pattern already used by another local project (`obs-transcript`).

## What Changes

- Add a `launchd` LaunchAgent (`com.alisson.meet-recorder.plist`) and a `run.sh` wrapper script to the repo, adapted from the `exemplo.plist` / `exemplo-run.sh` reference files already present in the project.
- The agent uses `RunAtLoad=true` (start at login) and `KeepAlive=true` (relaunch if the process exits), unlike the reference example which is a periodic `StartInterval` job — the menu bar app is a long-running process, not a one-shot job.
- `run.sh` changes into the project directory before invoking the poetry venv's Python directly, so `load_dotenv()` in `main.py` can find `.env`.
- stdout/stderr are redirected to log files via the plist's `StandardOutPath`/`StandardErrorPath`.
- `meet_recorder/consolecolor.py`'s `enabled` flag switches from hardcoded `True` to `sys.stdout.isatty()`, so ANSI color codes only appear when running interactively in a terminal, not when logging to a file under launchd.
- Add a new README section documenting the autostart setup: where the plist/run.sh live, how to install/uninstall via `launchctl`, how to find the poetry venv Python path, and how to check logs.

## Capabilities

### New Capabilities
- `menubar-autostart`: macOS login-time autostart of the menu bar app via a launchd LaunchAgent, including the wrapper script, logging-to-file behavior, and setup/teardown documentation.

### Modified Capabilities
(none — the color-output change is an implementation detail of `menubar-autostart`'s logging behavior, not a change to an existing capability's documented requirements)

## Impact

- New files: `com.alisson.meet-recorder.plist`, `run.sh` (or similar names, at repo root alongside the `exemplo.*` references).
- Modified files: `meet_recorder/consolecolor.py` (one-line default change), `README.md` (new documentation section).
- No changes to `meet_recorder/menubar.py`, `main.py`, or the CLI surface — the app is launched exactly as `poetry run python main.py menubar` already works today, just via launchd instead of a manual terminal invocation.
- Depends on the poetry virtualenv already being created (`poetry install`) and its path being known/documented, since the hashed venv path changes if the venv is recreated.
