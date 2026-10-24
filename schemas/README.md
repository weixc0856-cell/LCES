# Schemas

JSON Schema files describe the contracts in `src/content_studio/models.py`.
The Pydantic models are the single source of truth; run:

```powershell
uv run lces export-schemas
```

to regenerate every schema listed below. The command overwrites the
corresponding files (it does not touch `scene_render_contract.schema.json`,
which belongs to Phase 3).

| File | Contract |
|---|---|
| `project.schema.json` | `ProjectConfig` |
| `source_registry.schema.json` | `SourceRegistry` |
| `evidence.schema.json` | `EvidenceRecord` |
| `evidence_ledger.schema.json` | `EvidenceLedger` |
| `research_brief.schema.json` | `ResearchBrief` |
| `research_analysis.schema.json` | `ResearchAnalysis` (single-call research output) |
| `quote_candidate.schema.json` | `QuoteCandidate` (model proposal before location) |
| `quote_audit.schema.json` | `QuoteAudit` (exact/normalized/review/rejected counts) |
| `section_analysis.schema.json` | `SectionAnalysis` (one sectioned-research window) |
| `source_map.schema.json` | `SourceMap` (page/section/chunk boundaries) |
| `content_outline.schema.json` | `ContentOutline` |
| `paper_map.schema.json` | `PaperMap` (internal paper structure) |
| `coverage_matrix.schema.json` | `CoverageMatrix` (paper element → units) |
| `learning_unit.schema.json` | `LearningUnit` (internal unit of generation) |
| `course_master.schema.json` | `CourseMaster` (single internal course source) |
| `public_content.schema.json` | `PublicContent` (public only) |
| `speaker_script.schema.json` | `SpeakerScript` (internal only) |
| `reading_edition.schema.json` | `ReadingEdition` |
| `qa_report.schema.json` | `QAReport` |
| `release_manifest.schema.json` | `ReleaseManifest` |
| `visual_spec.schema.json` | `VisualSpec` (renderer input) |
| `visual_asset.schema.json` | `VisualAsset` (rendered artifact provenance) |
| `scene_contract.schema.json` | `SceneContract` (one timeline shot, integer ms) |
| `scene_set.schema.json` | `SceneSet` (ordered scenes for one video build) |
| `frame_manifest.schema.json` | `FrameManifest` (frame evidence for one build) |
| `video_contract.schema.json` | `VideoContract` (canvas, rational fps, encoding) |
| `scene_render_contract.schema.json` | Phase 3 scene contract (not generated yet) |

The committed copies are hand-maintained equivalents for the core public,
evidence, project, script, and release contracts. Regenerating them locally is
expected and preferred; if a file differs from the Pydantic output, the
Pydantic model wins.

Rules enforced by the contracts:

- `additionalProperties: false` everywhere — internal fields cannot be smuggled
  into public data.
- Public blocks are a discriminated union on `type`; narration has no block
  type and no path into the public renderer.
- Slide IDs follow `slide-001`, claim IDs `claim-001`, evidence IDs
  `evidence-001`, sources `source-001`.
- Every table row must match the column count (enforced in Pydantic, not
  expressible in plain JSON Schema).
