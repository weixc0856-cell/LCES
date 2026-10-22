import pytest
from pydantic import ValidationError

from content_studio.models import (
    BulletsBlock,
    CheckResult,
    ParagraphBlock,
    ProjectConfig,
    PublicContent,
    PublicSlide,
    QAReport,
    SpeakerScript,
    TableBlock,
)


def test_public_content_validates():
    content = PublicContent(
        project_id="sample-course",
        title="示例",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="引言",
                body=[ParagraphBlock(text="公开正文")],
                source_ids=["source-001"],
            )
        ],
    )
    assert content.slides[0].body[0].type == "paragraph"


def test_public_content_rejects_internal_field():
    with pytest.raises(ValidationError):
        PublicContent.model_validate(
            {
                "project_id": "sample-course",
                "title": "示例",
                "language": "zh-CN",
                "speaker_script": "must not be public",
                "slides": [
                    {
                        "slide_id": "slide-001",
                        "title": "T",
                        "body": [{"type": "paragraph", "text": "B"}],
                        "source_ids": [],
                    }
                ],
            }
        )


def test_public_block_discriminator_rejects_unknown_type():
    with pytest.raises(ValidationError):
        PublicContent.model_validate(
            {
                "project_id": "sample-course",
                "title": "示例",
                "slides": [
                    {
                        "slide_id": "slide-001",
                        "title": "T",
                        "body": [{"type": "speaker_note", "text": "泄漏"}],
                        "source_ids": [],
                    }
                ],
            }
        )


def test_table_rejects_ragged_rows():
    with pytest.raises(ValidationError):
        TableBlock(columns=["a", "b"], rows=[["1"]])


def test_project_slug_validation():
    ProjectConfig(project_id="valid-project", title="Valid")
    with pytest.raises(ValidationError):
        ProjectConfig(project_id="../outside", title="Invalid")


def test_speaker_script_rejects_public_fields():
    with pytest.raises(ValidationError):
        SpeakerScript.model_validate(
            {
                "project_id": "sample-course",
                "slides": [],
                "sections": [{"slide_id": "slide-001", "narration": "讲稿"}],
            }
        )


def test_qa_report_blocking_failures():
    report = QAReport(
        project_id="sample-course",
        checks=[
            CheckResult(
                check_id="c1", gate="gate_1_research", status="fail", message="bad", blocking=True
            ),
            CheckResult(
                check_id="c2", gate="gate_2_content", status="warn", message="meh", blocking=True
            ),
        ],
    )
    assert len(report.blocking_failures) == 1
    assert report.gate_status()["gate_1_research"] == "fail"


def test_bullets_block():
    block = BulletsBlock(items=["一", "二"])
    assert block.type == "bullets"
