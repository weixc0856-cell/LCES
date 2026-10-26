from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from content_studio.cli import app
from content_studio.course_audit import (
    audit_is_current,
    canonical_latex,
    load_audit,
    run_course_audit,
    write_audit,
)
from content_studio.errors import ValidationFailure
from content_studio.models import (
    CheckResult,
    Claim,
    FormulaBlock,
    PaperElement,
    PaperMap,
    ParagraphBlock,
    ProjectConfig,
    PublicContent,
    PublicSlide,
    QAReport,
    SourceChunk,
    SourceDocumentMap,
    SourceMap,
    SourceRecord,
    SourceRegistry,
)
from content_studio.paths import ensure_project_layout
from content_studio.release import approve, build_release, verify_release
from content_studio.structured_review import (
    ReviewDocument,
    ReviewItem,
    record_review,
    record_substantive_review,
)
from content_studio.utils import write_json, write_text
from content_studio.validation import content_version

SOURCE_TEXT = (
    "Transformer (big) on WMT 2014 EN-FR: Table 2 reports 41.0 and the arXiv "
    "abstract reports 41.8. Table 3 big row reports BLEU (dev) 26.4 on "
    "newstest2013. Attention(Q,K,V)=softmax(QK^T/sqrt(d_k))V (Eq. 1)."
)
FORMULA = "Attention(Q,K,V)=softmax(QK^T/sqrt(d_k))V"


def _review_item(**overrides) -> ReviewItem:
    values = {
        "review_id": "review-table2-enfr",
        "local_evidence_id": "evidence-001",
        "window": "B_results",
        "paper_id": "paper-001",
        "source_id": "source-001",
        "chunk_id": "source-001:b0000",
        "locator": "§6.1",
        "evidence_kind": "table",
        "claim_id": "claim-001",
        "claim": (
            "Transformer (big) EN-FR BLEU: Table 2/§6.1 = 41.0; "
            "arXiv abstract = 41.8 (source conflict)"
        ),
        "conflict_status": "source_conflict",
        "research_verification": [
            {
                "research_finding": "source_conflict",
                "details": "Table 2/§6.1 state 41.0; the abstract states 41.8.",
                "sources": [
                    {"source_id": "local", "locator": "Table 2"},
                    {"source_id": "arxiv", "locator": "Abstract"},
                ],
            }
        ],
    }
    values.update(overrides)
    return ReviewItem(**values)


def _table3_item() -> ReviewItem:
    return _review_item(
        review_id="review-table3-big",
        local_evidence_id="evidence-002",
        paper_id="paper-003",
        locator="§6.2",
        claim="Table 3 big row: BLEU (dev) 26.4 on newstest2013, EN-DE",
        conflict_status="none",
        research_verification=[
            {"research_finding": "verified", "details": "Table 3 big row 26.4."}
        ],
    )


def _formula_item() -> ReviewItem:
    return _review_item(
        review_id="review-formula-attention",
        local_evidence_id="evidence-003",
        paper_id="paper-002",
        locator="§3.2.1",
        evidence_kind="formula",
        claim="Scaled Dot-Product Attention formula",
        conflict_status="none",
        research_verification=[
            {
                "research_finding": "verified",
                "details": "Matches Eq. (1).",
                "transcribed_expression": FORMULA,
            }
        ],
    )


def _content(paragraphs: list[str], *, formula: str | None = None) -> PublicContent:
    body: list[object] = [ParagraphBlock(text=text) for text in paragraphs]
    if formula is not None:
        body.append(FormulaBlock(latex=formula, explanation="注意力权重"))
    return PublicContent(
        project_id="audit-course",
        title="审计课程",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="结果",
                body=body,  # type: ignore[arg-type]
                source_ids=["source-001"],
            )
        ],
    )


