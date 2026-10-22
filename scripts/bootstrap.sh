#!/usr/bin/env bash
# LCES bootstrap (macOS/Linux). Rebuilds .venv with Python 3.13.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

echo "== Local Content Engineering Studio bootstrap =="

if ! command -v uv >/dev/null 2>&1; then
    echo "uv is not installed. See https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
fi

uv python install 3.13

if [ -f .venv/pyvenv.cfg ] && ! grep -q "version_info = 3\.13" .venv/pyvenv.cfg; then
    echo "-- Existing .venv is not Python 3.13; removing it"
    rm -rf .venv
fi

uv sync

if [ ! -d .git ]; then
    git init -b main >/dev/null
    echo "-- git repository initialized"
fi

uv run lces doctor
uv run pytest
uv run ruff check .

echo
echo "Done. Activate later with: source .venv/bin/activate"
