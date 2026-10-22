# Acceptance Plan

Execute after `uv sync`. Each item is checked against real command output; none
is considered passing because the code exists.

## Authoring environment results (Linux, Python 3.13.15)

| Command | Result |
|---|---|
| `pytest -q` | 51 passed |
| `ruff check .` | passed |
| `ruff format --check .` | passed |
| `mypy src` | passed |
| `lces run` (mock, temp project) | 6/6 stages; `NEEDS_REVISION`; release refused |
| `lces run --routing` (mock routing) | stage providers recorded as mock/none |
| `lces models` (no server) | reports unreachable without crashing |

The Windows `.venv` in this checkout is still Python 3.14.3; rebuild it before
repeating these checks locally.

## Environment

- [ ] `uv run lces doctor` reports Python 3.13 and a project `.venv`.
- [ ] `uv run pytest` passes.
- [ ] `uv run ruff check .` passes.
- [ ] `uv run lces export-schemas` writes schemas without error.

## MVP checklist (PRD section 18)

| ID | Item | Automated evidence | Status |
|---|---|---|---|
| MVP-01 | Local install and start | `doctor`, bootstrap script | Code ready; run locally |
| MVP-02 | Local PDF/Markdown and web input | `tests/test_ingestion.py` | Code ready; real web fetch not executed |
| MVP-03 | One real provider adapter | DeepSeek + Anthropic adapters | Code ready; requires API key and live call |
| MVP-04 | Claims have sources and verification state | evidence ledger + Gate 1 | Code ready |
| MVP-05 | Public and internal schemas separate | `tests/test_models.py`, rendering test | Code ready |
| MVP-06 | Public HTML renders the course | `tests/test_rendering.py` | Code ready |
| MVP-07 | Speaker script stored separately and mapped | `tests/test_pipeline.py` | Code ready |
| MVP-08 | No internal files in release | Gate 4 + `tests/test_release.py` | Code ready |
| MVP-09 | Schema/build/release tests pass | `pytest` | Run locally |
| MVP-10 | Failed gates block release | `test_release_is_blocked_when_qa_fails` | Code ready |
| MVP-11 | Traceability: input hashes, provider/model, QA | registry, trace JSON, manifest | Code ready |
| MVP-12 | Failed tasks retain state and can resume | SQLite stage runs, `--from-stage` | Code ready |

## Manual checks that automation cannot replace

- [ ] Read the research brief and confirm claims match the original paper.
- [ ] Verify formulas, units, normalization, and chart semantics.
- [ ] Confirm every key claim has evidence and unresolved conflicts are stated.
- [ ] Confirm the public page contains no narration, QA notes, paths, or secrets.
- [ ] Record approval only after the above review.
- [ ] After approval, run `lces release` and `lces release-check`, then open the
      HTML from the release directory offline.

## Known NOT_RUN items

Font fallback, media decode, subtitle timing, and audio/video synchronization
are not implemented. They must remain `NOT_RUN` in QA reports. Browser page
load, JavaScript errors, resource loads, viewport overflow, and screenshot
baselines are covered by Gate 3 when the `browser` extra is installed; without
it those checks are reported `NOT_RUN`, never `PASS`.