def _project(
    tmp_path: Path,
    *,
    paragraphs: list[str] | None = None,
    formula: str | None = None,
    items: list[ReviewItem] | None = None,
    source_present: bool = True,
    build_html: str = "<html><body><p>正文</p></body></html>",
) -> tuple[Path, ProjectConfig]:
    root = ensure_project_layout(tmp_path / "project")
    config = ProjectConfig(project_id="audit-course", title="审计课程")
    (root / "project.yaml").write_text(
        "project_id: audit-course" + "\n" + "title: 审计课程" + "\n",
        encoding="utf-8",
    )
    write_json(
        root / "internal" / "source_registry.json",
        SourceRegistry(
            project_id=config.project_id,
            sources=[
                SourceRecord(
                    source_id="source-001",
                    title="Paper",
                    kind="markdown",
                    origin="input/paper.md",
                )
            ],
        ),
    )
    write_json(
        root / "internal" / "source_map.json",
        SourceMap(
            project_id=config.project_id,
            documents=[
                SourceDocumentMap(
                    source_id="source-001",
                    text_chars=len(SOURCE_TEXT),
                    chunks=[
                        SourceChunk(
                            chunk_id="source-001:b0000",
                            index=0,
                            section="6.1",
                            char_start=0,
                            char_end=len(SOURCE_TEXT),
                            text_chars=len(SOURCE_TEXT),
                        )
                    ],
                )
            ],
        ),
    )
    if source_present:
        write_text(root / "internal" / "sources" / "source-001.txt", SOURCE_TEXT)
    write_json(
        root / "internal" / "claims.json",
        [Claim(claim_id="claim-001", statement="A claim", claim_type="fact")],
    )
    write_json(
        root / "internal" / "plan" / "paper_map.json",
        PaperMap(
            project_id=config.project_id,
            elements=[
                PaperElement(
                    paper_item_id="paper-001", kind="table", title="Table 2", locator="§6.1"
                ),
                PaperElement(
                    paper_item_id="paper-002",
                    kind="equation",
                    title="Eq. 1",
                    locator="§3.2.1",
                ),
                PaperElement(
                    paper_item_id="paper-003", kind="table", title="Table 3", locator="§6.2"
                ),
            ],
        ),
    )
    write_json(
        root / "internal" / "qa" / "structured_evidence_review.json",
        ReviewDocument(
            project_id=config.project_id,
            items=items if items is not None else [_review_item()],
        ),
    )
    write_json(
        root / "content" / "public_content.json",
        _content(["(无结果)"] if paragraphs is None else paragraphs, formula=formula),
    )
    write_json(
        root / "content" / "reading_edition.json",
        {
            "project_id": config.project_id,
            "title": "审计课程",
            "abstract": "摘要",
            "sections": [
                {
                    "slide_id": "slide-001",
                    "title": "结果",
                    "paragraphs": paragraphs or ["(无结果)"],
                    "source_ids": ["source-001"],
                }
            ],
            "references": ["source-001"],
        },
    )
    write_text(root / "build" / "slides" / "index.html", build_html)
    write_text(root / "build" / "reading_edition.html", "<html><body>阅读版</body></html>")
    _version, _bound = content_version(root)
    report = QAReport(
        project_id=config.project_id,
        provider="local",
        content_version=_version,
        content_files=_bound,
        checks=[
            CheckResult(
                check_id="gate_1_research_ok",
                gate="gate_1_research",
                status="pass",
                message="ok",
            )
        ],
    )
    write_json(root / "internal" / "qa" / "qa_report.json", report)
    return root, config


def _audit(root: Path, **kwargs) -> object:
    report = run_course_audit(root, **kwargs)
    write_audit(root, report)
    return report


def test_undisclosed_conflict_blocks(tmp_path):
    root, _config = _project(tmp_path, paragraphs=["Transformer 在英法任务达到 41.8 BLEU。"])

    report = run_course_audit(root)

    assert report.decision == "blocked"
    conflict = [
        finding for finding in report.findings if finding.check_type == "source_conflict_disclosed"
    ]
    assert conflict
    assert conflict[0].severity == "blocker"
    assert conflict[0].evidence_refs == ["review-table2-enfr"]


