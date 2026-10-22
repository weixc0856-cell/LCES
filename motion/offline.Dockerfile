# Offline P1 gate image.
#
# Build with network access; run with `--network none`. Everything the render
# needs (Node, Motion Canvas dependencies, Chromium, FFmpeg, Python) is baked
# in at build time, so a successful run proves the render itself is offline.
# The image ID and input hashes are recorded as evidence by CI.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    UV_LINK_MODE=copy

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl xz-utils \
 && rm -rf /var/lib/apt/lists/*

# Node is installed at the exact version the adapter enforces.
RUN curl -fsSLo /tmp/node.tar.xz \
      https://nodejs.org/dist/v24.22.1/node-v24.22.1-linux-x64.tar.xz \
 && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
 && rm /tmp/node.tar.xz \
 && test "$(node --version)" = "v24.22.1"

WORKDIR /app
COPY . .

# `npm ci` is the only admitted install; the lockfile is checked again by the
# adapter at render time.
RUN cd motion \
 && npm ci --no-audit --no-fund \
 && npm rebuild esbuild \
 && npx playwright install --with-deps chromium

RUN uv sync --locked

ENV PATH=/app/.venv/bin:$PATH

CMD ["bash", "scripts/ci-motion-offline.sh"]
