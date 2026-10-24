from __future__ import annotations

from content_studio.evidence_locator import (
    QuoteCandidate,
    locate_candidate,
    validate_candidates,
)
from content_studio.models import SourceChunk

SOURCE = (
    "First paragraph with a unique sentence about attention.\n\n"
    "Second paragraph with another sentence about recurrence.\n\n"
    "The model’s encoder is “stable”​ in every run.\n\n"
    "We scale by \\sqrt{d_k} before the softmax.\n\n"
    "A repeated phrase appears here. A repeated phrase appears again."
)
CHUNK_ONE_START = 0
CHUNK_ONE_END = SOURCE.index("Second paragraph")
CHUNK_TWO_START = CHUNK_ONE_END
CHUNK_TWO_END = len(SOURCE)


def _chunks() -> dict[str, SourceChunk]:
    one = SourceChunk(
        chunk_id="source-001:b0000",
        index=0,
        section="1 Introduction",
        char_start=CHUNK_ONE_START,
        char_end=CHUNK_ONE_END,
        text_chars=CHUNK_ONE_END - CHUNK_ONE_START,
    )
    two = SourceChunk(
        chunk_id="source-001:b0001",
        index=1,
        section="2 Method",
        char_start=CHUNK_TWO_START,
        char_end=CHUNK_TWO_END,
        text_chars=CHUNK_TWO_END - CHUNK_TWO_START,
    )
    return {one.chunk_id: one, two.chunk_id: two}


def _candidate(text: str, *, chunk_id: str = "source-001:b0000", claim_id: str = "claim-001"):
    return QuoteCandidate(
        candidate_id="evidence-001",
        claim_id=claim_id,
        source_id="source-001",
        chunk_id=chunk_id,
        text=text,
    )


def _locate(text: str, *, chunk_id: str = "source-001:b0000"):
    chunk = _chunks()[chunk_id]
    return locate_candidate(_candidate(text, chunk_id=chunk_id), chunk=chunk, source_text=SOURCE)


def test_exact_quote_is_sliced_from_the_source():
    location = _locate("First paragraph with a unique sentence about attention.")
    assert location.status == "verified_exact"
    assert location.excerpt == "First paragraph with a unique sentence about attention."
    assert location.char_start == 0
    assert location.locator == "§1 Introduction"
    assert location.normalized is False


def test_typography_normalisation_returns_the_original_slice():
    location = _locate(
        'The model\'s encoder is "stable" in every run.', chunk_id="source-001:b0001"
    )
    assert location.status == "verified_normalized"
    assert location.excerpt == "The model’s encoder is “stable”​ in every run."
    assert "“stable”" in location.excerpt


def test_math_symbols_are_not_silently_rewritten():
    location = _locate("We scale by √d_k before the softmax.")
    assert location.status == "needs_review"
    assert location.reason == "not_found"


def test_candidate_must_stay_inside_the_named_chunk():
    spanning = (
        "First paragraph with a unique sentence about attention.\n\n"
        "Second paragraph with another sentence about recurrence."
    )
    location = _locate(spanning, chunk_id="source-001:b0000")
    assert location.status == "needs_review"
    assert location.reason == "not_found"


def test_ambiguous_match_is_not_accepted():
    location = _locate("A repeated phrase appears", chunk_id="source-001:b0001")
    assert location.status == "needs_review"
    assert location.reason == "ambiguous_exact"


def test_short_candidate_is_not_accepted():
    location = _locate("attention")
    assert location.status == "needs_review"
    assert location.reason == "too_short"


def test_section_level_resolution_finds_the_actual_chunk():
    # The model names the wrong chunk (b0000) but the correct section.
    candidate = _candidate(
        "Second paragraph with another sentence about recurrence.",
        chunk_id="source-001:b0000",
    ).model_copy(update={"section_id": "2 Method"})

    located, audit = validate_candidates(
        [candidate],
        claim_ids={"claim-001"},
        chunks=_chunks(),
        source_texts={"source-001": SOURCE},
    )

    assert located[0].location.status == "verified_exact"
    assert located[0].location.chunk_id == "source-001:b0001"
    assert located[0].location.resolved is True
    assert audit.section_resolved == 1


def test_section_resolution_never_joins_chunks():
    spanning = (
        "First paragraph with a unique sentence about attention."
        + chr(10) * 2
        + "Second paragraph with another sentence about recurrence."
    )
    candidate = _candidate(spanning, chunk_id="source-001:b0000").model_copy(
        update={"section_id": "1 Introduction"}
    )

    located, audit = validate_candidates(
        [candidate],
        claim_ids={"claim-001"},
        chunks=_chunks(),
        source_texts={"source-001": SOURCE},
    )

    assert located[0].location.status == "needs_review"
    assert located[0].location.reason == "not_found_in_section"
    assert audit.section_resolved == 0


def test_validate_candidates_rejects_invalid_ids():
    chunks = _chunks()
    candidates = [
        _candidate("First paragraph with a unique sentence about attention."),
        _candidate("Second paragraph with another sentence about recurrence."),
        _candidate("Second paragraph with another sentence about recurrence."),
        _candidate("First paragraph with a unique sentence about attention.", chunk_id="missing"),
    ]
    candidates[1] = candidates[1].model_copy(update={"claim_id": "claim-999"})
    candidates[2] = candidates[2].model_copy(update={"source_id": "source-999"})

    located, audit = validate_candidates(
        candidates,
        claim_ids={"claim-001"},
        chunks=chunks,
        source_texts={"source-001": SOURCE},
    )

    statuses = [item.location.status for item in located]
    assert statuses == ["verified_exact", "rejected", "rejected", "rejected"]
    assert audit.total == 4
    assert audit.verified_exact == 1
    assert audit.rejected == 3
    reasons = {review.candidate_id for review in audit.reviews}
    assert reasons == {"evidence-001"}
    assert {review.reason for review in audit.reviews} == {
        "unknown_claim",
        "unknown_source",
        "unknown_chunk",
    }


def test_chunk_in_locator_is_accepted_but_chunk_must_be_in_window():
    chunks = _chunks()
    candidate = _candidate("First paragraph with a unique sentence about attention.", chunk_id="")
    candidate = candidate.model_copy(update={"locator": "source-001:b0000"})

    located, audit = validate_candidates(
        [candidate],
        claim_ids={"claim-001"},
        chunks=chunks,
        source_texts={"source-001": SOURCE},
    )

    assert located[0].location.status == "verified_exact"
    assert located[0].candidate.chunk_id == "source-001:b0000"
    assert audit.verified_exact == 1
