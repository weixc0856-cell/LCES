# Development Rules

## Environment

- Python **3.13**, locked by `.python-version` and `requires-python = ">=3.13,<3.14"`.
- Virtual environment **inside the repository** at `.venv/`. Never install business dependencies globally.
- Use `uv sync` (installs the default `dev` dependency group), then `uv run …` for everything.
- If an existing `.venv` was created with another Python version, `scripts/bootstrap.ps1` (Windows) or `scripts/bootstrap.sh` removes and rebuilds it. `uv sync` also recreates an incompatible environment on its own.

## Commands

```powershell
uv run lces doctor
uv run lces supply-chain-check      # pins vs. Dockerfile, lockfiles, workflows
uv run lces models                 # probe local llama-server without generating
                                   # course-dev model/profile: docs/LOCAL_MODEL.md
uv run lces run .\projects\p1 --routing config/routing.yaml
uv run lces export-schemas
uv run pytest
uv run pytest --cov=src/content_studio --cov-report=term-missing
uv run ruff check .
uv run ruff format .
uv run mypy src
```

## Local-first verification

Run these before pushing. GitHub Actions is the final clean-environment gate,
not the development loop:

```bash
./scripts/ci-local.sh fast     # ruff, format, mypy, supply-chain audit, pytest (any OS)
./scripts/ci-local.sh render   # Linux/WSL2: Node contract + real renders + encode + Gate 4
./scripts/ci-local.sh offline  # Docker: build once, run renders with --network none
./scripts/ci-local.sh full     # fast + render + offline + browser QA
```

- The script reuses the exact commands from `.github/workflows/ci.yml`; it never
  installs anything and never skips a gate.
- `render` and `full` require Linux (WSL2), Node **24.22.1** (the Motion Canvas
  gate), `motion/node_modules` (`npm ci`), the Playwright Chromium for 1.64.0,
  and FFmpeg/ffprobe.
- `offline` (and the offline stage of `full`) need a Docker daemon running Linux
  containers. The image is built with network access; the render, encode, Gate 4
  and negative controls then run with `--network none`. A missing tool or a
  reachable network fails the gate.
- A missing tool stops the script with the command to run. Do not lower the
  version gates to make a local run pass.

## Dependency policy

- Runtime dependencies: `uv add <package>` then commit `pyproject.toml` + `uv.lock`.
- Dev tools: `uv add --dev <package>` (writes `[dependency-groups].dev`).
- Media-only packages (Playwright) stay in the `media` and `browser` extras and are not installed by default.
  Gate 3 browser checks need `uv sync --extra browser` plus `uv run playwright install chromium`;
  without them the checks report `NOT_RUN`.
- Do not claim a dependency is locked until `uv.lock` contains it.

## Coding rules

- Public functions have type hints. External data is validated at boundaries with Pydantic.
- Expected failures raise subclasses of `LCESError`; do not swallow exceptions silently.
- Never log or persist API keys, authorization headers, or full prompts containing secrets.
- Do not write into `release/` from content modules. Only `release.py` assembles it.
- New release-blocking rule ⇒ new test. A rule that is not implemented must report `NOT_RUN`.

## Data rules

- `input/` raw snapshots, `internal/` research and scripts, `content/` structured assets, `build/` disposable, `release/` whitelisted deliverables.
- Public HTML only receives `PublicContent`. Never pass `SpeakerScript` or internal notes to templates.
- Source excerpts are short quotations with locators; do not store long copyrighted passages.

## Git

```powershell
git init -b main            # first time only
git remote add origin git@github.com:weixc0856-cell/LCES.git
git add .
git commit -m "feat: phase 0 + phase 1 baseline"
git push -u origin main
```

Commit `uv.lock`, `schemas/`, templates, and tests. Never commit `.env`, `var/`, `projects/*/internal/`, `projects/*/build/`, or `projects/*/release/`.
