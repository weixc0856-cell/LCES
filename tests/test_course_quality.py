from __future__ import annotations

from pathlib import Path

import pytest

from content_studio.course_quality import (
    CourseAcceptance,
    CourseContract,
    CourseModule,
    CourseObjective,
    TimingEvidence,
    load_quality,
    run_course_quality_audit,
    write_quality,
)
from content_studio.errors import ValidationFailure
from content_studio.models import (
    CheckBlock,
    CheckResult,
    ContentOutline,
    FormulaBlock,
    OutlineSection,
    ParagraphBlock,
    ProjectConfig,
    PublicContent,
    PublicSlide,
    QAReport,
    ReadingEdition,
    ReadingSection,
    ScriptSection,
    SpeakerScript,
)
from content_studio.paths import ensure_project_layout, template_dir
from content_studio.release import approve, build_release
from content_studio.rendering import build_public_html
from content_studio.utils import sha256_file, utc_now, write_json, write_text
from content_studio.validation import run_release_checks


def _content(formula: bool = True, check: bool = True) -> PublicContent:
    body: list[object] = [
        ParagraphBlock(
            text=(
                "缩放点积注意力把查询、键和值映射为输出。分数矩阵按行做 softmax，"
                "再对值加权求和；这段文字足够长，用来满足产品契约的实质内容检查。"
            )
        )
    ]
    if formula:
        body.append(FormulaBlock(latex="Attention(Q,K,V)=softmax(QK^T/sqrt(d_k))V"))
    if check:
        body.append(
            CheckBlock(
                question="缩放发生在 softmax 之前还是之后？",
                answer="之前。",
                rationale="缩放控制点积方差。",
            )
        )
    return PublicContent(
        project_id="quality-course",
        title="质量验收课程",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="注意力",
                body=body,  # type: ignore[arg-type]
                source_ids=["source-001"],
            )
        ],
    )


def _project(
    tmp_path: Path,
    *,
    formula: bool = True,
    check: bool = True,
    status: str = "approved",
    contract_target: float = 20,
    project_target: float = 20,
    timing: str = "measured",
    acceptance: bool = True,
) -> Path:
    root = ensure_project_layout(tmp_path / "project")
    (root / "project.yaml").write_text(
        "project_id: quality-course\n"
        "title: 质量验收课程\n"
        f"target_duration_minutes: {project_target}\n",
        encoding="utf-8",
    )
    write_json(root / "content" / "public_content.json", _content(formula, check))
    write_json(
        root / "content" / "reading_edition.json",
        ReadingEdition(
            project_id="quality-course",
            title="质量验收课程",
            abstract="摘要",
            sections=[
                ReadingSection(
                    slide_id="slide-001",
                    title="注意力",
                    paragraphs=["阅读版段落。"],
                    source_ids=["source-001"],
                )
            ],
            references=["source-001"],
        ),
    )
    write_json(
        root / "content" / "outline.json",
        ContentOutline(
            project_id="quality-course",
            title="质量验收课程",
            sections=[
                OutlineSection(
                    slide_id="slide-001",
                    title="注意力",
                    learning_objectives=["解释注意力"],
                    key_points=["softmax"],
                    evidence_ids=["evidence-001"],
                    estimated_minutes=20,
                )
            ],
            total_minutes=20,
        ),
    )
    write_json(
        root / "internal" / "speaker_script.json",
        SpeakerScript(
            project_id="quality-course",
            sections=[
                ScriptSection(
                    slide_id="slide-001",
                    narration="这是一段足够长的口播稿，用来检查口播稿与幻灯片是否一一对应。",
                    estimated_seconds=1200,
                )
            ],
            total_estimated_seconds=1200,
        ),
    )
    write_text(root / "build" / "slides" / "index.html", "<html><body>课程</body></html>")
    write_text(root / "build" / "reading_edition.html", "<html><body>阅读版</body></html>")
    write_json(
        root / "internal" / "qa" / "qa_report.json",
        QAReport(
            project_id="quality-course",
            provider="local",
            checks=[
                CheckResult(
                    check_id="browser_pages_load",
                    gate="gate_3_engineering",
                    status="pass",
                    message="ok",
                ),
                CheckResult(
                    check_id="browser_layout_no_overflow",
                    gate="gate_3_engineering",
                    status="pass",
                    message="ok",
                ),
            ],
        ),
    )
    contract = CourseContract(
        project_id="quality-course",
        version="1.0",
        status=status,  # type: ignore[arg-type]
        approved_by="product-owner" if status == "approved" else "",
        audience="测试受众",
        target_duration_minutes=contract_target,
        timing_rule="实测",
        objectives=[
            CourseObjective(
                objective_id="objective-attention",
                statement="解释注意力",
                slide_ids=["slide-001"],
            )
        ],
        modules=[
            CourseModule(
                module_id="module-01",
                title="注意力",
                target_minutes=20,
                slide_ids=["slide-001"],
            )
        ],
        deliverables=["幻灯片", "阅读版", "口播稿", "学习检查"],
        required_formula_count=1,
        required_check_count=1,
        manual_items=["课程产品验收"],
    )
    write_json(root / "internal" / "plan" / "course_contract.json", contract)
    if timing == "measured":
        write_json(
            root / "internal" / "qa" / "timing_evidence.json",
            TimingEvidence(
                project_id="quality-course",
                method="tts_readthrough",
                measured_seconds=1200,
                target_minutes=20,
                script_sha256=sha256_file(root / "internal" / "speaker_script.json"),
                voice="test",
                generated_at=utc_now(),
            ),
        )
    elif timing == "estimate":
        write_json(
            root / "internal" / "qa" / "timing_evidence.json",
            TimingEvidence(
                project_id="quality-course",
                method="estimate",
                measured_seconds=1200,
                target_minutes=20,
                script_sha256=sha256_file(root / "internal" / "speaker_script.json"),
                generated_at=utc_now(),
            ),
        )
    report = run_course_quality_audit(root)
    write_quality(root, report)
    if acceptance:
        write_json(
            root / "internal" / "qa" / "course_acceptance.json",
            CourseAcceptance(
                project_id="quality-course",
                contract_version="1.0",
                content_version=report.content_version,
                reviewer="human",
                reviewed_at=utc_now(),
                decision="pass",
                timing_confirmed=True,
                visual_confirmed=True,
                checks_confirmed=True,
            ),
        )
        write_quality(root, run_course_quality_audit(root))
    return root


