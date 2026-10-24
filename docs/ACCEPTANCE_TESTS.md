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
| `lces export-schemas` | 26 schemas, including asset/scene/video, source-map, quote-audit and course-planning contracts |
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
- Motion Canvas manual acceptance (P2.4-D): `tests/test_visual_acceptance.py`
  covers the record schema and validation, toolchain matching, the CLI writer
  and Gate 4's warn/fail/pass branches. A machine may fail an asset; only
  `lces accept-visual` can record a human `pass`.

- Motion Canvas materials (P3-A): `tests/fixtures/motion/` holds seven
  representative scene contracts and a sha256 manifest.
  `tests/test_motion_materials.py` checks the hashes, contract validity,
  expected frame counts and template coverage, so an accidental input change
  fails before any render runs.

- Motion Canvas material renders (P3-A): `tests/test_motion_canvas_materials.py`
  validates every frozen material through the adapter on all platforms and,
  with `LCES_MC_MATERIALS=1`, renders the set on Linux, checking frames,
  resolution, fps, decode and visual QA and emitting a per-material report.
  CI exposes it through the manual `materials` input.

- Motion Canvas resource baseline (P3-B): `tests/test_resource_probe.py` covers
  the probe's sampling and its `unavailable` semantics (a failed measurement is
  never zero). `tests/test_motion_canvas_stress.py` renders the 1 s / 10 s /
  60 s tiers with `LCES_MC_STRESS=1`, repeating the longer tiers, and records
  timing, process-tree resources, disk, artifacts and environment.

- Motion Canvas fault injection (P3-C): `tests/test_motion_canvas_faults_p3.py`
  (with `LCES_MC_FAULTS=1`) covers timeout, cancel during render, cancel during
  encode, retry after failure and a read-only media directory; each case asserts
  the terminal error, the untouched old video and no staging leftovers.
  `tests/test_encode.py` covers encoder exit/timeout/cancel and the disk-full
  mapping.

- Research quotes (Gate 1): `tests/test_evidence.py` checks that an evidence
  excerpt which does not appear in the extracted source is flagged, while
  whitespace/case variants pass and a missing source text skips the check.
  The local course trial's six quotes pass this check against the paper text.

- Source maps (P0-B2): `tests/test_source_map.py` covers contiguous chunk
  tiling, the 2000-character limit, page numbers, rejection of page texts that
  do not reconstruct the stored source, backfill for old projects, CRLF
  robustness, heading detection in single-newline HTML extracts, false
  positives (figure labels, author blocks, table values), and a placeholder
  chunk for scanned PDFs with no extractable text.
- Sectioned research (P0-B2): `tests/test_sectioned_research.py` asserts every
  chunk is sent whole exactly once, no truncation marker appears, claim and
  evidence IDs are renumbered and remapped, duplicate statements collapse
  while their evidence is kept, every model call is traced with
  `finish_reason`/usage, and a human-authored `paper_map.json` is not
  overwritten.
- Coverage planning (P0-B2): `tests/test_planning.py` rebuilds the Attention
  coverage matrix from the blueprint, detects required gaps and unknown paper
  items, and covers the Gate 2 `pass` / `fail` / `not_run` branches.
  `lces plan-coverage` writes the matrix and exits non-zero when a required
  element has no teaching unit.

- Research trial report (P0-B2.1): `scripts/analyze-research-trial.py` is a
  read-only summary of one real run: calls and chunk ranges, exactly-once
  chunk coverage, claim/evidence linkage, quote checks against the stored
  text, evidence per section, key-fact string presence, and claim types. It
  does not modify the project and is not a substitute for human review.

- Research hardening (post-trial): `tests/test_sectioned_research.py` covers
  bibliography exclusion (`excluded_chunks` and no References chunk sent),
  section-focused windows, unlocatable candidates staying out of the ledger,
  merged-claim counting and per-call traces. `tests/test_providers.py` covers
  usage summed across every structured call in a stage.
- Two-window locator trial: `scripts/trial-quote-locator.py` sends only §3.2.x and
  §6.1/§6.2 to the model and writes a candidate/status/audit report under
  `var/quote-locator-trial/` without modifying the project.
- Structured formula/table evidence: `tests/test_structured_evidence.py`
  covers table row structural checks, column-semantics review, prose scope,
  wide spans, split rows, missing values, unknown table IDs, no PaperMap,
  formula normalization without semantic pass, missing symbols, and audit
  merging; `tests/test_sectioned_research.py` checks that table rows stay out of
  the formal ledger without column semantics, and that structured fields survive
  the CSV round-trip.
- Section-level resolution: `tests/test_evidence_locator.py` covers a wrong
  chunk with the correct section resolving to the actual chunk, and a quote
  spanning two chunks in the named section staying `needs_review` (no joins).
- Deterministic quote locator (P0-B2.2): `tests/test_evidence_locator.py`
  covers exact and normalized matches with source-sliced excerpts, ambiguity,
  short candidates, cross-chunk joins, unknown claim/source/chunk rejection,
  math-symbol mismatches going to review, and audit counts/reasons. Research
  integration asserts only verified evidence reaches `evidence_ledger.csv` and
  that failures land in `internal/qa/quote_audit.json`.

- Course content audit and release gate (2026-10-24): `tests/test_course_audit.py`
  covers undisclosed 41.0/41.8 conflicts, unreviewed BLEU values, Table 3
  `BLEU (dev)` mislabelled as a test-set result, formula denominator and
  transpose changes, `\frac`/`√` normalisation, unreviewed and absent formulas,
  missing source text, missing locators, stable finding IDs, audit staleness
  after a content edit, release refusal while evidence is unsigned, release
  refusal for an undisclosed conflict, release success after a human signature,
  and the AI review layer never becoming a human signature. The real project's
  acceptance record is
  [`docs/design/release-acceptance-2026-10-24.md`](design/release-acceptance-2026-10-24.md).


- Course product qualification (P5): `tests/test_course_quality.py` covers the
  product contract (missing contract, target downgrade, objective coverage,
  modules, formulas, learning checks), measured vs estimated timing, the
  human acceptance record and its content-version binding, Gate B release
  blocking, the contract-less `NOT_RUN` path, and the `CheckBlock` rendering.
  The real-course result is
  [`docs/design/course-product-qualification-2026-10-24.md`](design/course-product-qualification-2026-10-24.md).

- Human acceptance preparation (P6): `tests/test_review_packets.py` covers
  packet source slices and `unresolved` handling, course-usage matching,
  stable content hashes, the index, empty signature fields and the
  `export-review-packets` CLI. The P6 execution report is
  [`docs/design/p6/p6-execution-2026-10-24.md`](design/p6/p6-execution-2026-10-24.md).
