# Implementation Status

Updated through the roadmap phases (0-6), continuous evaluation/cost work,
PRD 2 modules 1-2, and the Mermaid/Graphviz renderers — package version 0.11.0.

Status meanings: **Implemented** = code exists and is covered by written tests;
**Partial** = code exists but a meaningful part is missing; **Not implemented** =
no code path exists; **Config only** = configuration placeholder, not consumed
by a working code path.

| Capability | Status | Notes |
|---|---|---|
| Python 3.13 pin / project `.venv` | Implemented | `.python-version`, `requires-python`, `scripts/bootstrap.*`, VS Code interpreter path |
| Dependency groups + lock workflow | Implemented | `dev` group installed by `uv sync`; regenerate `uv.lock` locally after changes |
| CLI (`doctor`, `init-project`, `ingest`, `research`, `outline`, `generate`, `build`, `validate`, `release-check`, `approve`, `release`, `status`, `run`, `export-schemas`, `render-spec`, `review-claims`, `media-check`, `mcp-serve`, `eval`, `usage`) | Implemented | |
| Unified Pydantic contracts | Implemented | `models.py`; JSON Schema export command |
| SQLite task/stage/asset/approval records | Implemented | `storage.py`; state machine values from PRD |
| DeepSeek adapter (OpenAI-compatible) | Implemented | `httpx`, timeout, bounded retry, usage extraction |
| Anthropic adapter | Implemented | Messages API via `httpx`; no SDK dependency |
| Local llama.cpp adapter | Implemented | OpenAI-compatible `/v1`, optional `--api-key`, model auto-discovery, `/health` probe, loopback traffic bypasses OS proxies |
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
| Public HTML build | Implemented | Jinja2, autoescaping, offline inline CSS; table and figure blocks render through the registry |
| Visual spec contract | Implemented | `VisualSpec` with `schema_version` 1.x, generated JSON Schema, renderer/validation fields |
| Renderer registry | Implemented | `renderers.py`; unknown types fail the build; renderer name/version/`output_sha256` recorded in `internal/qa/render_manifest.json` |
| Renderer interface (PRD 2) | Implemented | `validate_input`, `check_environment`, `estimate_resources`, `cancel`, `collect_outputs`, `validate`, `get_diagnostics`; ordered checks with recorded diagnostics |
| Visual asset contract | Implemented | `VisualAsset` with workspace-relative paths, hashes, QA results; `internal/qa/visual_assets.json` per build |
| Scene / video contracts | Implemented | Integer-ms scenes, rational fps, audio/subtitle/encoding fields, provenance and build hash; schemas exported |
| Mermaid diagrams | Implemented | Vendored runtime 12.2.0 (MIT, sha256-verified), offline Chromium, strict config, rejects init/click directives |
| Motion Canvas P0 (experiment) | Conditional (CI) | `spike/motion-canvas` + manual workflow; offline 300-frame render, negative control, cancel/timeout pass on Linux; not in production |
| Graphviz graphs | Implemented (environment-gated) | `graphviz.dot` via `LCES_DOT_BIN`/PATH (>= 2.40); CI acceptance on Graphviz 2.43.0 with real `dot` rendering (14/14 tests); Windows 16.1.0 install still pending |
| Renderer environment diagnostics | Implemented | `lces doctor` reports Mermaid runtime and Graphviz availability |
| Legacy render comparison | Implemented | `use_registry=False` keeps the template-only path; a parity test compares both outputs |
| Chart rendering (Vega-Lite) | Implemented | `data_chart` renders static SVG through `vl-convert`; optional `charts` extra; no Node.js or network |
| Custom SVG rendering | Implemented | `custom_svg` inlines XML-valid SVG after blocking scripts, handlers, `foreignObject`, and external references |
| Inline SVG accessibility/layout | Implemented | `role="img"`, `aria-label`, `max-width:100%`; mobile overflow caught by browser QA and fixed |
| Third-party licence record | Implemented | `LICENSE-THIRD-PARTY.md` lists Playwright/Chromium, vl-convert, Vega-Lite/Vega |
| Gate 1 research checks | Partial | Evidence references, key-claim support, claim/evidence review states, locators, contradicted-claim blocking; scientific review is `NOT_RUN` |
| Claim-level verification | Implemented | Six canonical states plus legacy mapping; `lces review-claims` records reviewer and time |
| Model self-verification blocked | Implemented | Research stage resets model-reported statuses; `supported` without a reviewer is treated as `pending` |
| Broken claims handling | Implemented | `claims.json` parse failures fail Gate 1 instead of becoming "no claims" |
| Gate 2 content checks | Partial | Schema, mapping, markers, citations, mock detection, duration estimate |
| Gate 3 engineering checks | Implemented | Build/UTF-8/markers/figures plus Playwright page load, JS errors, resource loads, overflow at five viewports; screenshot baselines |
| Gate 4 release checks | Partial | Allowlist/markers/secrets/hashes/approval; media decode, audio presence, and subtitle timing when media is present |
| Media probing and frame sampling | Implemented | `media.py` + `lces media-check`; ffprobe metadata, FFmpeg frame extraction for review |
| Subtitle timing checks | Implemented | SRT/VTT cues must be ordered, non-inverted, and inside the video duration |
| Tool layer | Implemented | `tools.py`: Pydantic input validation, read/write access, JSONL call log |
| MCP stdio server | Implemented | Optional `mcp` extra; thin wrappers over `invoke_tool`; no release/approve/delete tool |
| Release staging + manifest + ZIP | Implemented | ZIP built only from `release/` tree |
| Human approval recording | Implemented | File + SQLite; not a web UI |
| Failure recovery | Partial | Stage-scoped rerun with task records; no automatic retry queue |
| Model routing / cost statistics | Partial | Explicit stage routing with per-stage fallback and a usage/cost report; automatic quality-based routing and per-task cost prediction are not implemented |
| Failure escalation | Implemented | Provider error triggers one fallback retry; both stage runs recorded |
| Usage and cost report | Implemented | `lces usage` from `stage_runs`; local/unpriced models reported as not costed, never zero |
| Local model evaluation suite | Implemented | `evals/basic.jsonl` (8 task types) + `lces eval`; mechanical checks, JSON reports in `var/evals/` |
| Playwright browser QA | Implemented | Optional `browser` extra; checks page load, JS errors, resources, overflow at 1280/1920/2560/3840/mobile viewports |
| Visual regression | Partial | Screenshot baselines compared byte-for-byte; differences are `warn` for human review, no pixel-diff tooling yet |
| SVG/Canvas scene engine, frame export | Not implemented | `scene_render_contract` schema only |
| Video/animation generation (Manim/Remotion) | Not implemented | FFmpeg is used for inspection only |
| FFmpeg video, subtitles, media checks | Not implemented | Phase 3 |
| Local web interface | Not implemented | Phase 6 |
| CI workflow | Implemented | `test`, `browser-qa`, and `graphviz` jobs all green (run `39740736404`); Graphviz evidence uploaded as an artifact. Manual `motion-canvas-p0` workflow green (run `39742834259`) |

