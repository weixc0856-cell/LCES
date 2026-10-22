# Implementation Status

Updated for the Phase 0 + Phase 1 baseline (package version 0.2.0).

Status meanings: **Implemented** = code exists and is covered by written tests;
**Partial** = code exists but a meaningful part is missing; **Not implemented** =
no code path exists; **Config only** = configuration placeholder, not consumed
by a working code path.

| Capability | Status | Notes |
|---|---|---|
| Python 3.13 pin / project `.venv` | Implemented | `.python-version`, `requires-python`, `scripts/bootstrap.*`, VS Code interpreter path |
| Dependency groups + lock workflow | Implemented | `dev` group installed by `uv sync`; regenerate `uv.lock` locally after changes |
| CLI (`doctor`, `init-project`, `ingest`, `research`, `outline`, `generate`, `build`, `validate`, `release-check`, `approve`, `release`, `status`, `run`, `export-schemas`) | Implemented | |
| Unified Pydantic contracts | Implemented | `models.py`; JSON Schema export command |
| SQLite task/stage/asset/approval records | Implemented | `storage.py`; state machine values from PRD |
| DeepSeek adapter (OpenAI-compatible) | Implemented | `httpx`, timeout, bounded retry, usage extraction |
| Anthropic adapter | Implemented | Messages API via `httpx`; no SDK dependency |
| Local llama.cpp adapter | Implemented | OpenAI-compatible `/v1`, no key required, model auto-discovery, `/health` probe |
| Mock provider | Implemented | Deterministic; release gates reject it |
| Stage routing (local/cloud mix) | Partial | `research`/`outline`/`generate` only; no automatic escalation or quality-based routing |
| Model diagnostics | Implemented | `lces models` probes local `/health` and `/v1/models` |
| Usage telemetry | Partial | Tokens and provider/model per stage in SQLite; no cost pricing table |
| Local prompt budgeting | Implemented | `LCES_LOCAL_PROMPT_CHAR_BUDGET`, default 24000 characters |
| Local ingestion (MD/TXT/HTML/PDF/DOCX) | Implemented | PDF without text layer marked `partial` (no OCR) |
| URL ingestion | Partial | No JS rendering, login, or anti-bot handling; failures recorded as `unavailable` |
| Source registry with hashes | Implemented | `internal/source_registry.json`, raw copies in `input/` |
| Claims / evidence ledger / research brief | Implemented | One research call; CSV ledger with verification status |
| Course outline | Implemented | Evidence-linked sections |
| Public content / speaker script separation | Implemented | Separate models, separate files, template accepts public model only |
| Reading edition | Implemented | Structured JSON + HTML |
| Public HTML build | Implemented | Jinja2, autoescaping, offline inline CSS |
| Gate 1 research checks | Partial | Structural checks only; scientific review is `NOT_RUN` |
| Gate 2 content checks | Partial | Schema, mapping, markers, citations, mock detection, duration estimate |
| Gate 3 engineering checks | Partial | Build/UTF-8/markers/figures; browser visual regression `NOT_RUN` |
| Gate 4 release checks | Partial | Allowlist/markers/secrets/hashes/approval; media decode `NOT_RUN` |
| Release staging + manifest + ZIP | Implemented | ZIP built only from `release/` tree |
| Human approval recording | Implemented | File + SQLite; not a web UI |
| Failure recovery | Partial | Stage-scoped rerun with task records; no automatic retry queue |
| Model routing / cost statistics | Partial | Explicit stage routing works; automatic escalation, eval-based routing and pricing are not implemented |
| Local model evaluation suite | Not implemented | No `evals/` benchmark runner yet; see `local model.md` for the proposed test set |
| Playwright visual regression | Not implemented | Phase 3 |
| SVG/Canvas scene engine, frame export | Not implemented | `scene_render_contract` schema only |
| FFmpeg video, subtitles, media checks | Not implemented | Phase 3 |
| Local web interface | Not implemented | Phase 6 |
| CI workflow | Partial | `.github/workflows/ci.yml` runs pytest/ruff on Python 3.13; not verified in this environment |

## Verification status

Executed in the environment that produced this baseline (Linux sandbox,
Python 3.13.15, dependencies from `pyproject.toml`, separate environment so the
Windows `.venv` was not modified):

| Command | Result |
|---|---|
| `uv sync` | 47 packages resolved/installed |
| `pytest -q` | 51 passed |
| `ruff check .` | passed |
| `ruff format --check .` | passed |
| `mypy src` | no issues in 24 source files |
| `lces export-schemas` | 12 schemas written |
| `lces run` (mock, temp project) | all 6 stages completed; QA correctly returned `NEEDS_REVISION` and blocked release |

These results validate the implemented checks only. They do not prove
scientific correctness, source authenticity, or end-to-end production
readiness. On the user's machine the existing `.venv` was created with Python
3.14.3 and must be rebuilt with Python 3.13 (`scripts/bootstrap.ps1` or
`uv sync`), after which the same commands should be re-run locally.
