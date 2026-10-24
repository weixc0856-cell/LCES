# Content and Visual Contracts

Phase 2 separates three things that used to live in one HTML template:

1. **Content** — `PublicContent` / `ReadingEdition` say *what* a course contains.
2. **Visual specs** — `VisualSpec` says *how* one visual is described and which
   renderer should produce it.
3. **Renderers** — `renderers.py` turn a spec into an artifact and own their
   escaping, validation, and version.

## Source maps and sectioned research (P0-B2)

`SourceMap` (`internal/source_map.json`) records how each stored source text is
tiled. Every `SourceChunk` carries a stable `chunk_id` (`source-001:b0007`), a
page number (PDF only), the section label, and exact `char_start`/`char_end`.
Chunks are contiguous, never exceed 2000 characters, never cross a PDF page
boundary, and together cover the whole text. The stored `.txt` remains the
quote source of truth; the map only records where each slice came from.

Ingestion writes the map while page numbers are still available. Older
projects are backfilled by `ensure_source_map`; page texts that do not
reconstruct the stored text raise an error instead of producing wrong offsets.

Research no longer truncates the head of a source. `run_research` packs whole
chunks into windows bounded by `LCES_LOCAL_PROMPT_CHAR_BUDGET` (or
`LCES_PROMPT_CHAR_BUDGET` for cloud providers), sends one `SectionAnalysis`
call per window, and merges the results. Windows are also focused by section:
a new section segment opens a new window once the current one has at least
`max(3000, budget // 3)` characters and two segments. A table of contents does
not poison this count because the packer counts segment changes, not unique
labels.

- Bibliography, acknowledgement and author-affiliation sections are not sent
  to the model. Their chunks are recorded in `excluded_chunks` with a reason,
  so "not sent" is distinguishable from "silently lost".
- claim/evidence IDs are assigned globally (`claim-001`, `evidence-001`) and
  the local IDs from each call are remapped. A duplicate statement collapses
  to one claim, while its distinct evidence rows are kept.
- evidence that names an unknown source or claim is dropped and counted; the
  locator comes from the chunk header (section or page).
- every excerpt is checked against the window text after whitespace, case and
  typography normalization. A non-verbatim excerpt is kept but flagged in
  `notes` and counted in `non_verbatim_evidence`; it is never presented as a
  verified quote. Gate 1 still reports it.
- paper elements found in a window are merged into
  `internal/plan/paper_map.extracted.json`. `paper_map.json` is written only
  when no human-authored blueprint exists, so a blueprint is never replaced by
  model output.

`internal/research_checkpoint.json` is rewritten after every completed window
with the calls, claims, evidence, paper elements, exclusions and counters so
far. It is evidence of progress, not a resume contract yet: a later window can
fail (timeout, truncation) without erasing what earlier windows produced.

`research_analysis.json` records `research_calls`: one entry per model call
with chunk range, section, pages, provider, model, usage, `finish_reason`,
`request_id` and the non-verbatim evidence IDs, plus `usage` totals,
`merged_claims`, `non_verbatim_evidence` and `excluded_chunks`. A response
stopped by the output budget still raises `OutputTruncatedError` and is never
merged.

## Deterministic evidence locator (P0-B2.2)

The model proposes a quote; it does not produce formal evidence. `evidence_locator.py` checks every
`QuoteCandidate` against the current window:

- The candidate can name a `chunk_id`, a `section_id`, or a section in `locator`
  (`§3.2.1 ...`). When it names a section, the locator searches that section's chunks but
  accepts only a quote that fits wholly inside **one** chunk; the accepted record stores the
  resolved `chunk_id` and `resolved=True`. It never searches another section and never joins
  chunks. Ambiguous or missing matches stay `needs_review`.
- The claim must exist in the same `SectionAnalysis`, and the source must exist in the registry;
  otherwise the candidate is `rejected` with a reason.
- Exact match → `verified_exact`; typography-only normalized match → `verified_normalized`;
  not found, ambiguous, or shorter than 12 normalized characters → `needs_review`.
