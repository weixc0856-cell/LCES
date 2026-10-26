# Architecture

## Scope

This file describes the implementation as it exists. The product goal and deliverables
are defined in [`PRODUCT.md`](PRODUCT.md); the quality standard is [`QUALITY.md`](QUALITY.md).
Those two files and this one are the only authoritative documents. If this file and
`PRODUCT.md` disagree, `PRODUCT.md` wins and this file is wrong.

## Goal

Turn external material into a traceable course package while keeping public and
internal assets structurally separate. Phase 1 implements one reliable
end-to-end path; it does not attempt a general agent platform.

## Modules

| Layer | Module | Responsibility |
|---|---|---|
| CLI | `cli.py` | Commands, exit codes, human-readable gate output |
| Orchestration | `orchestrator.py` | Stage selection, status transitions, failure recording |
| Ingestion | `ingestion.py` | Local/URL/PDF/DOCX/HTML/Markdown acquisition, hashing, snapshots |
| Research | `research.py` | Claims, evidence ledger, research brief, unknown/conflict tracking; model-reported review states are reset |
| Evidence review | `evidence.py` | Canonical review states, named-reviewer rule, `lces review-claims` |
| Media checks | `media.py` | ffprobe metadata, FFmpeg frame sampling, SRT/VTT timing; used by Gate 4 |
| Tool layer / MCP | `tools.py`, `mcp_server.py` | Pydantic-validated tools with read/write access, JSONL audit log, optional stdio server |
| Evaluation / cost | `eval.py`, `usage.py` | Fixed benchmark set with mechanical checks; token, failure, time, and cost report from `stage_runs` |
| Content | `content.py` | Outline, public content, speaker script, reading edition |
| Rendering | `rendering.py` + `templates/` | Public HTML from public-only models |
| Teaching units | `units.py` | Materialises one `LearningUnit` per delivered scene; keeps the paper blueprint and writes `internal/plan/course_master.generated.json` with input fingerprints |
| Scene contracts | `scenes.py` | Generates a `ScenePlan` from delivered units (authored steps override per scene), validates one `SceneContract` per slide and writes the contracts/plan artifacts |
| Duration budget | `duration.py` | Unit weights → per-unit seconds; keeps estimates, TTS measurements and animation time separate |
| Narration expansion | `expansion.py` | Evidence-constrained unit expansion with visual-sync, length, duplicate and number guards; atomic writes and rejection log |
| Providers | `providers/` | Provider-neutral interface; DeepSeek, Anthropic, local llama.cpp, Mock |
| Routing | `routing.py` + `config/routing.yaml` | Opt-in per-stage provider selection (research/outline/generate) |
| Storage | `storage.py` | SQLite tasks, stage runs, events, assets, approvals |
| Validation | `validation.py` | Gates 1–4, marker/secret scans, manifest verification |
| Release | `release.py` | Approval, staging, manifest, ZIP |
| Contracts | `models.py` | Pydantic models; JSON Schema source |
| Course audit | `course_audit.py`, `number_audit.py` | Deterministic course↔evidence audit: BLEU values, conflicts, conditions, formula matching, number coverage, LaTeX leakage, external assets, protected conditions; report bound to file hashes |
| Gate B | `course_quality.py` | Course product contract, coverage, deliverables, timing evidence, human acceptance |
| Motion Canvas | `motion_canvas.py`, `motion_templates.py`, `timeline.py`, `frame_manifest.py`, `encode.py`, `video_qa.py` | Frame rendering, manifest, encoding and video QA through one adapter |
| Visual QA | `visual_qa.py`, `visual_baseline.py`, `visual_acceptance.py` | Automatic frame metrics, baseline drift, human acceptance |
| Typesetting | `latex_render.py` | Build-time LaTeX subset → semantic HTML; unsupported commands fail the build |

## Data flow