## Verification status

Executed on the development machine (Windows 11, Python 3.13.12, project
`.venv` rebuilt by `scripts/bootstrap.ps1`) on 2026-10-22:

| Command | Result |
|---|---|
| `uv sync --extra browser` | 45 packages resolved; Playwright 1.64 + Chromium headless shell installed |
| `pytest -q` | 177 passed, 1 skipped (local real Graphviz test) |
| `ruff check .` | passed |
| `ruff format --check .` | passed |
| `mypy src` | no issues in 33 source files |
| `lces run` (local `Qwen3.5-4B`, arXiv 1706.03762) | all 6 stages completed; browser QA established 10 baselines; Gate 3 passed |
| `lces run --only build` through the registry | table rendered by `html.table` 1.0.0; manifest hash recorded; screenshots still match baseline |
| `lces render-spec` (unknown `visual_type`) | exits 1 with `UnsupportedVisualType`; no placeholder output |
| `lces render-spec` (Vega-Lite BLEU chart) | `vega_lite.chart` 1.0.0, 9.9 KB SVG, no script; Chromium: 0 JS errors, 0 broken assets, 0 overflow at desktop and 390 px |
| `lces validate` (real project, Gate 1) | model-written `verified` evidence reported as unverified (no reviewer); key claims pending — warnings only, no blocking failure |
| `lces review-claims` | rejects unknown status and empty reviewer; records reviewer + `reviewed_at` in `claims.json` |
| `lces media-check` (2 s test clip) | 640x360, 2.00 s, mpeg4 + aac; three keyframes written |
| Gate 4 media checks | corrupt video fails; valid video plus in-range subtitles passes; no media reports `NOT_RUN` |
| `lces mcp-serve` (MCP SDK absent) | exits 1 and names `uv sync --extra mcp` |
| MCP server smoke | lists `project_status`, `task_status`, `qa_report`, `release_manifest`; `run_validate` only with `--allow-write`; no release tool |
| `lces eval --provider local` (8 tasks) | 7/8 passed, average latency 23.2 s; `explain-001` failed for omitting `softmax`; report kept in `var/evals/` |
| `lces usage --pricing config/pricing.yaml` | local: 4 calls, 12,777 in / 4,808 out tokens, reported as 未核算 (not zero) |
| Stage fallback routing | local `ProviderError` retried with `mock`; `stage_runs` records one fail then one pass |
| `lces run --only build` (asset contract) | `visual_assets.json`: `slide-003-block-01`, `table`, `html.table 1.0.0`, source + output sha256, status `rendered` |
| `lces export-schemas` | 16 schemas, including `visual_asset`, `scene_contract`, `video_contract` |
| `lces doctor` (local) | `Mermaid: 可用 — vendored 12.2.0`; `Graphviz: 不可用 — ... winget ... 16.1.0` |
| CI `test` / `browser-qa` / `graphviz` | all green (run `39740736404`); mypy passes without optional extras |
| CI Graphviz evidence | `dot - graphviz version 2.43.0`; 14 tests, 0 failures; artifact `graphviz-evidence` uploaded |
| Motion Canvas P0 CI (manual) | run `39742834259`: `--network none` 300 frames in 4.71 s; negative controls exit 1; cancel 95 frames; timeout 76 frames; evidence artifact uploaded |
| Graphviz renderer | stubbed path covers syntax error, timeout, unsafe output; real `dot` test passes in CI (2.43.0), skipped locally until 16.1.0 is installed |
| Mermaid renderer | flowchart + sequence render offline; invalid syntax, malicious labels, init directives, and a 1 ms timeout all fail explicitly |
| `lces approve` / `release` / `release-check` | v1 assembled and verified (Gate 4 partial; no media in v1) |

These results validate the implemented checks only. They do not prove
scientific correctness, source authenticity, or end-to-end production
readiness. The sample run needed manual corrections to a model-generated
complexity claim that no automated gate could detect; `scientific_review`
remains `NOT_RUN`.