- The formal `source_excerpt` is sliced from the source text at the located offsets. The model's
  candidate text is never copied into the ledger.
- Only verified candidates enter `evidence_ledger.csv`; `quote_status` records `verified_exact` or
  `verified_normalized`. Review and rejected candidates go to `internal/qa/quote_audit.json` with
  their reason and candidate text.
- There is no fuzzy acceptance. Math symbols, table reordering, ellipses and cross-chunk joins do
  not pass; they go to review.

`EvidenceRecord` now carries `chunk_id` and `quote_status`; rows from older projects default to
`unverified`. The research trace records per-call `quote_audit` counts, and
`research_analysis.json` carries the merged `quote_audit` summary.

## Structured formula and table evidence (stage B)

Free-text quotes cannot represent a formula or a table row reliably: the source
text keeps subscripts, duplicated LaTeX fragments and table layout that no
contiguous quote can match. `EvidenceRecord` therefore gains two optional
structured objects:

| Field | Shape |
|---|---|
| `formula` | `formula_id`, `expression`, `symbols[]`, `locator` |
| `table` | `table_id`, `row_label`, `column_label`, `value`, `unit`, `variant`, `locator` |

Validation (`structured_evidence.py`):

- `formula_id` / `table_id` must resolve to a `PaperMap` element of the matching
  kind (`equation` / `table`); without a PaperMap the candidate is
  `needs_review` (`no_paper_map`).
- A **table** candidate carries `scope` (`cell` / `row` / `prose`),
  `table_id`, `row_label`, `column_label`, `value`, `unit`, `variant` and
  `locator`. A row label and value in one chunk with a span ≤120 characters is
  only a **structural** check; it is recorded as `needs_review` with
  `column_semantics_unverified`. A row split across chunks is
  `needs_review` (`table_row_split_or_missing_value`); a wide label→value span
  is `needs_review` (`table_row_span_too_wide`); `scope=prose` is
  `needs_review` (`prose_not_table_cell`). `verified_structured` is reserved
  for a future cell-column parser that maps the table header to the cell; the
  current program does not emit it for tables.
- The excerpt is still sliced from the source for review, but no table evidence
  enters the formal ledger on row/span alone.
- A **formula** checks the element, expression and symbol presence only. It
  never becomes `verified_structured`; it is `needs_review`
  (`formula_semantics_manual` or `formula_symbols_not_found`). The algebra must
  be reviewed by a human.
- `verified_structured` is the only additional value accepted in the evidence
  ledger's `quote_status`; review/rejected structured candidates are written to
  `internal/qa/structured_evidence_audit.json`.
- The evidence CSV stores the structured object in `structured_json` so the
  ledger remains one file.

`verified_structured` means "the named element exists and the row/values are in
one source chunk", not "the table semantics are correct". Formula semantics and
table meaning remain human review.

## Human review records (P2)

`ReviewDocument` / `ReviewItem` in `structured_review.py` store the human
review of structured evidence. They deliberately separate three layers:

| Layer | Field | Meaning |
|---|---|---|
| Program location | `EvidenceRecord.quote_status` | `verified_exact` / `verified_normalized` / `verified_structured`; a deterministic check, not truth |
| Research verification | `ResearchVerification.research_finding` | `verified` / `needs_review` / `source_conflict` / `incorrect` / `not_verifiable` against an external source |
| Human signature | `ReviewItem.conclusion` + `reviewer` + `reviewed_at` + `basis` | The only field that counts as a human decision |

Rules enforced by `lces review-evidence` and `structured_review.py`:

- A signed item needs `reviewer`, `reviewed_at`, `conclusion` and `basis`; missing
  any field is rejected.
- The item must link to a real `source_id` + `chunk_id`, and to a `claim_id` or a
  window-local `claim_ref`; a `paper_id` must exist in the paper map.
- A `source_conflict` item cannot pass without `conflict_acknowledged=True`.
  Competing values are preserved with their sources and locators; the program
  never picks one automatically.
