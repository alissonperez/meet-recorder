Meet Recorder
=============================================

## Requirements

- Python 3.13.0 (in [`.python-version`](./.python-version)): Recommended to use [pyenv](https://github.com/pyenv/pyenv) to manage your python versions.
- **Poetry**: See how to install poetry [here](https://python-poetry.org/docs/#installing-with-pipx).

## How to setup

```
$ make setup
```

To clean up all app env (removing pipenv env, for example):

```
$ make clear
```

## How to run

Fill a `.env` based on `.env.example` and then:

```
$ pipenv run python main.py --help
```

## How to lint

```
make lint
```

## Audio capture setup (BlackHole)

Recording captures both your microphone and the computer's system audio (e.g. the other
participants in a call) at the same time, using [BlackHole](https://existential.audio/blackhole/)
as a virtual audio driver. This requires a one-time system setup:

1. Install the required Homebrew packages:

   ```
   brew install blackhole-2ch switchaudio-osx
   ```

2. Restart Core Audio so the new virtual device appears:

   ```
   sudo killall -9 coreaudiod
   ```

3. Create a Multi-Output Device (one-time, manual):
   - Open **Audio MIDI Setup** (Spotlight → "Audio MIDI Setup").
   - Click `+` in the bottom-left corner → **Create Multi-Output Device**.
   - Check the boxes for your physical output (e.g. "MacBook Pro Speakers" or your headphones)
     and **"BlackHole 2ch"**.
   - Check **"Drift Correction"** next to BlackHole (reduces desync on longer recordings).
   - Rename the device to `Multi-Output (BlackHole)` (or set `MULTI_OUTPUT_DEVICE_NAME` in
     `.env` if you name it differently — see `.env.example`).

Once set up, `python main.py record` will automatically switch the system output to this
Multi-Output Device while recording, and restore your original output device when it stops.
