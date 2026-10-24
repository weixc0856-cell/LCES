# Evidence Governance

Phase 4 makes the source → evidence → claim → content chain explicit and
keeps verification in human hands.

## Status vocabulary

Canonical review states (`Claim.verification_status`,
`EvidenceRecord.verification_status`):

| State | Meaning | Gate 1 effect |
|---|---|---|
| `pending` | Not reviewed yet | warn |
| `supported` | Evidence supports the claim within the checked scope | pass |
| `partially_supported` | Evidence supports only part of it | warn |
| `contradicted` | Evidence conflicts with the claim | **fail (blocking)** |
| `insufficient_evidence` | Not enough evidence to decide | warn |
| `not_applicable` | Verification does not apply | pass |

Older projects use `unverified` / `verified` / `conflict` / `unverifiable`;
`canonical_status()` maps them to `pending` / `supported` / `contradicted` /
`insufficient_evidence` so history keeps working.

## Two rules that matter

1. **The model cannot verify itself.** The research stage resets every
   model-reported status to `pending`/`unverified` and clears reviewer and
   timestamp fields before persisting. A provider that emits `"verified"` gains
   nothing.
2. **No reviewer, no credit.** `review_state()` demotes `supported`/`verified`
   to `pending` when `reviewer` is empty. This catches older rows that a model
   marked as verified: the gate reports them as unverified instead of trusting
   them.

`contradicted` stays blocking regardless of reviewer: a conflict must be
resolved or the release stops.

## Recording a review

```powershell
uv run lces review-claims .\projects\<project> --claim claim-001 `
    --status supported --by "你的名字" --note "对照原文 Abstract"
```

This writes `verification_status`, `reviewer`, `reviewed_at`, and the note into
`internal/claims.json`. Re-run `lces validate` afterwards so Gate 1 reflects
the decision. The command refuses unknown statuses, an empty reviewer, and
claim IDs that do not exist.

Evidence rows carry their own status and reviewer columns in
`internal/evidence_ledger.csv`; the same anonymous-status rule applies.

## Gate 1 checks

| Check | Blocks? | What it verifies |
|---|---|---|
| `source_registry_exists` | yes | Registry present and non-empty |
| `sources_available` | no (warn) | Every source fetched |
| `research_brief_exists` | yes | Brief written |
| `claims_parse` | yes | `claims.json` parses; a broken file never becomes "no claims" |
| `evidence_references_valid` | yes | Evidence points at real sources and claims |
| `key_claims_have_evidence` | yes | Every key claim has supporting evidence |
| `contradicted_claims_blocked` | yes | No key claim is contradicted |
| `pending_claims_flagged` | no (warn) | Key claims still awaiting review |
| `evidence_locators_present` | no (warn) | Key evidence has a locator or excerpt |
| `unverified_key_evidence_flagged` | no (warn) | Key evidence lacking a named review |
| `scientific_review` | `not_run` | Formulas, units, causality — human only |

## Sectioned research and locators

Research now runs once per chunk window instead of once per source. Each
window carries chunk headers with `source_id`, section and page; the model must
use those for `locator` and quote `source_excerpt` verbatim without the
headers. The merge step assigns global IDs, remaps evidence to claims, and
records every call (chunk range, `finish_reason`, usage, request id) in
`research_analysis.json`.

The same anonymity rule applies per window: every model-reported verification
status is reset. The model now only proposes candidates; `evidence_locator.py`
must find each candidate inside the named chunk before it becomes evidence.
Only `verified_exact` and `verified_normalized` enter the ledger; the excerpt
is sliced from the source, so a paraphrase cannot be written as a quote.
Candidates may name a section instead of a chunk; the locator then searches
that section but still accepts only a quote contained in a single chunk, and
records the resolved chunk. `needs_review` and `rejected` candidates are
recorded with their reasons in `internal/qa/quote_audit.json`. Bibliography, acknowledgement and affiliation
sections are excluded from research and listed in `excluded_chunks`, so they
cannot become teaching claims.

Formulas and table rows use structured evidence instead of free-text quotes.
A table row's label/value co-occurrence and span are only structural checks;
because the extracted source cannot prove the column-to-cell mapping, table
evidence stays `needs_review` (`column_semantics_unverified`). `verified_structured`
is reserved for a future cell-column parser. A formula is never auto-verified:
the program checks the paper element, expression and symbol presence, records a
normalized expression (`unicode-math/v1`: `√`/`\sqrt` and subscript braces are
normalized for matching only), then marks it `formula_semantics_manual` or
`formula_symbols_not_found` for human review. Structured reviews are written to
`internal/qa/structured_evidence_audit.json`.

**Research verification is not a signature.** `ResearchVerification` may record
`research_finding=verified` against a primary source, but that is a separate
layer from `ReviewItem.conclusion`; it never sets `reviewed_by_human` or changes
the evidence ledger. A `source_conflict` must list every source and locator; the
program does not choose a winner. A human `pass` on a conflict requires
`conflict_acknowledged=True` and a basis. `lces review-evidence` validates the
links and appends an audit entry.

## AI substantive review (2026-10-24)

A third layer records what an AI actually checked:

```powershell
uv run lces review-evidence-ai .\projects\<project> --review-id review-... `
    --by "claude-code (AI substantive review)" --finding consistent `
    --scope source_transcription --scope claim_interpretation `
    --basis "Table 2 row at b0048 reads 27.3; EN-DE column checked against the proceedings" `
    --limitations "Course usage is checked by the course audit"
