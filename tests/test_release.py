import zipfile
from pathlib import Path

import pytest

from content_studio.errors import ConfigurationError, ValidationFailure
from content_studio.media import MediaInfo
from content_studio.models import (
    CheckResult,
    FrameEntry,
    FrameManifest,
    ParagraphBlock,
    ProjectConfig,
    PublicContent,
    PublicSlide,
    QAReport,
    SceneFrameSpan,
)
from content_studio.paths import ensure_project_layout
from content_studio.release import approve, build_release, verify_release
from content_studio.utils import sha256_file, write_json, write_text
from content_studio.validation import content_version, run_release_checks

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
    _version, _bound = content_version(root)
    report = QAReport(
        project_id=config.project_id,
        provider="deepseek",
        checks=[
            CheckResult(check_id=f"{gate}-ok", gate=gate, status="pass", message="ok")
            for gate in GATES
        ],
        content_version=_version,
        content_files=_bound,
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


def _frame_manifest() -> FrameManifest:
    return FrameManifest(
        build_id="build-gate-001",
        asset_id="course-v1",
        fps_num=30,
        width=320,
        height=180,
        total_frames=3,
        scenes=[SceneFrameSpan(scene_id="scene-001", start_frame=0, end_frame=3)],
        frames=[
            FrameEntry(
                index=index,
                path=f"frames/project/{index:06d}.png",
                sha256="a" * 64,
                width=320,
                height=180,
            )
            for index in range(3)
        ],
    )


def _gate4_setup(tmp_path):
    release = tmp_path / "release"
    (release / "media").mkdir(parents=True)
    video = release / "media" / "course.mp4"
    video.write_bytes(b"video-bytes")
    project = tmp_path / "project"
    (project / "internal" / "qa").mkdir(parents=True)
    write_json(project / "internal" / "qa" / "frame_manifest.json", _frame_manifest())
    return release, video, project


def _fake_media(monkeypatch):
    monkeypatch.setattr("content_studio.validation.tool_status", lambda: (True, ""))
    monkeypatch.setattr(
        "content_studio.validation.probe_media",
        lambda path: MediaInfo(
            path=str(path),
            duration_seconds=0.1,
            width=320,
            height=180,
            video_codec="h264",
            audio_codec="",
            size_bytes=5,
        ),
    )


def test_gate4_detects_video_manifest_mismatch(tmp_path, monkeypatch):
    release, _video, project = _gate4_setup(tmp_path)
    _fake_media(monkeypatch)
    monkeypatch.setattr(
        "content_studio.validation.verify_video_against_manifest",
        lambda video, manifest: ["video decodes 2 frames, manifest has 3"],
    )
    checks = run_release_checks(
        release,
        manifest=None,
        approval_required=False,
        approval_present=False,
        project_dir=project,
    )
    assert any(
        item.check_id == "video_matches_manifest" and item.status == "fail" for item in checks
    )


def test_gate4_accepts_matching_video_and_hash(tmp_path, monkeypatch):
    release, video, project = _gate4_setup(tmp_path)
    _fake_media(monkeypatch)
    monkeypatch.setattr(
        "content_studio.validation.verify_video_against_manifest",
        lambda video_path, manifest: [],
    )
    write_json(
        project / "internal" / "qa" / "encode_report.json",
        {"video_sha256": sha256_file(video)},
    )
    checks = run_release_checks(
        release,
        manifest=None,
        approval_required=False,
        approval_present=False,
        project_dir=project,
    )
    statuses = {
        item.check_id: item.status
        for item in checks
        if item.check_id in {"video_matches_manifest", "video_hash_matches_encode_report"}
    }
    assert statuses == {
        "video_matches_manifest": "pass",
        "video_hash_matches_encode_report": "pass",
    }


def test_gate4_detects_a_stale_encode_report(tmp_path, monkeypatch):
    release, _video, project = _gate4_setup(tmp_path)
    _fake_media(monkeypatch)
    monkeypatch.setattr(
        "content_studio.validation.verify_video_against_manifest",
        lambda video_path, manifest: [],
    )
    write_json(
        project / "internal" / "qa" / "encode_report.json",
        {"video_sha256": "b" * 64},
    )
    checks = run_release_checks(
        release,
        manifest=None,
        approval_required=False,
        approval_present=False,
        project_dir=project,
    )
    assert any(
        item.check_id == "video_hash_matches_encode_report" and item.status == "fail"
        for item in checks
    )


def test_release_refuses_a_qa_report_without_content_binding(tmp_path):
    root, config = _ready_project(tmp_path)
    approve(root, config, "v1", "reviewer")
    # Simulate a report written before the binding existed.
    report = QAReport(
        project_id=config.project_id,
        checks=[
            CheckResult(check_id=f"{gate}-ok", gate=gate, status="pass", message="ok")
            for gate in GATES
        ],
    )
    write_json(root / "internal" / "qa" / "qa_report.json", report)
    with pytest.raises(ValidationFailure, match="no content binding"):
        build_release(root, config, "v1")


def test_release_refuses_a_pass_after_content_changed(tmp_path):
    root, config = _ready_project(tmp_path)
    approve(root, config, "v1", "reviewer")
    # Editing the built page after `validate` makes the old pass describe other bytes.
    write_text(
        root / "build" / "slides" / "index.html",
        "<html><body>公开正文（未再验证）</body></html>",
    )
    with pytest.raises(ValidationFailure, match="changed after"):
        build_release(root, config, "v1")


def test_manifest_records_version_lineage(tmp_path):
    root, config = _ready_project(tmp_path)
    approve(root, config, "v1", "reviewer")

    manifest = build_release(root, config, "v1")

    current, _files = content_version(root)
    assert manifest.manifest_schema_version == "2.0"
    assert manifest.content_version == current
    assert manifest.decision == "approved"
    assert manifest.disclosures == []
    assert manifest.course_product == "not_applicable"
    assert manifest.acceptance_sha256 == ""
    assert manifest.limitations == []
    # The temporary project is not a Git worktree; absence is recorded, not invented.
    assert manifest.code_version == "" or len(manifest.code_version) >= 40


def test_release_check_rejects_incomplete_lineage(tmp_path):
    root, config = _ready_project(tmp_path)
    approve(root, config, "v1", "reviewer")
    manifest = build_release(root, config, "v1")
    broken = manifest.model_copy(update={"content_version": "", "decision": ""})
    write_json(root / "release" / "v1" / "release_manifest.json", broken)

    _manifest, errors = verify_release(root, "v1")

    assert any("manifest_lineage" in error for error in errors)


def test_manifest_discloses_not_run_checks(tmp_path):
    """A release with NOT_RUN checks is `approved_with_disclosures`, not `approved`."""

    root, config = _ready_project(tmp_path)
    approve(root, config, "v1", "reviewer")
    version, bound = content_version(root)
    report = QAReport(
        project_id=config.project_id,
        checks=[
            CheckResult(check_id=f"{gate}-ok", gate=gate, status="pass", message="ok")
            for gate in GATES
        ]
        + [
            CheckResult(
                check_id="scientific_review",
                gate="gate_1_research",
                status="not_run",
                message="需要专家复核",
                blocking=False,
            )
        ],
        content_version=version,
        content_files=bound,
    )
    write_json(root / "internal" / "qa" / "qa_report.json", report)

    manifest = build_release(root, config, "v1")

    assert manifest.decision == "approved_with_disclosures"
    assert any("scientific_review" in item for item in manifest.limitations)
    _manifest, errors = verify_release(root, "v1")
    assert errors == []