def test_disclosed_conflict_passes_the_conflict_check(tmp_path):
    root, _config = _project(
        tmp_path,
        paragraphs=[
            "英法任务：Table 2 与 §6.1 记为 41.0；arXiv 摘要记为 41.8，存在来源冲突。",
            "41.0 BLEU 是论文正文口径。",
        ],
    )

    report = run_course_audit(root)

    assert not [
        finding for finding in report.findings if finding.check_type == "source_conflict_disclosed"
    ]


def test_unverified_bleu_value_blocks(tmp_path):
    root, _config = _project(tmp_path, paragraphs=["模型取得 41.5 BLEU。"])

    report = run_course_audit(root)

    unsupported = [
        finding for finding in report.findings if finding.check_type == "bleu_value_supported"
    ]
    assert unsupported and unsupported[0].severity == "blocker"
    assert report.decision == "blocked"


def test_table3_value_in_test_context_blocks(tmp_path):
    root, _config = _project(
        tmp_path,
        paragraphs=["在测试集上，big 模型取得 26.4 BLEU。"],
        items=[_table3_item()],
    )

    report = run_course_audit(root)

    condition = [
        finding for finding in report.findings if finding.check_type == "bleu_metric_condition"
    ]
    assert condition and condition[0].severity == "blocker"
    assert "测试集" in condition[0].actual


def test_table3_value_without_condition_needs_correction(tmp_path):
    root, _config = _project(
        tmp_path,
        paragraphs=["big 模型取得 26.4 BLEU。"],
        items=[_table3_item()],
    )

    report = run_course_audit(root)

    condition = [
        finding for finding in report.findings if finding.check_type == "bleu_metric_condition"
    ]
    assert condition and condition[0].severity == "major"
    assert report.decision == "needs_correction"


def test_dev_condition_is_recognised(tmp_path):
    root, _config = _project(
        tmp_path,
        paragraphs=["在 EN-DE 开发集 newstest2013 上，big 模型取得 26.4 BLEU (dev)。"],
        items=[_table3_item()],
    )

    report = run_course_audit(root)

    assert not [
        finding for finding in report.findings if finding.check_type == "bleu_metric_condition"
    ]


def test_formula_matches_after_controlled_normalisation(tmp_path):
    root, _config = _project(
        tmp_path,
        paragraphs=["公式如下。"],
        formula=r"Attention(Q, K, V) = \text{softmax}(\frac{QK^T}{\sqrt{d_k}})V",
        items=[_formula_item()],
    )

    report = run_course_audit(root)

    assert not [
        finding for finding in report.findings if finding.check_type == "formula_matches_review"
    ]
    assert report.decision == "passed"


def test_formula_denominator_change_is_detected(tmp_path):
    root, _config = _project(
        tmp_path,
        paragraphs=["公式如下。"],
        formula=r"Attention(Q, K, V) = \text{softmax}(\frac{QK^T}{\sqrt{d_v}})V",
        items=[_formula_item()],
    )

    report = run_course_audit(root)

    mismatches = [
        finding for finding in report.findings if finding.check_type == "formula_matches_review"
    ]
    assert mismatches and mismatches[0].severity == "blocker"
    assert report.decision == "blocked"


def test_formula_transpose_removal_is_detected(tmp_path):
    assert canonical_latex("softmax(QK^{T}/sqrt(d_k))V") != canonical_latex(
        "softmax(QK/sqrt(d_k))V"
    )


def test_unreviewed_formula_blocks(tmp_path):
    root, _config = _project(
        tmp_path,
        paragraphs=["公式如下。"],
        formula="PE(pos,2i)=sin(pos/10000^(2i/d_model))",
        items=[_formula_item()],
    )

    report = run_course_audit(root)

    unreviewed = [
        finding for finding in report.findings if finding.check_type == "formula_matches_review"
    ]
    assert unreviewed and unreviewed[0].severity == "blocker"


