# Offline P1 gate image.
#
# Build with network access; run with `--network none`. Everything the render
# needs (Node, Motion Canvas dependencies, Chromium, FFmpeg, Python) is baked
# in at build time, so a successful run proves the render itself is offline.
# The image ID and input hashes are recorded as evidence by CI.
#
# P2.3-C pins both downloads:
#   - the base image by multi-arch index digest (the tag stays for readability);
#   - the Node archive by SHA-256 taken from the official SHASUMS256.txt, and
#     verified before extraction.
# `lces supply-chain-check` fails when this file and config/supply-chain.json
# disagree. Upgrade both together, then rebuild and record the new image ID.
#
# Debian trixie is required: bookworm ships FFmpeg 5.1, below the adapter's
# >= 6.0 gate.
FROM ghcr.io/astral-sh/uv:python3.13-trixie-slim@sha256:331fbb158258608b9391e802305a9a2c9e42d689435c1d98706647122a122ab0

ENV DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    UV_LINK_MODE=copy

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg ca-certificates curl xz-utils \
 && rm -rf /var/lib/apt/lists/* \
 && ffmpeg -version | awk 'NR==1 {split($3, v, "."); exit !(v[1] >= 6)}'

# Node is installed at the exact version the adapter enforces. The checksum is
# the official release hash; a corrupted or substituted archive fails the
# build instead of becoming part of the image.
ARG NODE_VERSION=24.22.1
ARG NODE_SHA256=6c172a9ab6718f7b801fb5a7bd486af2ee5e32758086a04b84fcce2aa77095e6

RUN curl -fsSLo /tmp/node.tar.xz \
      "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
 && echo "${NODE_SHA256}  /tmp/node.tar.xz" | sha256sum -c - \
 && tar -xJf /tmp/node.tar.xz -C /usr/local --strip-components=1 \
 && rm /tmp/node.tar.xz \
 && test "$(node --version)" = "v${NODE_VERSION}"

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
