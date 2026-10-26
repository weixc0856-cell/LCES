"""Guards for the known defects in TDD-001 §14 (REG-001 … REG-010).

Every test here reproduces one recorded failure mode on a synthetic fixture and
asserts the mechanism that now catches it. The register itself — including the
items that still need a human record — is `docs/QUALITY.md` §7.

REG-005/006/009/010 stay partly human: a passing test proves the gate exists,
never that a person signed or watched anything.
"""

from pathlib import Path

from content_studio.models import (
    Claim,
    ProjectConfig,
    ResearchBrief,
    SourceRecord,
    SourceRegistry,
)
from content_studio.paths import ensure_project_layout
from content_studio.utils import write_json, write_text
from content_studio.validation import run_validation

TEMPLATES = Path(__file__).resolve().parents[1] / "templates" / "public_html"


def _gate1_project(tmp_path: Path, *, with_evidence: bool) -> tuple[Path, ProjectConfig]:
    """A project with one key claim, optionally backed by one evidence row."""

    root = ensure_project_layout(tmp_path / "project")
    config = ProjectConfig(project_id="reg-course", title="回归课程")
    write_json(
        root / "internal" / "source_registry.json",
        SourceRegistry(
            project_id=config.project_id,
            sources=[
                SourceRecord(
                    source_id="source-001",
                    title="Source",
                    kind="text",
                    origin="input/source.md",
                    local_path="internal/sources/source-001.txt",
                )
            ],
        ),
    )
    write_text(
        root / "internal" / "sources" / "source-001.txt",
        "The Transformer reaches 28.4 BLEU on WMT 2014 English-to-German.",
    )
    write_json(
        root / "internal" / "research_brief.json",
        ResearchBrief(
            project_id=config.project_id,
            research_question="示例问题",
            scope="示例范围",
        ),
    )
    write_json(
        root / "internal" / "claims.json",
        [
            Claim(
                claim_id="claim-001",
                statement="Transformer (big) 在 WMT 2014 英德达到 28.4 BLEU",
                claim_type="fact",
                importance="key",
            ).model_dump(mode="json")
        ],
    )
    header = (
        "evidence_id,source_id,chunk_id,claim_id,evidence_type,locator,"
        "source_excerpt,support_relation,verification_status,quote_status,"
        "reviewer,checked_at,notes,structured_json\n"
    )
    row = ""
    if with_evidence:
        row = (
            "evidence-001,source-001,source-001:b0000,claim-001,quote,Abstract,"
            '"The Transformer reaches 28.4 BLEU on WMT 2014 English-to-German.",'
            "supports,unverified,unverified,,,\n"
        )
    write_text(root / "internal" / "evidence_ledger.csv", header + row)
    return root, config


def _status(checks, check_id: str) -> str:
    return next(item.status for item in checks if item.check_id == check_id)


def test_reg_001_key_claim_without_evidence_fails_gate_1(tmp_path):
    root, config = _gate1_project(tmp_path, with_evidence=False)

    report = run_validation(root, config, TEMPLATES, browser_qa=False)

    assert _status(report.checks, "key_claims_have_evidence") == "fail"
    assert any(
        item.check_id == "key_claims_have_evidence" and "claim-001" in item.message
        for item in report.checks
    )
    assert report.blocking_failures


def test_reg_001_key_claim_with_a_supporting_row_passes(tmp_path):
    root, config = _gate1_project(tmp_path, with_evidence=True)

    report = run_validation(root, config, TEMPLATES, browser_qa=False)

    assert _status(report.checks, "key_claims_have_evidence") == "pass"