```
input/ ──ingest──> internal/source_registry.json + internal/sources/*.txt
                         │                    + internal/source_map.json
                         │
                    research (model, one call per chunk window)
                         ▼
        internal/research_analysis.json, evidence_ledger.csv, research_brief.md
        internal/plan/paper_map.extracted.json (paper_map.json if no blueprint)
                         │
                     outline (model)
                         ▼
                content/outline.json
                         │
        ┌────────────────┼──────────────────┐
        ▼                ▼                  ▼
 content/public_content.json  internal/speaker_script.json  content/reading_edition.json
        │                (never rendered)          │
        └─────────────► build/ ◄───────────────────┘
                         │
                    validate (gates 1–3)
                         ▼
              internal/qa/qa_report.json
                         │
              approve (human) + release (gate 4)
                         ▼
              release/v1/ + build/artifacts/*.zip
```

Ingestion writes a `SourceMap` (`internal/source_map.json`) with page, section
and chunk boundaries while the raw document is still available. Research packs
whole chunks into windows and makes one model call per window; no stage
truncates the source head. `SectionAnalysis` results are merged deterministically
(global claim/evidence IDs, deduplicated statements) and every call is recorded
in `research_analysis.json`.

## Public/private boundary

The central invariant is a type boundary, not a naming convention:

- `PublicContent` contains only displayable fields (`extra="forbid"`).
- `SpeakerScript` is a separate model persisted under `internal/`.
- `build_public_html()` accepts only `PublicContent`.
- `release.py` rebuilds a staging tree from explicit sources; it never copies
  the working directory.
- Gate 4 rejects anything outside the allowlist, internal markers, secret
  patterns, hash mismatches, and missing human approval.

Blacklist scans are a second line of defence. They are not the mechanism that
keeps narration out of HTML.

## Provider neutrality

`ModelProvider.generate()` and `generate_structured(request, Schema)` are the
only entry points used by business code. The base class adds JSON instructions,
parses fenced/prose-wrapped JSON, validates with Pydantic, and makes one repair
attempt. Adapters own transport, auth, timeouts, retries, and usage extraction.

Every generation request carries an explicit output budget. The orchestrator
passes `Settings.max_output_tokens` into research, outline, public content,
speaker script, and reading edition. Responses keep the provider's
`finish_reason` and request id; a `length`/`max_tokens` stop raises
`OutputTruncatedError` before the JSON repair loop, because retrying the same
request would truncate at the same point. The caller must raise the budget or
split the unit.

The local adapter targets llama.cpp `llama-server` (OpenAI-compatible `/v1`),
discovers the loaded model from `/v1/models`, supports an optional `--api-key`,
and never sends loopback traffic through the OS proxy. Model routing is opt-in
and stage-scoped; deterministic stages never construct a model provider.

## Course planning contracts

`PaperMap`, `CoverageMatrix`, `LearningUnit`, and `CourseMaster` describe what
a course must cover before any unit text exists. They are internal-only
(`internal/plan/` and `internal/course_master.json`) because they carry evidence
and claim references; a `LearningUnit` may hold both public blocks and
narration, and the assembler — not a template — splits it. The Attention
blueprint is frozen under `tests/fixtures/course_plan/attention/`; all units
are `planned` with empty bodies and all paper elements stay `unverified` until
research or a human records evidence. Unit-level generation, the unit queue,
and the derivation of `PublicContent`/`SpeakerScript` from `CourseMaster` are
not implemented yet.

## Content and visual contracts

Content models describe what a course says. Visual output goes through a
separate contract: `visuals.py` derives a `VisualSpec` for each table and
figure block, `renderers.py` resolves the spec through a registry keyed by
`visual_type`, and the renderer owns escaping plus its own validation. A
`render_manifest.json` records renderer name, version, schema version, and
output hash per fragment.

Unknown visual types raise `UnsupportedVisualType` and fail the build; they are
never rendered as empty placeholders. Statistical charts are described as
Vega-Lite documents and rendered to static SVG by `vl-convert` (no Node.js or
network); custom SVG files are inlined only after XML and safety checks. The
template still contains the previous inline branches so `use_registry=False`
can reproduce the old output for parity tests. See
`docs/CONTENT_CONTRACTS.md` for the version policy.

## Local/cloud split