- `research_finding=verified` never changes `reviewed_by_human` or the human
  conclusion. Formula research records keep the original expression,
  transcription, symbol/dimension/derivation checks and limitations.
- Writes are atomic and append `internal/qa/evidence_review_audit.jsonl` with
  before/after conclusion, reviewer and basis.

## Coverage planning and the Gate 2 check

`lces plan-coverage <project>` derives `internal/plan/coverage_matrix.json`
from `PaperMap` + `CourseMaster`. Each unit's `paper_item_ids` becomes
`covered_by`; a required element with no unit becomes `missing`; notes from a
previous matrix are preserved. The matrix is pinned to the paper map by
SHA-256.

Gate 2 adds `coverage_matrix_complete`:

- `PASS` when every required paper element is covered and the hash matches.
- `FAIL` when a required element has no unit, a unit names an unknown paper
  item, or the matrix was built against a different paper map.
- `NOT_RUN` when any of the three planning files is absent — absence of
  planning data is not evidence of coverage.

## Course planning contracts (P0-A)

Four internal contracts describe *what a course must teach* before any unit
text is generated. They are exported by `lces export-schemas` as
`paper_map`, `coverage_matrix`, `learning_unit`, and `course_master`.

| Contract | Purpose | Stored under |
|---|---|---|
| `PaperMap` | Paper sections, formulas, figures, tables, experiments, results, ablations, limitations and conclusions, each with a locator, `required` flag and status | `internal/plan/paper_map.json` |
| `CoverageMatrix` | Maps every paper element to the units that teach it; pinned to the exact paper map by SHA-256 | `internal/plan/coverage_matrix.json` |
| `LearningUnit` | The unit of generation and review: objectives, key concepts, public blocks, narration, evidence/claim refs, visual needs, status and revision | merged into `internal/course_master.json`; per-unit drafts are a later phase |
| `CourseMaster` | Single internal course source: chapters, ordered units, coverage, sources and references | `internal/course_master.json` |

Rules:

- A paper element is never silently dropped. `PaperElement.status` separates
  `verified`, `unverified`, `not_found`, `not_applicable` and `needs_review`;
  a model finding nothing must record `not_found`, not omit the element.
- `CoverageEntry.status` must match `covered_by`: `covered`/`partial` need at
  least one unit, `missing`/`not_applicable` name none.
- A `LearningUnit` is not a slide. One unit may span several slides and one
  simple conclusion may occupy a single unit. Only units in
  `generated`/`validating`/`approved` status may carry a body.
- `CourseMaster.chapters` order and `unit_ids` must match `units` exactly;
  coverage entries may only reference units that exist in the same master.
- `LearningUnit` is internal: `body` is public, `narration` and the
  evidence/claim references are not. The assembler splits it into
  `PublicContent` and `SpeakerScript`; no template receives a unit directly.
  Deriving those files from the master is a later phase, not implemented yet.

The `Attention Is All You Need` blueprint is frozen as a tracked fixture under
`tests/fixtures/course_plan/attention/`. It has 12 chapters, 25 planned units
(81 minutes), 30 paper elements and complete required coverage. All units are
`planned` with empty bodies and all paper elements are `unverified`; it is
planning data, not generated course content.

## Asset, scene, and video contracts (PRD 2 module 1)

Three additional contracts describe rendered artifacts and video builds. JSON
Schemas are exported by `lces export-schemas`.

**`VisualAsset`** records one visual artifact: `asset_id`, `asset_type`,
`source`, `renderer` + `renderer_version`, `parameters`, `dependencies`,
`evidence_refs`, `output_paths`, `status`, `qa_results`, `source_hash`,
`output_hashes`, `created_at`, `build_id`. All path fields are validated as
workspace-relative: absolute paths, drive letters, and `..` are rejected.

After each public build, `internal/qa/visual_assets.json` contains one asset
per rendered fragment. Inline fragments hash the built page that embeds them;
chart assets list their SVG artifact instead.

