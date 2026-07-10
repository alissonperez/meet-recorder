#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/85750/wo/personal/meet-recorder"
VENV_PYTHON="/Users/85750/Library/Caches/pypoetry/virtualenvs/meet-recorder-RBBEOZkh-py3.13/bin/python"

export PATH="/opt/homebrew/bin:$PATH"

cd "$PROJECT_DIR"

"$VENV_PYTHON" main.py menubar