`config/routing.yaml` can send research to a cloud model while drafting stays
local. A stage entry may also name a fallback provider: a provider error after
the adapter's own retries triggers one retry with the fallback, and both
attempts stay in `stage_runs`. `lces models` probes `/health` and
`/v1/models` without making a completion request. Each stage records provider,
model, and token usage in SQLite, so a mixed run remains auditable. Escalation
based on eval scores or a cost budget is not implemented.

## State machine

`CREATED → INGESTING → RESEARCHING → PLANNING → GENERATING → VALIDATING →
REVIEW_REQUIRED → RELEASED`, with `FAILED` and `NEEDS_REVISION` reachable from
any stage. Each stage run is recorded with provider, model, usage JSON, error,
and timestamps.

Resuming is stage-scoped: `lces run --from-stage outline` rebuilds the
downstream assets without re-fetching sources.

## Scene contracts and the deck runtime (2026-10-24)

`scenes.py` derives one `SceneContract` per public slide and validates it before
HTML is written: every step points at a real block, every claim reference exists,
every evidence reference resolves, and every scene has a narration section when a
speaker script exists. An optional `content/scene_plan.json` names the steps and
effects; blocks it omits are still revealed, never dropped. The build writes the
contracts to `internal/qa/scene_contracts.json` and embeds them in the page as
JSON, so the deck and the video pipeline share one idea of a scene.

The deck runtime (`templates/public_html/course.html.j2`) exposes
`window.__lces` with `play`, `pause`, `replay`, `reset`, `seekStep`, `next`,
`prev`, `advance`, `gotoScene`, `setRecord` and read-only state. A single
requestAnimationFrame clock drives step transitions; CSS only animates the
appearance, so a paused or reset scene has a deterministic class state. Record
mode (`?record=1` or `R`) hides the bar, footer and lab controls and fits the
16:9 stage to the viewport (`stage` is exactly 1920x1080 at a 1920x1080 window).

## Units, generated plans and incremental generation (2026-10-24)

`units.py` materialises the delivered course: for every public slide it creates a
`LearningUnit` in a delivered chapter (`unit-101…`), copies no body or narration,
links `scene_ids`, and records a SHA-256 fingerprint over the slide, narration,
referenced claims and evidence. The paper-coverage blueprint
(`internal/course_master.json`) is preserved as chapters/units/coverage; the
generated master adds the delivered units. This is deliberately one master with
two views, not two files that can disagree.

`scenes.py` turns those units into a `ScenePlan`: step order follows the authored
block order (checks last), effects come from the block type, labels from the
block's own text, and durations from the unit's estimated minutes. An optional
`content/scene_plan.json` overrides individual scenes; every other scene stays
generated. The build writes `internal/qa/scene_plan.generated.json`, writes the
contracts, and embeds them in the page. A course with no authored plan builds
all 14 scenes from generated plans (verified on the Attention course).

Incremental generation is fingerprint-based: `lces plan-impact` lists units whose
inputs changed (a claim edit invalidates every unit that references it), and
`lces generate --unit <id>` regenerates only that unit's scenes, updating only
those fingerprints. An unchanged unit is skipped unless `--force` is passed.
Failed generation writes nothing, and the generated master/plan contain no
timestamps, so repeated builds are byte-identical.

## Duration budget and expansion loop (2026-10-24)

`duration.py` allocates the contract target across delivered units by teaching
weight (objectives, concepts, formulas, visual blocks, claims, checks), with a
45–480 s floor/ceiling. It keeps the planning estimate, the TTS measurement and
the per-step animation durations in separate fields. A TTS record is only used
as a measurement when its `script_sha256` matches the current speaker script.

`expansion.py` expands one unit's narration under its own evidence. The provider
may only use the unit's claims and evidence; the program then refuses an output
that misses a required visual-sync block, falls outside the budget length, repeats
a sentence, leaks an internal id, or states a number absent from the evidence.
A rejected output is logged with its raw model text and never touches the script.
Failures are repaired by appending the missing explanation (up to three attempts)
and re-validating the merged result. `lces duration-plan` reports the gap,
`lces expand-unit` expands one unit, and `lces rebalance` runs expansion → TTS
measurement → re-evaluation for at most two rounds. TTS failure leaves timing
`NOT_RUN`; estimates are never promoted to measurements.

