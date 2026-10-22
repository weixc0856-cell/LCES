# Dependencies

## Toolchain

| Tool | Version | Notes |
|---|---|---|
| Python | 3.13.x | `.python-version`; `requires-python = ">=3.13,<3.14"` |
| uv | 0.5+ | Creates `.venv`, resolves `uv.lock`, runs commands |
| Git | 2.30+ | Local version control |
| FFmpeg | Phase 3 | Video/subtitle encoding, not installed now |
| Playwright | Phase 3 | Browser rendering and visual regression, `media` extra |

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

`playwright` via the `media` extra (`uv sync --extra media`) for Phase 3 only.

## Lock file policy

`uv.lock` is committed. The checked-in lock predates the Python 3.13 pin and the
`python-docx` dependency, so run `uv lock` (or simply `uv sync`) once locally
and commit the regenerated file. Do not describe dependencies as locked until
that regenerated `uv.lock` is in the repository.

## Upgrade policy

Upgrade in a dedicated change, run the full test suite, and record the reason.
Model provider model IDs are configuration, not dependencies: verify them
against the official documentation at the time of use.