def test_reviewed_formula_absent_from_course_is_reported(tmp_path):
    root, _config = _project(
        tmp_path,
        paragraphs=["课程没有展示公式。"],
        items=[_formula_item()],
    )

    report = run_course_audit(root)

    absent = [
        finding for finding in report.findings if finding.check_type == "reviewed_formula_present"
    ]
    assert absent and absent[0].severity == "major"
    assert report.decision == "needs_correction"


def test_missing_source_text_is_not_a_pass(tmp_path):
    root, _config = _project(
        tmp_path,
        paragraphs=["英法任务：Table 2 与 §6.1 记为 41.0；arXiv 摘要记为 41.8，存在来源冲突。"],
        source_present=False,
    )

    report = run_course_audit(root)

    unavailable = [
        finding
        for finding in report.findings
        if finding.check_type == "evidence_item_source_available"
    ]
    assert unavailable
    assert report.decision != "passed"


def test_review_without_a_locator_blocks(tmp_path):
    root, _config = _project(
        tmp_path,
        paragraphs=["英法任务：Table 2 与 §6.1 记为 41.0；arXiv 摘要记为 41.8，存在来源冲突。"],
        items=[_review_item(locator="")],
    )

    report = run_course_audit(root)

    missing = [
        finding
        for finding in report.findings
        if finding.check_type == "evidence_item_locator_present"
    ]
    assert missing and missing[0].severity == "blocker"
    assert report.decision == "blocked"


def test_unreadable_content_blocks_instead_of_crashing(tmp_path):
    root, _config = _project(
        tmp_path,
        paragraphs=["英法任务：Table 2 与 §6.1 记为 41.0；arXiv 摘要记为 41.8，存在来源冲突。"],
    )
    (root / "content" / "public_content.json").write_text("{not-json", encoding="utf-8")

    report = run_course_audit(root)

    assert report.decision == "blocked"
    assert any(finding.check_type == "course_content_readable" for finding in report.findings)


def test_finding_ids_are_stable_across_runs(tmp_path):
    root, _config = _project(tmp_path, paragraphs=["模型取得 41.5 BLEU。"])

    first = run_course_audit(root)
    second = run_course_audit(root)

    assert [finding.finding_id for finding in first.findings] == [
        finding.finding_id for finding in second.findings
    ]
    assert len(first.findings) == len(second.findings)


def test_editing_content_invalidates_the_audit(tmp_path):
    root, _config = _project(
        tmp_path,
        paragraphs=["英法任务：Table 2 与 §6.1 记为 41.0；arXiv 摘要记为 41.8，存在来源冲突。"],
    )
    report = _audit(root)
    assert audit_is_current(root, report) == []

    write_json(
        root / "content" / "public_content.json",
        _content(["课程改了内容。"]),
    )

    assert audit_is_current(root, report) == ["content/public_content.json"]


def test_release_is_blocked_while_evidence_is_unsigned(tmp_path):
    root, config = _project(
        tmp_path,
        paragraphs=["英法任务：Table 2 与 §6.1 记为 41.0；arXiv 摘要记为 41.8，存在来源冲突。"],
    )
    approve(root, config, "v1", "reviewer")

    with pytest.raises(ValidationFailure) as caught:
        build_release(root, config, "v1")

    message = str(caught.value)
    assert "needs_human_review" in message
    assert "structured_evidence_signed" in message


def test_release_is_refused_when_the_conflict_is_undisclosed(tmp_path):
    root, config = _project(tmp_path, paragraphs=["Transformer 达到 41.8 BLEU。"])
    record_review(
        root,
        "review-table2-enfr",
        "Human Reviewer",
        "pass",
        "Checked Table 2 and the abstract; the course discloses both values.",
        conflict_ack=True,
    )
    approve(root, config, "v1", "reviewer")

    with pytest.raises(ValidationFailure) as caught:
        build_release(root, config, "v1")

    message = str(caught.value)
    assert "blocked" in message
    assert "source_conflict_disclosed" in message


