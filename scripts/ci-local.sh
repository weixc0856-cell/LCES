#!/usr/bin/env bash
# Local mirror of the CI gates. Run before pushing.
#
#   ./scripts/ci-local.sh fast     # ruff, format, mypy, pytest (any OS)
#   ./scripts/ci-local.sh render   # Linux/WSL: Node contract + real render/encode/Gate 4
#   ./scripts/ci-local.sh offline  # Docker: build once, render with `--network none`
#   ./scripts/ci-local.sh full     # fast + render + offline + browser QA
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
usage: ./scripts/ci-local.sh [fast|render|offline|full]

  fast     ruff check, ruff format --check, mypy, pytest (no browser)
  render   Linux/WSL only: Node contract suite, real renders, encode, Gate 4
  offline  Docker only: build the pinned image, then render with --network none
  full     fast + render + offline + browser QA (needs the browser extra)
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

require_docker() {
  command -v docker >/dev/null 2>&1 || die "docker is not installed"
  docker info >/dev/null 2>&1 || die "the Docker daemon is not reachable"
}

require_lf() {
  # Docker copies the working tree; a Windows tool that rewrites a shell
  # script with CRLF makes bash fail at `set -euo pipefail` inside the image.
  local bad
  bad="$(grep -rIl $'\r' scripts/*.sh motion/offline.Dockerfile 2>/dev/null || true)"
  [ -z "$bad" ] || die "CRLF line endings in files the container runs: $bad"
}

fast() {
  require_uv
  note "lint, format, types (CI test job)"
  uv run ruff check .
  uv run ruff format --check .
  uv run mypy src
  note "supply-chain pins (CI test job)"
  uv run lces supply-chain-check
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
  (cd motion && node --test --test-reporter=tap contract.test.mjs output-dir.test.mjs network-policy.test.mjs)
  note "real renders, encoding and Gate 4 (CI motion job)"
  LCES_MC_E2E=1 uv run pytest -m motion -v --basetemp=var/ci-local/pytest
  if [ "${LCES_MC_STRESS:-0}" = "1" ]; then
    note "duration tiers and resource baseline (P3-B)"
    LCES_MC_STRESS=1 LCES_STRESS_OUT=var/ci-local/stress.json       uv run pytest tests/test_motion_canvas_stress.py -v
  fi
  if [ "${LCES_MC_MATERIALS:-0}" = "1" ]; then
    note "representative materials (real renders)"
    LCES_MC_MATERIALS=1 LCES_MATERIALS_OUT=var/ci-local/materials.json       uv run pytest tests/test_motion_canvas_materials.py -v
  fi
  if [ "${LCES_MC_REPRO:-0}" = "1" ]; then
    note "reproducibility measurement (two renders)"
    LCES_MC_REPRO=1 LCES_REPRO_OUT=var/ci-local/reproducibility.json       uv run pytest tests/test_motion_canvas_reproducibility.py -v
  fi
}

offline() {
  require_docker
  require_lf
  mkdir -p var/ci-offline
  note "build the offline image (network allowed here only)"
  docker build -f motion/offline.Dockerfile -t lces-motion-offline .
  docker image inspect lces-motion-offline --format '{{.Id}}' | tee var/ci-offline/image-id.txt
  note "render, encode, Gate 4 and negative controls (--network none)"
  docker run --rm --network none --memory=2048m --memory-swap=2048m \
    -v "$ROOT/var/ci-offline:/evidence" \
    -e LCES_OFFLINE_EVIDENCE=/evidence \
    lces-motion-offline
}

full() {
  fast
  render
  offline
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
  offline) offline ;;
  full) full ;;
  -h | --help | help) usage ;;
  *) usage; exit 2 ;;
esac
