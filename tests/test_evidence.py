import json

import pytest

from content_studio.errors import ValidationFailure
from content_studio.evidence import (
    canonical_status,
    is_contradicted,
    is_pending,
    is_supported,
    review_claim,
    review_state,
)
from content_studio.models import (
    Claim,
    EvidenceLedger,
    EvidenceRecord,
    ResearchAnalysis,
)
from content_studio.research import _reset_verification
from content_studio.validation import _claim_review_checks


def _claim(
    claim_id: str = "claim-001",
    *,
    importance: str = "key",
    status: str = "pending",
    reviewer: str = "",
) -> Claim:
    return Claim(
        claim_id=claim_id,
        statement="示例主张",
        claim_type="fact",
        importance=importance,  # type: ignore[arg-type]
        verification_status=status,  # type: ignore[arg-type]
        reviewer=reviewer,
    )


def _evidence(
    evidence_id: str = "evidence-001",
    *,
    claim_id: str = "claim-001",
    locator: str = "Abstract",
    excerpt: str = "原文摘录",
    status: str = "unverified",
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        source_id="source-001",
        claim_id=claim_id,
        evidence_type="quote",
        locator=locator,
        source_excerpt=excerpt,
        support_relation="supports",
        verification_status=status,  # type: ignore[arg-type]
    )


def _project(tmp_path):
    internal = tmp_path / "internal"
    internal.mkdir(parents=True)
    (internal / "claims.json").write_text(
        json.dumps(
            [
                _claim("claim-001").model_dump(mode="json"),
                _claim("claim-002", importance="supporting").model_dump(mode="json"),
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return tmp_path


def test_legacy_statuses_map_to_canonical_values():
    assert canonical_status("unverified") == "pending"
    assert canonical_status("verified") == "supported"
    assert canonical_status("conflict") == "contradicted"
    assert canonical_status("unverifiable") == "insufficient_evidence"
    assert canonical_status("supported") == "supported"

    assert is_supported("verified") is True
    assert is_contradicted("conflict") is True
    assert is_pending("unverified") is True


def test_review_claim_records_reviewer_and_time(tmp_path):
    project = _project(tmp_path)
    updated = review_claim(project, "claim-001", "supported", "weixc0856", note="对照原文")

    assert updated.verification_status == "supported"
    assert updated.reviewer == "weixc0856"
    assert updated.reviewed_at is not None

    stored = json.loads((tmp_path / "internal" / "claims.json").read_text(encoding="utf-8"))
    assert stored[0]["verification_status"] == "supported"
    assert stored[0]["reviewer"] == "weixc0856"
    assert stored[1]["verification_status"] == "pending", "other claims must not change"


def test_review_claim_rejects_invalid_input(tmp_path):
    project = _project(tmp_path)
    with pytest.raises(ValidationFailure, match="unknown review status"):
        review_claim(project, "claim-001", "approved", "weixc0856")
    with pytest.raises(ValidationFailure, match="reviewer is required"):
        review_claim(project, "claim-001", "supported", "  ")
    with pytest.raises(ValidationFailure, match="claim not found"):
        review_claim(project, "claim-999", "supported", "weixc0856")

    with pytest.raises(ValidationFailure, match="claims.json is missing"):
        review_claim(tmp_path / "empty", "claim-001", "supported", "weixc0856")


def test_generation_resets_model_reported_verification():
    analysis = ResearchAnalysis(
        research_question="问题",
        scope="范围",
        claims=[_claim(status="supported")],
        evidence=[_evidence(status="verified")],
    )
    reset = _reset_verification(analysis)

    assert reset.claims[0].verification_status == "pending"
    assert reset.claims[0].reviewer == ""
    assert reset.evidence[0].verification_status == "unverified"
    assert reset.evidence[0].reviewer == ""


def test_contradicted_key_claim_blocks_gate():
    checks = _claim_review_checks(
        [_claim(status="contradicted")], EvidenceLedger(project_id="p"), claims_error=""
    )
    statuses = {check.check_id: check.status for check in checks}
    assert statuses["contradicted_claims_blocked"] == "fail"
    assert next(c for c in checks if c.check_id == "contradicted_claims_blocked").blocking


def test_pending_claims_only_warn():
    checks = _claim_review_checks(
        [_claim(status="pending")], EvidenceLedger(project_id="p"), claims_error=""
    )
    statuses = {check.check_id: check.status for check in checks}
    assert statuses["pending_claims_flagged"] == "warn"
    assert next(c for c in checks if c.check_id == "pending_claims_flagged").blocking is False


def test_supported_key_claims_pass():
    checks = _claim_review_checks(
        [_claim(status="supported", reviewer="tester")],
        EvidenceLedger(project_id="p", records=[_evidence()]),
        claims_error="",
    )
    statuses = {check.check_id: check.status for check in checks}
    assert statuses["contradicted_claims_blocked"] == "pass"
    assert statuses["pending_claims_flagged"] == "pass"
    assert statuses["evidence_locators_present"] == "pass"


def test_supported_without_reviewer_is_treated_as_pending():
    assert review_state("supported", "") == "pending"
    assert review_state("verified", "  ") == "pending"
    assert review_state("supported", "tester") == "supported"

    checks = _claim_review_checks(
        [_claim(status="supported")], EvidenceLedger(project_id="p"), claims_error=""
    )
    pending = next(c for c in checks if c.check_id == "pending_claims_flagged")
    assert pending.status == "warn"
    assert "claim-001" in pending.message


def test_evidence_without_locator_or_excerpt_is_flagged():
    checks = _claim_review_checks(
        [_claim(status="supported", reviewer="tester")],
        EvidenceLedger(
            project_id="p",
            records=[_evidence(locator="", excerpt="")],
        ),
        claims_error="",
    )
    locator_check = next(c for c in checks if c.check_id == "evidence_locators_present")
    assert locator_check.status == "warn"
    assert "evidence-001" in locator_check.message


def test_broken_claims_file_suppresses_vacuous_passes():
    checks = _claim_review_checks([], EvidenceLedger(project_id="p"), claims_error="bad json")
    assert checks == []