def test_signed_and_audited_course_can_be_released(tmp_path):
    root, config = _project(
        tmp_path,
        paragraphs=["英法任务：Table 2 与 §6.1 记为 41.0；arXiv 摘要记为 41.8，存在来源冲突。"],
    )
    record_review(
        root,
        "review-table2-enfr",
        "Human Reviewer",
        "pass",
        "Compared Table 2, §6.1 and the abstract; the course discloses both values.",
        conflict_ack=True,
    )
    approve(root, config, "v1", "reviewer")

    manifest = build_release(root, config, "v1")

    assert manifest.version == "v1"
    _manifest, errors = verify_release(root, "v1")
    assert errors == []
    report = load_audit(root)
    assert report is not None and report.decision == "passed"


def test_release_check_detects_content_edited_after_the_audit(tmp_path):
    root, config = _project(
        tmp_path,
        paragraphs=["英法任务：Table 2 与 §6.1 记为 41.0；arXiv 摘要记为 41.8，存在来源冲突。"],
    )
    record_review(
        root,
        "review-table2-enfr",
        "Human Reviewer",
        "pass",
        "Compared Table 2, §6.1 and the abstract.",
        conflict_ack=True,
    )
    approve(root, config, "v1", "reviewer")
    build_release(root, config, "v1")

    write_json(root / "content" / "public_content.json", _content(["新的课程版本。"]))

    _manifest, errors = verify_release(root, "v1")
    assert any("course_content_audit_current" in error for error in errors)


def test_release_asset_must_match_the_audited_build(tmp_path):
    root, config = _project(
        tmp_path,
        paragraphs=["英法任务：Table 2 与 §6.1 记为 41.0；arXiv 摘要记为 41.8，存在来源冲突。"],
    )
    record_review(
        root,
        "review-table2-enfr",
        "Human Reviewer",
        "pass",
        "Compared Table 2, §6.1 and the abstract.",
        conflict_ack=True,
    )
    approve(root, config, "v1", "reviewer")
    build_release(root, config, "v1")

    write_text(
        root / "release" / "v1" / "slides" / "index.html",
        "<html><body><p>替换后的页面</p></body></html>",
    )

    _manifest, errors = verify_release(root, "v1")
    assert any("release_matches_audited_content" in error for error in errors)


