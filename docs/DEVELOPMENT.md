# Development Rules

## Environment

- Python **3.13**, locked by `.python-version` and `requires-python = ">=3.13,<3.14"`.
- Virtual environment **inside the repository** at `.venv/`. Never install business dependencies globally.
- Use `uv sync` (installs the default `dev` dependency group), then `uv run …` for everything.
- If an existing `.venv` was created with another Python version, `scripts/bootstrap.ps1` (Windows) or `scripts/bootstrap.sh` removes and rebuilds it. `uv sync` also recreates an incompatible environment on its own.

## Commands

```powershell
uv run lces doctor
uv run lces models                 # probe local llama-server without generating
uv run lces run .\projects\p1 --routing config/routing.yaml
uv run lces export-schemas
uv run pytest
uv run pytest --cov=src/content_studio --cov-report=term-missing
uv run ruff check .
uv run ruff format .
uv run mypy src
```

## Dependency policy

- Runtime dependencies: `uv add <package>` then commit `pyproject.toml` + `uv.lock`.
- Dev tools: `uv add --dev <package>` (writes `[dependency-groups].dev`).
- Media-only packages (Playwright) stay in the `media` extra and are not installed by default.
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
