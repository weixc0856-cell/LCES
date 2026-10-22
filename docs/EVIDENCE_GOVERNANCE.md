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

## What automation still cannot do

Gate 1 checks structure and review state, not truth. It cannot tell whether an
excerpt supports the claim it is attached to, whether the claim over-generalises,
or whether the source is trustworthy. Those remain human review, recorded with
the reviewer's name.
