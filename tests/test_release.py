import zipfile
from pathlib import Path

import pytest

from content_studio.errors import ConfigurationError, ValidationFailure
from content_studio.models import (
    CheckResult,
    ParagraphBlock,
    ProjectConfig,
    PublicContent,
    PublicSlide,
    QAReport,
)
from content_studio.paths import ensure_project_layout
from content_studio.release import approve, build_release, verify_release
from content_studio.utils import write_json, write_text
from content_studio.validation import run_release_checks

GATES = ("gate_1_research", "gate_2_content", "gate_3_engineering", "gate_4_release")


def _ready_project(tmp_path: Path) -> tuple[Path, ProjectConfig]:
    root = ensure_project_layout(tmp_path / "project")
    config = ProjectConfig(project_id="release-course", title="发布测试")
    content = PublicContent(
        project_id=config.project_id,
        title=config.title,
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="第一节",
                body=[ParagraphBlock(text="公开正文")],
                source_ids=["source-001"],
            )
        ],
    )
    write_json(root / "content" / "public_content.json", content)
    write_text(root / "build" / "slides" / "index.html", "<html><body>公开正文</body></html>")
    write_text(root / "build" / "reading_edition.html", "<html><body>阅读版</body></html>")
    report = QAReport(
        project_id=config.project_id,
        provider="deepseek",
        checks=[
            CheckResult(check_id=f"{gate}-ok", gate=gate, status="pass", message="ok")
            for gate in GATES
        ],
    )
    write_json(root / "internal" / "qa" / "qa_report.json", report)
    return root, config


def test_release_rejects_unexpected_files(tmp_path):
    release = tmp_path / "release"
    (release / "slides").mkdir(parents=True)
    (release / "slides" / "index.html").write_text("<html></html>", encoding="utf-8")
    (release / "notes.md").write_text("draft", encoding="utf-8")
    checks = run_release_checks(
        release, manifest=None, approval_required=False, approval_present=False
    )
    assert any(item.check_id == "allowlist_only" and item.status == "fail" for item in checks)


def test_release_rejects_internal_markers(tmp_path):
    release = tmp_path / "release"
    (release / "slides").mkdir(parents=True)
    (release / "slides" / "index.html").write_text(
        "<html>口播稿：内部材料</html>", encoding="utf-8"
    )
    checks = run_release_checks(
        release, manifest=None, approval_required=False, approval_present=False
    )
    assert any(item.check_id == "no_internal_markers" and item.status == "fail" for item in checks)


def test_release_rejects_secret_patterns(tmp_path):
    release = tmp_path / "release"
    (release / "slides").mkdir(parents=True)
    (release / "slides" / "index.html").write_text(
        "<html>api_key = sk-abcdefghijklmnopqrstuvwx</html>", encoding="utf-8"
    )
    checks = run_release_checks(
        release, manifest=None, approval_required=False, approval_present=False
    )
    assert any(item.check_id == "no_secret_patterns" and item.status == "fail" for item in checks)


def test_full_release_build_and_verify(tmp_path):
    root, config = _ready_project(tmp_path)
    approve(root, config, "v1", "reviewer")

    manifest = build_release(root, config, "v1")

    assert {item.path for item in manifest.files} == {
        "slides/index.html",
        "reading_edition.html",
        "metadata/description.md",
    }
    archive = root / "build" / "artifacts" / "release-course-v1.zip"
    assert archive.is_file()
    with zipfile.ZipFile(archive) as bundle:
        names = bundle.namelist()
    assert "release-course/release_manifest.json" in names
    assert "release-course/slides/index.html" in names

    _manifest, errors = verify_release(root, "v1")
    assert errors == []


def test_release_requires_approval(tmp_path):
    root, config = _ready_project(tmp_path)
    with pytest.raises(ValidationFailure):
        build_release(root, config, "v1")


def test_verify_detects_tampering(tmp_path):
    root, config = _ready_project(tmp_path)
    approve(root, config, "v1", "reviewer")
    build_release(root, config, "v1")

    (root / "release" / "v1" / "slides" / "index.html").write_text(
        "<html>tampered</html>", encoding="utf-8"
    )
    _manifest, errors = verify_release(root, "v1")
    assert any("manifest_hashes_match" in error for error in errors)


def test_rebuild_same_version_requires_force(tmp_path):
    root, config = _ready_project(tmp_path)
    approve(root, config, "v1", "reviewer")
    build_release(root, config, "v1")
    with pytest.raises(ConfigurationError):
        build_release(root, config, "v1")
