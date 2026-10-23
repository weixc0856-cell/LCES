#!/usr/bin/env bash
# Runs inside the offline P1 container (`docker run --network none`).
#
# Proves, in one run:
#   * the container really has no network (negative controls fail);
#   * a real Motion Canvas render, encode and Gate 4 check complete offline;
#   * no external request succeeded during the render;
#   * every completed build published a verified video.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

EVIDENCE="${LCES_OFFLINE_EVIDENCE:-/evidence}"
BUILDS="${LCES_OFFLINE_BUILDS:-/tmp/lces-offline-builds}"
mkdir -p "$EVIDENCE" "$BUILDS"

# uv must not try to resolve or download anything: the venv was built when the
# image was created, and the container has no network at this point.
export UV_OFFLINE=1
export UV_PYTHON_DOWNLOADS=never

note() { printf '\n==> %s\n' "$*"; }

note "record the offline environment"
node --version | tee "$EVIDENCE/node-version.txt"
npm --version | tee "$EVIDENCE/npm-version.txt"
(cd motion && npx playwright --version) | tee "$EVIDENCE/playwright-version.txt"
ffmpeg -version | sed -n '1p' | tee "$EVIDENCE/ffmpeg-version.txt"
uv run --no-sync lces doctor | tee "$EVIDENCE/doctor.txt"
sha256sum motion/package-lock.json uv.lock motion/offline.Dockerfile \
  | tee "$EVIDENCE/input-hashes.txt"

note "network negative controls (must fail)"
set +e
node -e "fetch('https://registry.npmjs.org', {signal: AbortSignal.timeout(5000)}).then(() => process.exit(0)).catch(() => process.exit(1))"
fetch_exit=$?
mkdir -p /tmp/negative-project /tmp/negative-cache
(cd /tmp/negative-project && npm install left-pad --no-audit --no-fund --cache /tmp/negative-cache)
npm_exit=$?
set -e
echo "fetch_exit=$fetch_exit npm_exit=$npm_exit" | tee "$EVIDENCE/negative-control.txt"
if [ "$fetch_exit" -eq 0 ] || [ "$npm_exit" -eq 0 ]; then
  echo "FAIL: the container reached the network; this is not an offline run" >&2
  exit 1
fi

note "real render, encode and Gate 4 (network none)"
LCES_MC_E2E=1 LCES_MC_OFFLINE=1 UV_OFFLINE=1 uv run --no-sync pytest \
  tests/test_motion_canvas_e2e.py tests/test_encode.py tests/test_release_video.py \
  -v --basetemp="$BUILDS" --junitxml="$EVIDENCE/e2e-report.xml" \
  2>&1 | tee "$EVIDENCE/e2e.log"

note "collect frame manifests, videos and reports"
uv run --no-sync python scripts/collect-motion-evidence.py \
  --root "$BUILDS" --out "$EVIDENCE"

note "verify the request audit and published outputs"
uv run --no-sync python scripts/verify-offline-evidence.py --root "$BUILDS" \
  | tee "$EVIDENCE/offline-verification.txt"

note "audit evidence for secrets and host paths"
uv run --no-sync python scripts/audit-evidence.py "$EVIDENCE" | tee "$EVIDENCE/evidence-audit.txt"
