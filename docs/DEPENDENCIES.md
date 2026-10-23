# Dependencies

## Toolchain

| Tool | Version | Notes |
|---|---|---|
| Python | 3.13.x | `.python-version`; `requires-python = ">=3.13,<3.14"` |
| uv | 0.5+ | Creates `.venv`, resolves `uv.lock`, runs commands |
| Git | 2.30+ | Local version control |
| Node | 24.22.1 | Motion Canvas render only; hard gate in `motion_canvas.py` and `motion/package.json` |
| npm | 11.x | Ships with Node 24.22.1; only `npm ci` is admitted |
| Playwright | 1.64.0 | Motion Canvas driver (`motion/`), plus the optional `browser`/`media` extras |
| FFmpeg / ffprobe | 6.0+ | Encoding, media probing, subtitle checks |
| Graphviz | 2.40+ | `graphviz.dot`, environment-gated (`LCES_DOT_BIN` or PATH) |

## Runtime (installed by `uv sync`)

| Package | Constraint | Role |
|---|---|---|
| typer | >=0.12,<1.0 | CLI commands and options |
| pydantic | >=2.8,<3.0 | Contracts and validation |
| pydantic-settings | >=2.4,<3.0 | `.env` and environment configuration |
| PyYAML | >=6.0,<7.0 | `project.yaml`, config files |
| httpx | >=0.27,<1.0 | Provider HTTP calls and URL ingestion |
| jinja2 | >=3.1,<4.0 | Public HTML templates (autoescape on) |
| beautifulsoup4 | >=4.12,<5.0 | HTML text extraction |
| pypdf | >=5.0,<7.0 | PDF text extraction (no OCR) |
| python-docx | >=1.1,<2.0 | DOCX text extraction |

## Development (`[dependency-groups].dev`, installed by default)

pytest, pytest-cov, ruff, mypy, types-PyYAML. `uv sync --no-dev` skips them.

## Optional

`playwright` via the `media` or `browser` extra (`uv sync --extra browser`) for
browser QA. `vl-convert-python` via `charts`; `mcp` for the MCP stdio server.

## Supply-chain record (P2.3-C)

Every pinned build input has one entry in `config/supply-chain.json`. The record
separates two ideas that are often conflated:

- **trust** — the channel the input came from: `official-release` (Node's own
  release directory), `official-registry` (npmjs/PyPI), `upstream-publisher`
  (the project's published image), `upstream-installer` (a dependency's own
  downloader), `distro-package` (apt).
- **reproducibility** — what the pin can promise: `digest-pinned`,
  `checksum-pinned`, `lockfile-pinned`, `version-pinned`, or `version-floor`.
  A version floor (FFmpeg from apt) is recorded as such; it is not sold as
  byte-identical reproducibility.

```powershell
uv run lces supply-chain-check
```

The audit is static and fails (exit code 1) when a pin does not reach the build:

| Check | Consumer it reads |
|---|---|
| SC-01 base image digest | `motion/offline.Dockerfile` `FROM` |
| SC-02 Node archive SHA-256 | Dockerfile `ARG`s + `sha256sum -c` |
| SC-03 npm registry + integrity | `motion/package-lock.json` |
| SC-04 lockfile vs `package.json` | both npm manifests |
| SC-05 Actions commit SHAs | `.github/workflows/*.yml` |
| SC-06 version constants | record ↔ adapter constants ↔ `motion/package.json` |
| SC-07 Python lock coverage | `uv.lock`, `pyproject.toml`, CI `uv sync --locked`; every package resolves to `https://pypi.org/simple` |

CI runs it in the `test` job and `scripts/ci-local.sh fast` runs it locally.
What the audit cannot prove: that an upstream release was honest, or that a
build is byte-identical across machines. `internal/qa/encode_report.json`
records the Level 1 provenance of each render (`schema_version` 1.1):
tool versions plus the hashes of `package.json` and `package-lock.json`.

Upgrade procedure — change both the record and the consumer in one commit:

1. resolve the new digest/checksum from the upstream source;
2. update `config/supply-chain.json` and the Dockerfile/workflow/lockfile;
3. run `uv run lces supply-chain-check` and the full test suite;
4. rebuild the offline image and record the new image ID in the P2.3 plan.

## Lock file policy

`uv.lock` is committed and current (`uv lock --check` succeeds). CI and the
offline image install with `uv sync --locked`, so a stale lockfile fails instead
of silently re-resolving. `motion/package-lock.json` is committed as well; the
adapter refuses to render when the installed direct dependencies disagree with
it.

## Upgrade policy

Upgrade in a dedicated change, run the full test suite, and record the reason.
Model provider model IDs are configuration, not dependencies: verify them
against the official documentation at the time of use.
