"""Evidence governance: review states and human claim review (Phase 4).

The model writes claims and evidence, but it cannot verify them. Review state
starts as ``pending``/``unverified`` and only a named human reviewer can move
it forward. Legacy status values keep working through :func:`canonical_status`.
"""

from __future__ import annotations

import json
from pathlib import Path

from content_studio.errors import ValidationFailure
from content_studio.models import Claim
from content_studio.utils import utc_now, write_json

CANONICAL_STATUSES = (
    "pending",
    "supported",
    "partially_supported",
    "contradicted",
    "insufficient_evidence",
    "not_applicable",
)

LEGACY_STATUS_MAP = {
    "unverified": "pending",
    "verified": "supported",
    "conflict": "contradicted",
    "unverifiable": "insufficient_evidence",
}

SUPPORTED_STATUSES = frozenset({"supported", "not_applicable"})
CONTRADICTED_STATUSES = frozenset({"contradicted"})
PENDING_STATUSES = frozenset({"pending", "partially_supported", "insufficient_evidence"})


def canonical_status(status: str) -> str:
    return LEGACY_STATUS_MAP.get(status, status)


def review_state(status: str, reviewer: str) -> str:
    """Canonical status, with anonymous "supported" demoted to pending.

    Older projects contain statuses the model wrote about its own evidence.
    Those rows have no reviewer, so they cannot count as human verification.
    """

    canonical = canonical_status(status)
    if canonical in SUPPORTED_STATUSES and not reviewer.strip():
        return "pending"
    return canonical


def is_supported(status: str) -> bool:
    return canonical_status(status) in SUPPORTED_STATUSES


def is_contradicted(status: str) -> bool:
    return canonical_status(status) in CONTRADICTED_STATUSES


def is_pending(status: str) -> bool:
    return canonical_status(status) in PENDING_STATUSES


def load_claims(project_dir: Path) -> list[Claim] | None:
    path = project_dir / "internal" / "claims.json"
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValidationFailure("claims.json must contain a list")
    return [Claim.model_validate(item) for item in raw]


def review_claim(
    project_dir: Path,
    claim_id: str,
    status: str,
    reviewer: str,
    note: str = "",
) -> Claim:
    """Record a human review decision for one claim and persist it."""

    if status not in CANONICAL_STATUSES:
        raise ValidationFailure(
            f"unknown review status '{status}'; choose from {', '.join(CANONICAL_STATUSES)}"
        )
    if not reviewer.strip():
        raise ValidationFailure("reviewer is required; anonymous reviews are not accepted")
    claims = load_claims(project_dir)
    if claims is None:
        raise ValidationFailure("claims.json is missing; run the research stage first")

    updated: Claim | None = None
    result: list[Claim] = []
    for claim in claims:
        if claim.claim_id != claim_id:
            result.append(claim)
            continue
        updated = claim.model_copy(
            update={
                "verification_status": status,
                "reviewer": reviewer.strip(),
                "reviewed_at": utc_now(),
                "notes": note or claim.notes,
            }
        )
        result.append(updated)
    if updated is None:
        raise ValidationFailure(f"claim not found: {claim_id}")

    write_json(project_dir / "internal" / "claims.json", result)
    return updated