def test_ai_substantive_review_is_not_a_human_signature(tmp_path):
    root, _config = _project(tmp_path)

    item = record_substantive_review(
        root,
        "review-table2-enfr",
        "claude-code (AI substantive review)",
        "consistent",
        ["source_transcription", "claim_interpretation"],
        "Compared Table 2, §6.1 and the abstract.",
        limitations="Course usage is checked by the course audit, not here.",
    )

    assert item.substantive_review is not None
    assert item.substantive_review.reviewer_kind == "ai"
    assert item.conclusion == "pending"
    assert item.reviewer == ""
    document = ReviewDocument.model_validate_json(
        (root / "internal" / "qa" / "structured_evidence_review.json").read_text(encoding="utf-8")
    )
    assert document.items[0].conclusion == "pending"
    assert all(
        verification.reviewed_by_human is False
        for verification in document.items[0].research_verification
    )
    audit = (
        (root / "internal" / "qa" / "evidence_review_audit.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    entry = json.loads(audit[0])
    assert entry["layer"] == "ai_substantive_review"
    assert entry["conclusion_unchanged"] == "pending"


def test_ai_substantive_review_requires_basis_and_scope(tmp_path):
    root, _config = _project(tmp_path)

    with pytest.raises(ValidationFailure, match="basis is required"):
        record_substantive_review(
            root, "review-table2-enfr", "ai", "consistent", ["source_transcription"], "  "
        )
    with pytest.raises(ValidationFailure, match="scope"):
        record_substantive_review(root, "review-table2-enfr", "ai", "consistent", [], "basis")
    with pytest.raises(ValidationFailure, match="unknown finding"):
        record_substantive_review(
            root, "review-table2-enfr", "ai", "passed", ["source_transcription"], "basis"
        )


def test_substantive_review_rejects_a_human_kind():
    with pytest.raises(ValidationError):
        ReviewItem.model_validate(
            {
                **_review_item().model_dump(mode="json"),
                "substantive_review": {
                    "reviewer": "someone",
                    "reviewer_kind": "human",
                    "reviewed_at": "2026-10-24T00:00:00Z",
                    "finding": "consistent",
                    "scopes": ["source_transcription"],
                    "basis": "basis",
                },
            }
        )


def test_cli_review_evidence_ai_records_separately(tmp_path, monkeypatch):
    root, _config = _project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(
        app,
        [
            "review-evidence-ai",
            str(root),
            "--review-id",
            "review-table2-enfr",
            "--by",
            "claude-code (AI substantive review)",
            "--finding",
            "consistent",
            "--scope",
            "source_transcription",
            "--basis",
            "Compared Table 2, §6.1 and the abstract.",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "人工结论保持不变: pending" in result.output
    document = ReviewDocument.model_validate_json(
        (root / "internal" / "qa" / "structured_evidence_review.json").read_text(encoding="utf-8")
    )
    assert document.items[0].conclusion == "pending"
    assert document.items[0].substantive_review is not None


def test_cli_audit_course_exits_non_zero_on_blockers(tmp_path, monkeypatch):
    root, _config = _project(tmp_path, paragraphs=["模型取得 41.5 BLEU。"])
    monkeypatch.chdir(tmp_path)

    result = CliRunner().invoke(app, ["audit-course", str(root)])

    assert result.exit_code == 1
    assert "bleu_value_supported" in result.output
    assert load_audit(root) is not None


def _write_script(root: Path, narration: str) -> None:
    write_json(
        root / "internal" / "speaker_script.json",
        {
            "project_id": "audit-course",
            "language": "zh-CN",
            "sections": [{"slide_id": "slide-001", "narration": narration}],
        },
    )


def test_unregistered_narration_number_blocks(tmp_path):
    """F-01 回归：口播里的超参数必须能在该节绑定的证据里找到。"""

    root, _config = _project(tmp_path, paragraphs=["本节没有数字。"])
    _write_script(root, "优化器用 Adam，beta2 等于 0.98，warmup 4000 步。")

    report = _audit(root)

    findings = [item for item in report.findings if item.check_type == "number_coverage"]
    assert findings, "未登记的口播数字必须报出"
    assert findings[0].severity == "major"
    assert "0.98" in findings[0].actual or "4000" in findings[0].actual


def test_registered_narration_number_is_covered(tmp_path):
    root, _config = _project(tmp_path, paragraphs=["结果 41.0 BLEU。"])
    _write_script(root, "英法方向采用 41.0 BLEU 的口径。")

    report = _audit(root)

    assert not [item for item in report.findings if item.check_type == "number_coverage"]


def _leak_html() -> str:
    return (
        '<html><body><div class="formula">' + "\\mathrm{Attention}(Q,K,V)" + "</div></body></html>"
    )


def test_raw_latex_in_build_is_a_blocker(tmp_path):
    root, _config = _project(
        tmp_path,
        paragraphs=["本节没有数字。"],
        build_html=_leak_html(),
    )

    report = _audit(root)

    leaks = [item for item in report.findings if item.check_type == "raw_latex_leak"]
    assert leaks and leaks[0].severity == "blocker"


def test_external_asset_dependency_is_a_blocker(tmp_path):
    root, _config = _project(
        tmp_path,
        paragraphs=["本节没有数字。"],
        build_html=(
            '<html><head><script src="https://cdn.example.com/katex.js"></script></head>'
            "<body><p>正文</p></body></html>"
        ),
    )

    report = _audit(root)

    external = [item for item in report.findings if item.check_type == "external_asset_dependency"]
    assert external and external[0].severity == "blocker"


def _post_ln_item() -> ReviewItem:
    return _review_item(
        review_id="review-formula-postln",
        local_evidence_id="evidence-004",
        paper_id="paper-002",
        locator="§3.1",
        evidence_kind="formula",
        claim="LayerNorm(x + Sublayer(x))",
        conflict_status="none",
        research_verification=[
            {
                "research_finding": "verified",
                "details": "§3.1 defines the sub-layer output.",
                "transcribed_expression": "\\mathrm{LayerNorm}(x+\\mathrm{Sublayer}(x))",
            }
        ],
    )


def test_pre_ln_tamper_is_detected(tmp_path):
    """把 Post-LN 公式改成 Pre-LN 必须触发 blocker。"""

    root, _config = _project(
        tmp_path,
        paragraphs=["残差结构。"],
        formula="\\mathrm{Sublayer}(x)+\\mathrm{LayerNorm}(x)",
        items=[_post_ln_item()],
    )

    report = _audit(root)

    mismatches = [item for item in report.findings if item.check_type == "formula_matches_review"]
    assert mismatches and mismatches[0].severity == "blocker"


def test_post_ln_formula_passes_when_unchanged(tmp_path):
    root, _config = _project(
        tmp_path,
        paragraphs=["残差结构。"],
        formula="\\mathrm{LayerNorm}(x+\\mathrm{Sublayer}(x))",
        items=[_post_ln_item()],
    )

    report = _audit(root)

    assert report.decision == "passed", [item.check_type for item in report.findings]


def test_removed_protected_condition_blocks(tmp_path):
    root, _config = _project(tmp_path, paragraphs=["自注意力比循环层更快。"])
    write_json(
        root / "internal" / "plan" / "course_guards.json",
        {
            "guards": [
                {
                    "guard_id": "complexity-condition",
                    "slide_id": "slide-001",
                    "required": ["序列长度 n 小于表示维度 d"],
                    "reason": "删除条件会把有条件的结论夸大为无条件优势。",
                }
            ]
        },
    )

    report = _audit(root)

    guards = [item for item in report.findings if item.check_type == "protected_condition_present"]
    assert guards and guards[0].severity == "blocker"


def test_quoted_protected_condition_passes(tmp_path):
    root, _config = _project(
        tmp_path, paragraphs=["论文的条件是序列长度 n 小于表示维度 d 时更快。"]
    )
    write_json(
        root / "internal" / "plan" / "course_guards.json",
        {
            "guards": [
                {
                    "guard_id": "complexity-condition",
                    "slide_id": "slide-001",
                    "required": ["序列长度 n 小于表示维度 d"],
                    "reason": "删除条件会把有条件的结论夸大为无条件优势。",
                }
            ]
        },
    )

    report = _audit(root)

    assert not [
        item for item in report.findings if item.check_type == "protected_condition_present"
    ]


def test_guard_without_reason_is_ignored(tmp_path):
    root, _config = _project(tmp_path, paragraphs=["本节没有数字。"])
    write_json(
        root / "internal" / "plan" / "course_guards.json",
        {"guards": [{"guard_id": "silent", "slide_id": "slide-001", "required": ["缺失短语"]}]},
    )

    report = _audit(root)

    assert not [
        item for item in report.findings if item.check_type == "protected_condition_present"
    ]


def test_reg_003_big_qualifier_missing_is_reported(tmp_path):
    """TDD-001 REG-003: 28.4 / 26.4 must stay labelled as the big model."""

    root, _config = _project(
        tmp_path,
        paragraphs=["在 EN-DE 开发集 newstest2013 上，模型取得 26.4 BLEU (dev)。"],
        items=[_table3_item()],
    )

    report = run_course_audit(root)

    variant = [
        finding for finding in report.findings if finding.check_type == "bleu_variant_qualifier"
    ]
    assert variant and variant[0].severity == "advisory"
    assert "big" in variant[0].expected


def test_reg_003_big_qualifier_present_is_accepted(tmp_path):
    root, _config = _project(
        tmp_path,
        paragraphs=["在 EN-DE 开发集 newstest2013 上，big 模型取得 26.4 BLEU (dev)。"],
        items=[_table3_item()],
    )

    report = run_course_audit(root)

    assert not [
        finding for finding in report.findings if finding.check_type == "bleu_variant_qualifier"
    ]