```

`substantive_review.reviewer_kind` is fixed to `ai`. The writer refuses an empty
reviewer or basis, refuses unknown findings, and never touches `reviewer`,
`reviewed_at`, `conclusion` or `reviewed_by_human`. The audit log line carries
`layer=ai_substantive_review` and `conclusion_unchanged`. Pydantic rejects
`reviewer_kind=human`, so an AI record cannot be promoted into a signature by
editing JSON alone.

The three layers answer different questions and must not be merged:

| Layer | Question | Can it release? |
|---|---|---|
| `research_verification` | Does an authoritative source agree? | no |
| `substantive_review` | Did an AI compare the record with the source? | no |
| `conclusion` + `reviewer` | Did a named human sign this scope? | yes, alone |

## Course content audit and release gate

`lces audit-course` is a read-only audit of what the course actually shows. It
reads `content/public_content.json`, `content/reading_edition.json` and the
built HTML (plus any `--scan` target) and checks:

- every decimal stated as a BLEU score belongs to a reviewed record;
- a value that is part of a source conflict is disclosed together with the
  other value and a conflict marker in the same teaching unit;
- Table 3 values (26.4 / 25.8) keep their `BLEU (dev)` + `newstest2013` +
  EN-DE condition and are not presented as test-set results;
- a displayed formula matches a reviewed transcription after
  `latex-tokens/v1` normalisation (commands, braces, parentheses, `\frac{a}{b}`
  → `a/b`, `√` → `sqrt`); this is matching only, never a semantic proof;
- a reviewed formula the course never shows, and a formula with no reviewed
  evidence, are reported;
- a missing source text makes the item unverifiable, never verified.

Findings are `blocker`, `major` or `advisory`, with a stable `finding_id`
derived from check type, location, expected and actual text. Re-running the
audit regenerates the report instead of appending duplicates. The report is
bound to the SHA-256 of every file it read (`course_version`), so editing the
course after an audit makes the old report stale.

Gate 2 blocks on `course_content_audit`; Gate 4 additionally requires
`structured_evidence_signed`, `source_conflicts_acknowledged`,
`course_content_audit_current`, `course_content_audit_passed` and
`release_matches_audited_content`. `build_release` refreshes the audit against
the build it packages; `release-check` refuses a release whose assets are not
the audited version. Refusals report a decision (`blocked`,
`needs_human_review`, `approved_with_disclosures` or `approved`) followed by
the concrete failing checks.

**ID scope.** `evidence-00x` in research windows and trial reports is
window-local. The formal ledger renumbers accepted evidence globally via
`_merge_evidence`; reviews carry `source_id`, `chunk_id` and `locator`, and the
trial report groups candidates by window, so a repeated local id is not a global
conflict.

`evidence_quotes_in_source` remains a second, whole-source check after the
ledger is written. It catches a locator bug or a source text change; it is not
the mechanism that admits evidence. Table and formula records are excluded
from the quote comparison and reported separately: a table row is not a quote,
and comparing it to prose would only produce a false warning.

**P5 evidence remediation (2026-10-24).** Of the 27 non-verbatim excerpts, 20
were replaced with the actual source slice (extraction artifacts included) and
marked `verified_normalized`; 7 were classified as structured table/formula
evidence and no longer treated as quotes. The per-record disposition is in
`docs/design/evidence-remediation-2026-10-24.json`. `claim-001` was narrowed to
"replaces recurrence" and a separate `claim-023` with a verbatim abstract quote
(`evidence-034`) now covers "no convolutions"; the link is no longer presented
as full support for a combined claim.

## What automation still cannot do

Gate 1 checks structure and review state, not truth. It cannot tell whether an
excerpt supports the claim it is attached to, whether the claim over-generalises,
or whether the source is trustworthy. Those remain human review, recorded with
the reviewer's name.
