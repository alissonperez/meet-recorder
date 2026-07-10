#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/Users/85750/wo/personal/obs-transcript"
VENV_PYTHON="/Users/85750/Library/Caches/pypoetry/virtualenvs/test-obs-4RXoO38a-py3.12/bin/python"

# Diretórios de entrada e saída — ajuste conforme necessário
INPUT_DIR="/Users/85750/Movies/gravacoes/"
TRANSCRIPT_OUTPUT_DIR="/Users/85750/Dropbox/obsedian-vault/Second Brain/Reuniões/Transcrições/"
OUTPUT_DIR="/Users/85750/Dropbox/obsedian-vault/Second Brain/Reuniões/Resumos/"

export PATH="/opt/homebrew/bin:$PATH"

DEBUG_FLAG=""
if [[ "${1:-}" == "--debug" ]]; then
    DEBUG_FLAG="--debug"
fi

echo "Transcrevendo arquivos de $INPUT_DIR para $OUTPUT_DIR usando o script $PROJECT_DIR/transcribe.py - transcripts-dir $TRANSCRIPT_OUTPUT_DIR${DEBUG_FLAG:+ [debug]}"

"$VENV_PYTHON" "$PROJECT_DIR/transcribe.py" "$INPUT_DIR" "$OUTPUT_DIR" --transcripts-dir "$TRANSCRIPT_OUTPUT_DIR" $DEBUG_FLAG
