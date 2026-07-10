## Context

The menu bar app (`meet_recorder/menubar.py`) is invoked today as `poetry run python main.py menubar` from a terminal. `main.py` calls `load_dotenv()` (no explicit path) before `fire.Fire(...)` dispatches to the handler, so it relies on the process's current working directory being the project root for `.env` to be found. Logging goes through `meet_recorder/logger.py`, configured via `tools.py`'s `handler` decorator, which always colorizes output because `meet_recorder/consolecolor.py` hardcodes `enabled = True`.

The project already has a working reference for launchd-based autostart from a sibling project (`obs-transcript`), captured locally as `exemplo.plist` / `exemplo-run.sh`. That reference is a periodic job (`StartInterval`), not a persistent GUI process, so its pattern needs adaptation rather than a direct copy.

## Goals / Non-Goals

**Goals:**
- Menu bar app process starts automatically at user login, without a terminal.
- If the process exits (crash, killed), launchd relaunches it.
- Logs from the launchd-managed process are readable (no raw ANSI escape codes) when viewed in a plain file.
- Manual `poetry run python main.py menubar` from a terminal continues to work exactly as before, with colored output.
- Setup/teardown is documented so it's reproducible after a venv rebuild or on a fresh machine.

**Non-Goals:**
- Auto-starting a *recording* on login — only the app/menu bar icon starts; the user still clicks "Iniciar".
- Packaging as a `.app` bundle (py2app) or distributing outside this machine.
- Making the venv path resolution automatic/dynamic (it's a documented manual step when the venv is recreated).
- Handling macOS TCC microphone-permission prompts programmatically — this is called out as a manual first-run check in the docs.

## Decisions

**LaunchAgent (`~/Library/LaunchAgents`) over LaunchDaemon.** The menu bar app is a per-user GUI process (rumps status bar item); LaunchDaemons run outside the user's GUI session and can't show UI. LaunchAgents installed under the user's `~/Library/LaunchAgents` are loaded in the user's login session automatically.

**`RunAtLoad=true` + `KeepAlive=true`, no `StartInterval`.** The reference `exemplo.plist` uses `StartInterval=300` because it's a periodic batch job (transcribe whatever's new every 5 minutes). The menu bar app is a long-lived process — it should start once at login and stay running, so `RunAtLoad` handles the start and `KeepAlive` handles unexpected exits. Using `StartInterval` on a persistent process would spawn a second app instance every interval.

**`run.sh` wrapper invoking the venv's Python directly, run from the project directory.** Matches the reference pattern (`VENV_PYTHON="/path/to/venv/bin/python"`) rather than shelling out to `poetry run`, since launchd's minimal environment doesn't reliably have `poetry` on `PATH` even with the `EnvironmentVariables` PATH override. The script `cd`s into the project directory first (the reference script doesn't need this since `transcribe.py` takes explicit I/O paths as arguments, but `main.py`'s `load_dotenv()` needs the working directory to be the project root to find `.env`).

**Color output gated on `sys.stdout.isatty()` instead of a new CLI flag.** `StandardOutPath` in the plist redirects launchd's stdout to a regular file, so `sys.stdout.isatty()` is naturally `False` in that context and `True` in an interactive terminal. This reuses the existing `ccolor.enabled` switch point (already read by `logger.setup` in `tools.py`) with no new flag, no launchd-specific branching, and no risk of the manual/terminal path regressing.

**Logs to files via `StandardOutPath`/`StandardErrorPath`, not a rotating log system.** Matches the existing reference pattern (`/tmp/com.alisson.<label>.out/.err`). No log rotation is introduced — this is a personal single-machine tool and `/tmp` logs are acceptable to grow/reset; rotation can be revisited if it becomes a problem.

## Risks / Trade-offs

- **[Risk]** Poetry venv path is hashed (e.g. `meet-recorder-RBBEOZkh-py3.13`) and changes if the venv is deleted/recreated → `run.sh` would silently point at a missing binary. **Mitigation**: document `poetry env info --path` as the way to refresh it; call it out explicitly in the README section.
- **[Risk]** First launch via launchd may trigger a new macOS microphone/screen-recording permission prompt distinct from the one already granted to terminal-launched Python, since TCC grants can be tied to the invoking process context. **Mitigation**: document this as an expected one-time manual step after first install; not automatable.
- **[Risk]** `KeepAlive=true` will relaunch the app in a tight loop if it crashes immediately on every start (e.g. missing `.env`, bad venv path), masking the root cause behind repeated restarts. **Mitigation**: document checking `StandardErrorPath` log first when the menu bar icon doesn't appear; note that `launchctl` can be used to unload the agent while debugging.
- **[Trade-off]** No log rotation/size cap on the launchd output files, consistent with the existing reference pattern's simplicity; acceptable for a personal tool but would need revisiting before wider use.

## Migration Plan

1. Add `run.sh` and the `.plist` to the repo (not yet installed to `~/Library/LaunchAgents`).
2. Apply the `consolecolor.py` isatty change; verify manual `poetry run python main.py menubar` still shows colored logs in a terminal.
3. Document install steps in the README (copy/symlink plist to `~/Library/LaunchAgents`, `launchctl bootstrap`/`load`).
4. Manual verification: log out/in (or `launchctl kickstart`) and confirm the menu bar icon appears, logs are written without ANSI codes, and killing the process causes launchd to relaunch it.
5. Rollback: `launchctl bootout`/`unload` the agent and remove the plist from `~/Library/LaunchAgents` — no code rollback needed since the CLI entrypoint is unchanged.

## Open Questions

- Exact log file location: `/tmp` (matching the reference) vs. a path inside the project or `~/Library/Logs`. Defaulting to `/tmp/com.alisson.meet-recorder.out`/`.err` to match the existing convention, but this can be adjusted in review.
