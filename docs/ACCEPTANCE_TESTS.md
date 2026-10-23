# Acceptance Plan

Execute after `uv sync`. Each item is checked against real command output; none
is considered passing because the code exists.

## Authoring environment results (Windows 11, Python 3.13.12)

| Command | Result |
|---|---|
| `pytest -q` | 333 passed, 11 skipped (Graphviz and ten Linux-only Motion Canvas tests) |
| `ruff check .` | passed |
| `ruff format --check .` | passed |
| `mypy src` | passed (27 source files) |
| `lces run` (mock, temp project) | 6/6 stages; `NEEDS_REVISION`; release refused |
| `lces run --routing` (mock routing) | stage providers recorded as mock/none |
| `lces models` (no server) | reports unreachable without crashing |
| `lces validate` (real project) | Gate 3 pass; 10 browser screenshots/baselines |
| `lces render-spec` (unknown type) | exits 1 with `UnsupportedVisualType` |
| `lces render-spec` (Vega-Lite chart) | static SVG rendered offline; Chromium check 0 errors/0 overflow |
| `lces validate` (Gate 1) | model-set `verified` without reviewer treated as unverified |
| `lces review-claims` | writes reviewer/time; rejects unknown status and empty reviewer |
| `lces media-check` | probes duration/resolution/codecs and samples keyframes (FFmpeg required) |
| `lces mcp-serve` | read-only tool list by default; `--allow-write` adds `run_validate`; no release tool |
| `lces eval --provider local` | 7/8 on the fixed 8-task set; report written to `var/evals/` |
| `lces usage --pricing config/pricing.yaml` | token/failure/time figures from `stage_runs`; local marked 未核算 |
| fallback routing | provider error retries once with the configured fallback; both attempts recorded |
| `lces export-schemas` | 16 schemas, including asset/scene/video contracts |
| `lces run --only build` | `internal/qa/visual_assets.json` records renderer version, source/output hashes, and QA status |
| `lces doctor` | reports the vendored Mermaid runtime and Graphviz availability |
| Mermaid/Graphviz adapters | offline SVG rendering, invalid input, missing dependency, timeout, and unsafe output all fail explicitly |

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

## Phase 1-6 automated evidence

- Browser QA: `tests/test_browser_qa.py` covers page load, JavaScript errors,
  horizontal overflow, baseline creation/comparison, and the `not_run`
  fallback when Playwright is absent.
- Content/visual contracts: `tests/test_renderers.py` covers registry dispatch,
  unknown visual types, invalid table data, missing figure assets, escaping,
  render-manifest provenance, and legacy-versus-registry output parity.
- Chart/SVG backends: the same file covers Vega-Lite SVG output, invalid Vega
  specs, custom-SVG safety checks (script/remote/path traversal), and the
  responsive inline-SVG attributes.
- Evidence governance: `tests/test_evidence.py` covers status mapping,
  anonymous-status demotion, generation-time reset, contradicted-claim
  blocking, pending warnings, and broken claims files; `tests/test_cli.py`
  covers `review-claims`.
- Media: `tests/test_media.py` generates a real clip with FFmpeg and covers
  probing, corrupt files, frame extraction, SRT/VTT timing, and Gate 4
  verdicts (skipped when FFmpeg is absent).
- Tools/MCP: `tests/test_tools.py` covers input validation, permission denial,
  JSONL logging, and the MCP tool list; `tests/test_cli.py` covers the missing
  SDK message.
- Evaluation/routing/cost: `tests/test_eval.py` covers check kinds and report
  contents; `tests/test_usage.py` covers aggregation, pricing, and the
  not-costed rules; `tests/test_routing.py` and `tests/test_pipeline.py` cover
  fallback parsing and the retry path.
- Asset/scene/video contracts: `tests/test_contracts.py` covers path safety,
  hashes, durations, rational fps, and enum validation; `tests/test_renderers.py`
  covers environment/input gating, diagnostics, resource estimates, and the
  asset manifest.
- Mermaid: `tests/test_mermaid.py` covers runtime presence/hash, offline
  flowchart and sequence rendering, init/click rejection, malicious labels,
  invalid syntax, and timeout.
