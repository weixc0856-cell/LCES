# Architecture

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
| Research | `research.py` | Claims, evidence ledger, research brief, unknown/conflict tracking |
| Content | `content.py` | Outline, public content, speaker script, reading edition |
| Rendering | `rendering.py` + `templates/` | Public HTML from public-only models |
| Providers | `providers/` | Provider-neutral interface; DeepSeek, Anthropic, local llama.cpp, Mock |
| Routing | `routing.py` + `config/routing.yaml` | Opt-in per-stage provider selection (research/outline/generate) |
| Storage | `storage.py` | SQLite tasks, stage runs, events, assets, approvals |
| Validation | `validation.py` | Gates 1–4, marker/secret scans, manifest verification |
| Release | `release.py` | Approval, staging, manifest, ZIP |
| Contracts | `models.py` | Pydantic models; JSON Schema source |

## Data flow

```
input/ ──ingest──> internal/source_registry.json + internal/sources/*.txt
                         │
                    research (model)
                         ▼
        internal/research_analysis.json, evidence_ledger.csv, research_brief.md
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

The local adapter targets llama.cpp `llama-server` (OpenAI-compatible `/v1`),
discovers the loaded model from `/v1/models`, and needs no API key. Model
routing is opt-in and stage-scoped; deterministic stages never construct a
model provider.

## Local/cloud split

`config/routing.yaml` can send research to a cloud model while drafting stays
local. `lces models` probes `/health` and `/v1/models` without making a
completion request. Each stage records provider, model, and token usage in
SQLite, so a mixed run remains auditable. Automatic escalation based on failure
counts or eval scores is not implemented yet.

## State machine

`CREATED → INGESTING → RESEARCHING → PLANNING → GENERATING → VALIDATING →
REVIEW_REQUIRED → RELEASED`, with `FAILED` and `NEEDS_REVISION` reachable from
any stage. Each stage run is recorded with provider, model, usage JSON, error,
and timestamps.

Resuming is stage-scoped: `lces run --from-stage outline` rebuilds the
downstream assets without re-fetching sources.

## Explicit non-goals in Phase 1

Browser frame export, FFmpeg encoding, subtitles, visual regression, web UI,
multi-model routing, cache/incremental builds. These are reported as `NOT_RUN`
rather than silently treated as passing.
