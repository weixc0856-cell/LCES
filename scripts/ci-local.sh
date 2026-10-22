#!/usr/bin/env bash
# Local mirror of the CI gates. Run before pushing.
#
#   ./scripts/ci-local.sh fast     # ruff, format, mypy, pytest (any OS)
#   ./scripts/ci-local.sh render   # Linux/WSL: Node contract + real render/encode/Gate 4
#   ./scripts/ci-local.sh full     # fast + render + browser QA
#
# The commands are the same ones the GitHub workflows run. This script never
# installs anything: missing tools stop it with the exact command to run.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODE="${1:-fast}"
EXPECTED_NODE="v24.22.1"

die() { printf 'error: %s\n' "$*" >&2; exit 2; }
note() { printf '\n==> %s\n' "$*"; }

usage() {
  cat <<'USAGE'
usage: ./scripts/ci-local.sh [fast|render|full]

  fast    ruff check, ruff format --check, mypy, pytest (no browser)
  render  Linux/WSL only: Node contract suite, real renders, encode, Gate 4
  full    fast + render + browser QA (needs the browser extra)
USAGE
}

require_uv() {
  command -v uv >/dev/null 2>&1 || die "uv is not installed"
}

require_linux() {
  [ "$(uname -s)" = "Linux" ] || die "render/full are Linux-only; run this in WSL2"
}

require_node() {
  command -v node >/dev/null 2>&1 || die "node is not installed; install Node $EXPECTED_NODE"
  local version
  version="$(node --version)"
  [ "$version" = "$EXPECTED_NODE" ] || die \
    "node $version found; Motion Canvas is pinned to $EXPECTED_NODE (do not lower the gate)"
}

require_motion_deps() {
  [ -d motion/node_modules ] || die "run: (cd motion && npm ci && npm rebuild esbuild)"
}

require_chromium() {
  local path
  path="$(
    cd motion
    node -e "const {chromium} = require('playwright'); process.stdout.write(chromium.executablePath())" \
      2>/dev/null || true
  )"
  if [ -z "$path" ] || [ ! -f "$path" ]; then
    die "Playwright Chromium is missing for motion/ (Playwright 1.64.0)"
  fi
}

require_ffmpeg() {
  command -v ffmpeg >/dev/null 2>&1 && command -v ffprobe >/dev/null 2>&1 \
    || die "ffmpeg and ffprobe are required"
}

fast() {
  require_uv
  note "lint, format, types (CI test job)"
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy src
  note "pytest (CI test job; motion tests skip without LCES_MC_E2E)"
  uv run pytest
}

render() {
  require_uv
  require_linux
  require_node
  require_motion_deps
  require_chromium
  require_ffmpeg
  mkdir -p var/ci-local
  note "Node contract suite (CI motion job)"
  (cd motion && node --test --test-reporter=tap contract.test.mjs)
  note "real renders, encoding and Gate 4 (CI motion job)"
  LCES_MC_E2E=1 uv run pytest -m motion -v --basetemp=var/ci-local/pytest
}

full() {
  fast
  render
  note "browser QA dependencies"
  uv run --extra browser python -c "import playwright" >/dev/null 2>&1 \
    || die "Python Playwright is missing; run: uv sync --extra browser"
  uv run --extra browser python - <<'PY' || die "Python Playwright Chromium cannot launch"
from playwright.sync_api import sync_playwright
with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    browser.close()
PY
  note "browser QA"
  uv run --extra browser pytest tests/test_browser_qa.py
}

case "$MODE" in
  fast) fast ;;
  render) render ;;
  full) full ;;
  -h | --help | help) usage ;;
  *) usage; exit 2 ;;
esac