**`SceneContract`** describes one shot: `scene_id`, `scene_type`,
`duration_ms` (integer milliseconds, never float seconds), `renderer`, source
asset refs, narration/subtitle refs, transitions, camera config, evidence refs,
quality profile, and `fallback_policy` (`fail` / `skip` / `placeholder`).

**`VideoContract`** describes a video build: canvas size, rational frame rate
(`fps_num`/`fps_den`, so 30000/1001 is exact), colour space and pixel format,
scene order, narration/audio refs, subtitle language and format, audio sample
rate and channels, codec and preset, renderer version, output path, QA report
ref, provenance/licence, build parameters and hash.

Unknown enum values, unsupported schema majors, empty scene lists, and
non-positive durations fail validation before any renderer runs.

## Renderer interface (PRD 2 module 2)

Each renderer implements, beyond `render`/`validate`:

| Hook | Purpose |
|---|---|
| `validate_input(spec)` | Reject bad parameters before rendering starts |
| `check_environment()` | Report missing tools or versions (`vl-convert`, FFmpeg, …) |
| `estimate_resources(spec)` | Rough CPU seconds / memory, with a note |
| `cancel()` | Best-effort cancellation hook |
| `collect_outputs(spec, context)` | Artifact paths produced by the render |
| `get_diagnostics()` | Last recorded failure context |

The registry enforces order: registered type → explicit renderer match →
environment → input validation → render → output validation. Any failure is
appended to `registry.diagnostics()` with the visual id, stage, and renderer.
The registry never substitutes another renderer silently.

## Schema versions

`VisualSpec.schema_version` defaults to `1.0` (`VISUAL_SCHEMA_VERSION` in
`models.py`). Only the major version `1` is accepted; anything else fails
validation with an explicit error. Compatibility policy:

- Adding optional fields or new `visual_type` values: minor version unchanged.
- Changing the meaning of `data` for an existing type: bump the major version
  and keep the previous renderer registered under a new `visual_type` until
  projects migrate.
- Removing a field: major version bump; old specs must be converted, not
  silently dropped.

JSON Schema for the contract is generated by `lces export-schemas`
(`schemas/visual_spec.schema.json`). Do not hand-edit it.

## Visual spec shape

```json
{
  "schema_version": "1.0",
  "visual_id": "slide-003-block-01",
  "visual_type": "table",
  "title": "架构复杂度对比",
  "renderer": "",
  "data": {"caption": "", "columns": ["a", "b"], "rows": [["1", "2"]]},
  "validation": {"required": true, "status": "pending", "message": ""}
}
```

- `visual_type` selects the renderer through the registry.
- `renderer` is optional; when set it must match the resolved renderer name or
  rendering fails. The registry never silently substitutes another renderer.
- `data` holds structured values only. Renderers must not invent or coerce
  facts that are absent from it.
- `validation.status` is written by the render/QA pipeline. Model output cannot
  set an approved release state.

## Registered renderers

| visual_type | renderer | version | Notes |
|---|---|---|---|
| `table` | `html.table` | 1.0.0 | Escapes every cell; validates row width |
| `figure_image` | `html.figure` | 1.0.0 | Requires the asset under `content/`; escapes path/alt/caption |
| `custom_svg` | `svg.custom` | 1.0.0 | Inlines an XML-valid SVG from `content/`; rejects scripts, event handlers, `foreignObject`, and external references |
| `data_chart` | `vega_lite.chart` | 1.0.0 | Renders a Vega-Lite spec to static SVG with `vl-convert`; no Node.js or network |
| `diagram` | `mermaid.diagram` | 1.0.0 | Renders Mermaid source with the vendored runtime (`vendor/mermaid`, 12.2.0, MIT) in offline Chromium; strict config, no init/click directives |
| `graph` | `graphviz.dot` | 1.0.0 | Renders DOT with an external Graphviz (`LCES_DOT_BIN` or `dot` on PATH, >= 2.40); missing `dot` is an environment failure, never a silent fallback |
| `animation` | `motion_canvas.renderer` | 0.1.0 | Renders one structured scene file to `build/media/course.mp4` through Motion Canvas + system FFmpeg (Linux only); failures never fall back to a template or a placeholder |

