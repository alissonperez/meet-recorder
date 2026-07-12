#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export PATH="/opt/homebrew/bin:$HOME/.pyenv/shims:$PATH"

cd "$PROJECT_DIR"

exec poetry run python main.py menubar
