## ADDED Requirements

### Requirement: Login-time autostart via launchd
The system SHALL provide a macOS LaunchAgent definition and wrapper script that starts the menu bar app automatically when the user logs in, without requiring a terminal to be opened.

#### Scenario: App starts automatically at login
- **WHEN** the user logs into macOS with the LaunchAgent installed and loaded
- **THEN** the menu bar icon appears in the idle state, without the user having to manually run any command

#### Scenario: App is not installed
- **WHEN** the LaunchAgent has not been installed/loaded
- **THEN** the menu bar app does not start automatically, and the existing manual `poetry run python main.py menubar` invocation continues to work unchanged

### Requirement: Automatic relaunch on unexpected exit
The system SHALL configure the LaunchAgent to relaunch the menu bar app process if it exits unexpectedly, so the icon remains available without manual intervention.

#### Scenario: Process crashes while running
- **WHEN** the menu bar app process terminates unexpectedly while the LaunchAgent is loaded
- **THEN** launchd starts a new instance of the process automatically

### Requirement: Non-interactive log output without color codes
The system SHALL emit log output without ANSI color escape codes when running non-interactively (i.e., when standard output is not a terminal), while preserving colored output when run manually in a terminal.

#### Scenario: Running under launchd with output redirected to a file
- **WHEN** the menu bar app is started by launchd with stdout/stderr redirected to log files
- **THEN** the log files contain plain text without ANSI escape sequences

#### Scenario: Running manually in a terminal
- **WHEN** the menu bar app is started manually via `poetry run python main.py menubar` in an interactive terminal
- **THEN** log output in the terminal retains the existing colorized formatting

### Requirement: Autostart setup documentation
The system SHALL document, in the project README, how to install, verify, inspect logs for, and uninstall the login-time autostart LaunchAgent.

#### Scenario: Following the documented install steps
- **WHEN** a developer follows the README's autostart section on a machine with the poetry environment already set up
- **THEN** they can locate the LaunchAgent plist and wrapper script, install and load the agent, find the correct poetry venv Python path, and confirm the app is running via logs

#### Scenario: Poetry venv is recreated
- **WHEN** the poetry virtualenv is deleted and recreated (changing its hashed path)
- **THEN** the README documents how to discover the new venv Python path and update the wrapper script accordingly

#### Scenario: Following the documented uninstall steps
- **WHEN** a developer follows the README's uninstall instructions
- **THEN** the LaunchAgent no longer starts the app automatically at login