Mermaid is delivered with the repository and verified against
`vendor/mermaid/manifest.json` (sha256) before every render; see that
directory's README for the upgrade procedure. Graphviz is a system dependency
and is not vendored — `lces doctor` reports whether it is available. The CI
`graphviz` job has accepted the adapter on Graphviz 2.43.0 (real `dot`
rendering, 14/14 tests); the Windows 16.1.0 local install is still pending.
See `docs/design/graphviz-acceptance.md`.

`data_chart` and `custom_svg` need their optional extras:

```powershell
uv sync --extra charts      # vl-convert-python for data_chart
```

Without the extra, rendering `data_chart` raises a `RenderError` that names the
install command; it never returns an empty chart. Every inline SVG gets
`role="img"`, `aria-label`, and `max-width:100%` so a fixed-width chart cannot
overflow a narrow viewport.

Rendering rules enforced in code:

- Unknown `visual_type` raises `UnsupportedVisualType` and fails the build; it
  never renders an empty placeholder.
- A renderer's `validate()` runs after `render()`; any problem raises
  `RenderError`, so malformed output cannot be reported as success.
- Renderer name and version are recorded per fragment.
- Values interpolated into HTML are escaped by the renderer because templates
  insert the fragment with `| safe`.

## Animation blocks and the production build (P2.1)

`PublicContent` gains one block:

```json
{"type": "animation", "scene_file": "content/scenes/course.json", "alt": "系统流程", "caption": ""}
```

- `scene_file` must be a workspace-relative `.json` under `content/scenes/`;
  it holds `{"scene_set": {...}, "video": {...}}`, the same structure the
  `lces render-scene` command accepts.
- `video.project_id` must match the project, `video.scene_ids` must match the
  scene order, and `video.output_path` must be `build/media/course.mp4` (the
  release allowlist path).
- One build may contain at most one animation block. A second block is
  `invalid_input`; multi-shot composition is a later phase.
- `lces build` resolves `animation` through `default_registry()`. On a
  non-Linux host, or without the pinned Node/Chromium/FFmpeg, the build fails
  with the environment code; it does not skip the animation.
- The adapter writes the video atomically, plus
  `internal/qa/frame_manifest.json` and `internal/qa/encode_report.json`.
  `visual_assets.json` records the video, both evidence files and the
  `build_id`; any hash or cross-check mismatch fails the build.
- `encode_report.json` schema **1.2** redacts the FFmpeg command: paths under
  the build root become `<build>/…` and the binary keeps only its basename
  (`command_paths: "build-relative"`), so the report can be uploaded as CI
  evidence. Schema **1.1** adds `provenance` for Level 1 input traceability
  (P2.3-C): `node_version`, `npm_version`, `motion_canvas_version`,
  `playwright_version`, `ffmpeg_version`, `python_version`, `lces_version`,
  `package_json_sha256` and `package_lock_sha256`. Neither carries a host
  path. Reports without provenance keep schema 1.0.
- The public page embeds a fixed `<video controls>` element pointing at
  `../media/course.mp4`; no model-provided HTML is accepted.
- `use_registry=False` rejects animation blocks, like charts.

Build commit protocol: `build/.build-in-progress` is written before rendering
and removed only after the page, specs, render manifest and `visual_assets.json`
have all been written and re-verified. `lces release` and `build_release()`
refuse while the marker exists; Gate 3 reports `build_committed=fail`.

## Scene templates: `title`, `flow`, `compare` (P2)

`SceneContract.data` is validated per `scene_type`; unknown fields are
rejected rather than ignored. All templates are fixed TypeScript in
`motion_templates.py`; data is embedded as JSON literals, so labels cannot
become code.

Common fields: `title` (required), `subtitle`, `accent_color`,
`background_color`. `title` keeps the P1 limit of 200 characters; `flow` and
`compare` use 120.

