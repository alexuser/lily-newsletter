#!/bin/bash
# Wrapper to run newsletter with proper virtual environment

VENV_DIR="$HOME/.openclaw/workspace/newsletter-venv"

# Load .env file if it exists
ENV_FILE="$HOME/.openclaw/workspace/.env"
if [ -f "$ENV_FILE" ]; then
    set -a
    source "$ENV_FILE"
    set +a
fi

source "$VENV_DIR/bin/activate"
python3 "$HOME/.openclaw/workspace/scripts/lily-daily-newsletter.py" "$@"
