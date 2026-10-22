from content_studio.models import (
    ParagraphBlock,
    PublicContent,
    PublicSlide,
    ReadingEdition,
    ReadingSection,
    TableBlock,
)
from content_studio.paths import template_dir
from content_studio.rendering import build_public_html, build_reading_html


def _content() -> PublicContent:
    return PublicContent(
        project_id="test-course",
        title="公开课程",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="标题",
                body=[
                    ParagraphBlock(text="公开正文"),
                    TableBlock(columns=["指标", "数值"], rows=[["延迟", "1.2 ms"]]),
                ],
                source_ids=["source-001"],
            )
        ],
    )


def test_public_builder_renders_only_public_model(tmp_path):
    output = build_public_html(_content(), template_dir(), tmp_path / "index.html")
    html = output.read_text(encoding="utf-8")
    assert "公开正文" in html
    assert "<table>" in html
    assert "source-001" in html
    assert "speaker_script" not in html
    assert "口播稿" not in html


def test_reading_edition_renders(tmp_path):
    edition = ReadingEdition(
        project_id="test-course",
        title="阅读版",
        abstract="摘要正文",
        sections=[
            ReadingSection(slide_id="slide-001", title="第一节", paragraphs=["深入阅读内容"])
        ],
        references=["Example et al. 2026"],
    )
    output = build_reading_html(edition, template_dir(), tmp_path / "reading.html")
    html = output.read_text(encoding="utf-8")
    assert "深入阅读内容" in html
    assert "Example et al. 2026" in html


def test_public_builder_escapes_html(tmp_path):
    content = PublicContent(
        project_id="test-course",
        title="<script>alert(1)</script>",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="安全",
                body=[ParagraphBlock(text="<img src=x onerror=alert(1)>")],
            )
        ],
    )
    html = build_public_html(content, template_dir(), tmp_path / "index.html").read_text(
        encoding="utf-8"
    )
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