**`flow`** — 2–6 nodes, 1–10 edges:

```json
{
  "title": "请求处理流程",
  "direction": "lr",
  "nodes": [{"id": "gateway", "label": "网关", "kind": "start"}],
  "edges": [{"from": "gateway", "to": "auth", "label": "写入"}]
}
```

- `direction`: `lr` (default) or `tb`; node `id` is unique, lowercase
  alphanumeric/hyphen; `label` ≤ 40; `kind` ∈ start/step/decision/end.
- Edges must reference existing nodes; self-loops and duplicate
  `(from, to)` pairs are rejected; edge labels ≤ 24.
- Layout is deterministic: nodes in index order, fixed gaps, no auto-layout.
  If the minimum node size/gap does not fit the canvas, the scene is
  `invalid_input`.

**`compare`** — two panels:

```json
{
  "title": "两种方案",
  "left": {"title": "方案 A", "items": ["实现简单"]},
  "right": {"title": "方案 B", "items": ["扩展性好"]}
}
```

- Panel title ≤ 60; 1–6 items per side, each ≤ 120 characters.
- Two equal-width panels; item positions are computed with a deterministic
  line estimate. If the items cannot fit the panel, the scene is
  `invalid_input`.
- No third column, icons, images, or rich text.

## Traceability

`build_public_html` writes, under `internal/qa/`:

- `visual_specs.json` — the derived specs, in build order.
- `render_manifest.json` — `visual_id`, `visual_type`, `schema_version`,
  `slide_id`, `block_index`, `renderer`, `renderer_version`,
  `output_sha256`.

The manifest links each rendered fragment to its input spec and renderer
version; the task/stage record in SQLite links the build to a project and time.
Each entry also carries `build_id` (empty for inline visuals, the Motion Canvas
build id for animations).

## Migration status

`table`, `figure_image`, `custom_svg`, and `data_chart` render through the
registry. The previous template-only path is still available via
`build_public_html(use_registry=False)` and is covered by a parity test, so the
old and new flows can be compared. Chart blocks cannot use the legacy path and
raise a `RenderError` instead of disappearing silently. Generate a one-off
fragment with:

```powershell
uv run lces render-spec .\spec.json --out .\build\visuals
```

A `data_chart` spec carries the Vega-Lite document under
`data.vega_lite`, plus `alt` (required) and `caption` (optional). The rendered
SVG is written to `<out>/visuals/<visual_id>.svg` and embedded in the returned
HTML fragment.

Chart sources should keep data, cleaning rules, statistical choices, and
encoding separable. The renderer validates structure, not whether the numbers
or axis semantics are correct; that remains part of human review.

## Adding a renderer

1. Implement `Renderer` with `name`, `version`, `visual_types`, `render`, and
   `validate`.
2. Register it in `default_registry()`; duplicate `visual_type` registration is
   rejected at startup.
3. Add tests for the happy path, invalid data, and unknown types.
4. Add a regression test comparing its output with any renderer it replaces.


## Learning checks and the product contract (P5)

`CheckBlock` (`type: "check"`) carries a question, an answer and the reasoning
behind the answer. The course template renders it as a `<details>` element so
the answer is available for self-checking without being shown by default. The
block is part of `PublicContent`, so it is exported in the public schema and
cannot carry speaker notes or internal fields.

A course that freezes a product definition writes
`internal/plan/course_contract.json` (`CourseContract`): audience,
prerequisites, target duration and timing rule, verifiable objectives mapped
to slide IDs, modules, deliverables, required formula/check counts and the
manual Gate B items. `lces audit-product` checks the delivered content against
that contract, including measured timing evidence and a human course
acceptance record. A project without a contract reports Gate B `NOT_RUN`,
never `PASS`; an approved contract makes Gate B blocking at release time.

`course_content_audit` remains a separate rule set: it checks that shown
numbers and formulas match reviewed evidence. It never implies that the course
product is accepted.