`audit-product` now exposes two decisions: `decision` (release, including human
records) and `production_decision` (automated findings only, with human items as
disclosures). `--production` exits 0 when automated production quality passes;
build, playback and recording never consult approval state.

## What is still absent (2026-10-24)

Browser QA, Motion Canvas frame export, FFmpeg encoding, video QA, visual
baselines and human visual acceptance are implemented and covered by tests. The
remaining gaps are listed with IDs in [`QUALITY.md`](QUALITY.md) §6:

- **One real course** — only the Attention course exercises the full path (Q-06).
- **`superseded` review state** — old reviews are rejected by version binding,
  but there is no explicit superseded record (Q-07).
- **LangGraph, web UI, automatic quality routing** — not implemented (ADR 0007).

Everything in this list reports `NOT_RUN` / `Partial`; none of it may be described
as passing.

## Run records (2026-10-24)

Each pipeline run stores `run_id`, an input fingerprint (`source_registry.json`
after ingestion, configured files/URLs before it) and a safe config snapshot
(provider, model, stages, routing file name; no secrets). Each stage stores
provider/model, usage, `error_class` (bounded vocabulary from
`errors.classify_error`), `retry_count` (0 for the first attempt, 1 for the
routing fallback) and the output artifact paths that exist. Existing SQLite
files gain the columns on open (`_ensure_columns`), so old databases keep their
rows. `lces status --task <id>` prints the lineage. This closes the run-record gap; cross-process recovery is still absent (ADR 0007).

## Release binding (2026-10-24)

`lces validate` now stamps `QAReport.content_version`, a SHA-256 over
`content/public_content.json`, `content/reading_edition.json`, `content/outline.json`,
`internal/speaker_script.json`, `build/slides/index.html` and
`build/reading_edition.html`. `build_release` recomputes it and refuses a report
that is unbound or stale. A published `release_manifest.json` with
`manifest_schema_version: "2.0"` records the course contract version, content
version, Git revision, source-registry hash, Gate B report and human-acceptance
hashes, the product decision and every `NOT_RUN` limitation. Version 1.0 manifests
stay readable and are verified by the older rule set; they are not relabelled.
See ADR 0010.

## Development rules

- Python 3.13 and the repository-local `.venv/`; use `uv sync` then `uv run …`.
- Public functions carry type hints; external data is validated with Pydantic at the boundary.
- Expected failures raise `LCESError` subclasses; never swallow an exception silently.
- Never log or persist API keys, authorization headers, or prompts containing secrets.
- Only `release.py` writes `release/`; content modules never do.
- New release-blocking rule ⇒ new test. A rule that is not implemented reports `NOT_RUN`.
- `lces validate` stamps `QAReport.content_version`; re-run it after any content or build
  edit. `build_release` refuses an unbound or stale report.
- Do not weaken a gate, tolerance or baseline to make a run green. Record the defect and
  fix it; the guard tests are listed in [`QUALITY.md`](QUALITY.md) §7.
- `python scripts/check_docs.py` must pass: links resolve, documented `lces` commands
  exist, and the required documents are present.

## Decision records

Architecture decisions live in [`ADR/`](ADR/). They are records, not plans: a new ADR
supersedes an old one, and the old text is not rewritten.

| ADR | Decision |
|---|---|
| 0001 | Provider-neutral model interface |
| 0002 | Public/private asset boundary |
| 0003 | Modular monolith with explicit layers |
| 0004 | Course master as the single source for derived deliverables |
| 0005 | Scene contract (fields partially implemented; Q-01) |
| 0006 | Reuse SVG/CSS/Canvas/Motion Canvas instead of one engine per course |
| 0007 | No LangGraph, web UI or automatic quality routing yet |
| 0008 | JSON + SQLite persistence |
| 0009 | Three independent visual layers (metrics / baseline / human) |
| 0010 | Release manifest bound to content, course and code lineage |
| 0011 | Third-party skill review and license registration |
| 0012 | Real-course and regression-set acceptance |