def _check_ids(report) -> dict[str, str]:
    return {finding.check_id: finding.severity for finding in report.findings}


def test_complete_course_passes_gate_b(tmp_path):
    root = _project(tmp_path)

    report = load_quality(root)

    assert report is not None
    assert report.decision == "passed", [f.message for f in report.findings]
    assert report.summary == {"blocker": 0, "human": 0}


def test_missing_contract_blocks(tmp_path):
    root = _project(tmp_path)
    (root / "internal" / "plan" / "course_contract.json").unlink()

    report = run_course_quality_audit(root)

    assert report.decision == "blocked"
    assert "product_contract_present" in _check_ids(report)


def test_target_downgrade_blocks(tmp_path):
    root = _project(tmp_path, contract_target=20, project_target=12)

    report = run_course_quality_audit(root)

    assert _check_ids(report)["target_not_downgraded"] == "blocker"


def test_missing_learning_check_blocks(tmp_path):
    root = _project(tmp_path, check=False)

    report = run_course_quality_audit(root)

    assert "deliverable_checks" in _check_ids(report)
    assert report.decision == "blocked"


def test_missing_formula_blocks(tmp_path):
    root = _project(tmp_path, formula=False)

    report = run_course_quality_audit(root)

    assert "deliverable_formulas" in _check_ids(report)


def test_estimate_timing_blocks(tmp_path):
    root = _project(tmp_path, timing="estimate")

    report = run_course_quality_audit(root)

    assert "timing_measured" in _check_ids(report)
    assert report.decision == "blocked"


def test_draft_contract_needs_human(tmp_path):
    root = _project(tmp_path, status="draft")

    report = run_course_quality_audit(root)

    assert report.decision == "needs_human_review"
    assert _check_ids(report)["product_contract_approved"] == "human"


def test_missing_acceptance_needs_human(tmp_path):
    root = _project(tmp_path, acceptance=False)

    report = run_course_quality_audit(root)

    assert report.decision == "needs_human_review"
    assert "human_course_acceptance" in _check_ids(report)


def test_acceptance_is_invalidated_by_content_change(tmp_path):
    root = _project(tmp_path)
    write_json(root / "content" / "public_content.json", _content(formula=False))

    report = run_course_quality_audit(root)

    assert "acceptance_content_version" in _check_ids(report)
    assert report.decision == "blocked"


def test_release_gate_blocks_a_product_blocker(tmp_path):
    root = _project(tmp_path, check=False)
    release = tmp_path / "release"
    release.mkdir()

    checks = run_release_checks(
        release,
        manifest=None,
        approval_required=False,
        approval_present=True,
        project_dir=root,
    )

    assert any(
        item.check_id == "course_product_qualified" and item.status == "fail" for item in checks
    )


def test_release_gate_reports_product_human_pending(tmp_path):
    root = _project(tmp_path, acceptance=False)
    release = tmp_path / "release"
    release.mkdir()

    checks = run_release_checks(
        release,
        manifest=None,
        approval_required=False,
        approval_present=True,
        project_dir=root,
    )

    assert any(
        item.check_id == "course_product_human_pending" and item.status == "fail" for item in checks
    )
    assert any(
        item.check_id == "course_product_qualified" and item.status == "pass" for item in checks
    )


def test_release_gate_skips_gate_b_without_a_contract(tmp_path):
    root = _project(tmp_path)
    (root / "internal" / "plan" / "course_contract.json").unlink()
    (root / "internal" / "qa" / "course_quality_audit.json").unlink()
    release = tmp_path / "release"
    release.mkdir()

    checks = run_release_checks(
        release,
        manifest=None,
        approval_required=False,
        approval_present=True,
        project_dir=root,
    )

    product = [item for item in checks if item.check_id == "course_product_qualified"]
    assert product and product[0].status == "not_run"


def test_release_is_blocked_by_gate_b(tmp_path):
    root = _project(tmp_path, check=False)
    config = ProjectConfig(project_id="quality-course", title="质量验收课程")
    approve(root, config, "v1", "reviewer")

    with pytest.raises(ValidationFailure) as caught:
        build_release(root, config, "v1")

    assert "course_product_qualified" in str(caught.value)


def test_check_block_renders_question_and_answer(tmp_path):
    output = build_public_html(
        _content(),
        template_dir(),
        tmp_path / "index.html",
        use_registry=False,
    )
    html = output.read_text(encoding="utf-8")

    assert "学习检查" in html
    assert "缩放发生在 softmax 之前还是之后？" in html
    assert "<details>" in html
    assert "缩放控制点积方差。" in html