- Graphviz: `tests/test_graphviz.py` covers the pinned install hint, version
  parsing, unsafe input, render failures, timeouts, and unsafe output; the real
  `dot` test is skipped when Graphviz is absent (run in the CI `graphviz` job).
- Motion Canvas P1: `tests/test_timeline.py` covers integer frame boundaries;
  `tests/test_motion_canvas.py` covers input/platform/version/lockfile gates and
  a fault matrix where every failure leaves the old video and QA evidence
  untouched; `tests/test_frame_manifest.py` covers manifest hashes, PNG
  structure, scene spans, path containment and decode; `tests/test_encode.py`
  and `tests/test_video_qa.py` cover explicit FFmpeg parameters, staging and
  video/manifest agreement; `tests/test_release_video.py` runs Gate 4 against a
  real encoded video; `tests/test_motion_canvas_e2e.py` performs real renders,
  cancellation and timeout on Linux. `tests/test_offline_evidence.py` checks
  the verifier used by the `--network none` job.
- Motion Canvas supply chain (P2.3-C): `tests/test_supply_chain.py` audits the
  checked-in repository, then flips one pin at a time (image digest, Node
  checksum, registry host, integrity, exact versions, action SHAs, Python
  lockfile) and asserts the matching SC check fails. CI runs
  `uv run lces supply-chain-check` in the `test` job.
- Motion Canvas network boundary (P2.3-D): `motion/network-policy.test.mjs`
  covers the allow/block matrix, query stripping and the fake-page
  continue/abort behaviour; `tests/test_motion_canvas.py` asserts all three
  templates pin the local font stack; `tests/test_motion_canvas_e2e.py`
  requires a real build to report `network_policy=local-only`, a non-zero
  blocked count and a named font. The offline job still proves the OS-level
  block.
- Motion Canvas acceptance (P2.3-E): `tests/test_encode.py` asserts the
  encode report's FFmpeg command is build-relative and path-free;
  `tests/test_utils.py` asserts `doctor` never prints the user home;
  `tests/test_evidence_audit.py` plants home paths and secrets in an evidence
  tree and expects findings while skipping binaries and symlinks. CI runs
  `scripts/audit-evidence.py` before uploading the p1, graphviz and offline
  artifacts. `docs/design/motion-canvas-p2.3-e-acceptance.md` maps N01–N18 to
  these tests.

## Manual checks that automation cannot replace

- [ ] Read the research brief and confirm claims match the original paper.
- [ ] Verify formulas, units, normalization, and chart semantics.
- [ ] Confirm every key claim has evidence and unresolved conflicts are stated.
- [ ] Confirm the public page contains no narration, QA notes, paths, or secrets.
- [ ] Record approval only after the above review.
- [ ] After approval, run `lces release` and `lces release-check`, then open the
      HTML from the release directory offline.

## Known NOT_RUN items

Font fallback, OCR, anti-bot handling, scientific review, audio/video
synchronization, and pixel-level visual diff are not implemented. They must
remain `NOT_RUN` in QA reports.
Media decode, audio-stream presence, subtitle timing, and Motion Canvas
frame/video QA **are** implemented and must not be reported as `NOT_RUN` when
FFmpeg is available; without FFmpeg the media checks are `NOT_RUN`, never
`PASS`. Browser page load, JavaScript errors, resource loads, viewport
overflow, and screenshot baselines are covered by Gate 3 when the `browser`
extra is installed; without it those checks are reported `NOT_RUN`, never
`PASS`. Motion Canvas blank-frame/visual acceptance (MC-04), cross-environment
byte-for-byte reproducibility (Level 3), and Windows-native rendering remain
`NOT_RUN`.

- Motion Canvas reproducibility (P2.4-C): `tests/test_reproducibility.py` covers
  the manifest comparison (identical, differing, zero-frame guard), visual
  metric deltas and the report's environment block.
  `tests/test_motion_canvas_reproducibility.py` renders the same scene twice on
  Linux when `LCES_MC_REPRO=1`; it records the measured byte-identical rate
  instead of asserting one. CI runs it from the manual `reproducibility` input.
