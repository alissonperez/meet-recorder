## 1. Color output fix (prerequisite for readable logs)

- [x] 1.1 In `meet_recorder/consolecolor.py`, change `enabled = True` to `enabled = sys.stdout.isatty()` (add `import sys`)
- [x] 1.2 Manually verify `poetry run python main.py menubar` still shows colored log output in an interactive terminal
- [x] 1.3 Manually verify output is plain (no ANSI codes) when stdout is redirected to a file, e.g. `poetry run python main.py quotation > /tmp/test.out; cat /tmp/test.out`

## 2. LaunchAgent wrapper script

- [x] 2.1 Create `run.sh` at the repo root (or a dedicated `scripts/` location — match `exemplo-run.sh`'s style), adapted from `exemplo-run.sh`:
  - Set `PROJECT_DIR` to the absolute repo path
  - Set `VENV_PYTHON` to the poetry venv's Python (discoverable via `poetry env info --path`)
  - `cd "$PROJECT_DIR"` before invoking Python, so `load_dotenv()` finds `.env`
  - Invoke `"$VENV_PYTHON" main.py menubar`
- [x] 2.2 `chmod +x run.sh`
- [x] 2.3 Manually run `./run.sh` directly (not via launchd) and confirm the menu bar icon appears and `.env`-dependent behavior works

## 3. LaunchAgent plist

- [x] 3.1 Create `com.alisson.meet-recorder.plist` at the repo root, adapted from `exemplo.plist`:
  - `Label`: `com.alisson.meet-recorder`
  - `ProgramArguments`: path to `run.sh`
  - `RunAtLoad`: `true`
  - `KeepAlive`: `true`
  - `EnvironmentVariables`: `PATH`/`HOME` matching the reference
  - `StandardOutPath`/`StandardErrorPath`: `/tmp/com.alisson.meet-recorder.out` / `.err`
  - No `StartInterval` (persistent process, not a periodic job)
- [x] 3.2 Validate the plist is well-formed: `plutil -lint com.alisson.meet-recorder.plist`

## 4. Install and verify end-to-end

- [x] 4.1 Copy or symlink the plist into `~/Library/LaunchAgents/`
- [x] 4.2 Load it: `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.alisson.meet-recorder.plist` (or `launchctl load`)
- [x] 4.3 Confirm the menu bar icon appears without manually running any command
- [x] 4.4 Inspect `/tmp/com.alisson.meet-recorder.out`/`.err` and confirm log lines are present and free of ANSI escape codes
- [x] 4.5 Kill the running process (`kill` its PID) and confirm launchd relaunches it (icon reappears)
- [x] 4.6 Log out and back in (or `launchctl kickstart -k gui/$(id -u)/com.alisson.meet-recorder`) and confirm the app starts automatically
- [x] 4.7 Check whether a new microphone/screen-recording permission prompt appears on first launchd-triggered start; note the outcome in the README if relevant

## 5. Documentation

- [x] 5.1 Add a new README section (after "Menu bar app") documenting:
  - What `run.sh`/`com.alisson.meet-recorder.plist` are and where they live
  - How to find/update the poetry venv Python path (`poetry env info --path`), including what to do after recreating the venv
  - Install steps (`launchctl bootstrap`/`load`)
  - How to check logs (`/tmp/com.alisson.meet-recorder.out`/`.err`)
  - Uninstall steps (`launchctl bootout`/`unload`, removing the plist from `~/Library/LaunchAgents`)
  - Note about the one-time microphone/screen-recording permission prompt possibly reappearing
