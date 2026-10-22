"""P2.1 production path: content block -> registry -> video -> asset record.

The real renderer is Linux-only and runs in the CI motion job; these tests use
a stub animation renderer to exercise the production wiring on any host. The
stub writes the same artifact set the real adapter produces.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from content_studio.errors import RenderError, ValidationFailure
from content_studio.models import (
    AnimationBlock,
    FrameEntry,
    FrameManifest,
    ParagraphBlock,
    ProjectConfig,
    PublicContent,
    PublicSlide,
    SceneFrameSpan,
)
from content_studio.paths import template_dir
from content_studio.release import build_release
from content_studio.renderers import RenderContext, Renderer, RendererRegistry, RenderResult
from content_studio.rendering import BUILD_MARKER, build_public_html
from content_studio.utils import sha256_file
from content_studio.visuals import render_content_visuals, verify_build_assets

BUILD_ID = "build-20261022-120000-abc123"


def _scene_payload(*, project_id: str = "p21-demo", output_path: str = "build/media/course.mp4"):
    return {
        "scene_set": {
            "scenes": [
                {
                    "scene_id": "scene-001",
                    "scene_type": "title",
                    "duration_ms": 1000,
                    "data": {"title": "P2.1", "subtitle": "production"},
                }
            ]
        },
        "video": {
            "project_id": project_id,
            "video_id": "course-v1",
            "content_version": "v1",
            "width": 640,
            "height": 360,
            "fps_num": 30,
            "fps_den": 1,
            "scene_ids": ["scene-001"],
            "output_path": output_path,
            "renderer": "motion_canvas.renderer",
            "renderer_version": "0.1.0",
        },
    }


def _project(tmp_path: Path, *, payload: dict | None = None) -> Path:
    project = tmp_path / "project"
    (project / "content" / "scenes").mkdir(parents=True)
    (project / "build" / "slides").mkdir(parents=True)
    (project / "internal" / "qa").mkdir(parents=True)
    (project / "content" / "scenes" / "course.json").write_text(
        json.dumps(payload or _scene_payload()), encoding="utf-8"
    )
    (project / "content" / "public_content.json").write_text("{}", encoding="utf-8")
    return project


def _content(*, project_id: str = "p21-demo", blocks: list | None = None) -> PublicContent:
    return PublicContent(
        project_id=project_id,
        title="P2.1",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="第一节",
                body=blocks
                or [
                    ParagraphBlock(text="正文"),
                    AnimationBlock(
                        scene_file="content/scenes/course.json",
                        alt="课程动画",
                        caption="系统流程",
                    ),
                ],
            )
        ],
    )


class _StubAnimationRenderer(Renderer):
    name = "motion_canvas.renderer"
    version = "0.1.0"
    visual_types = frozenset({"animation"})

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail

    def render(self, spec, context: RenderContext):
        if self.fail:
            raise RenderError("stub render failed", code="render_failed", stage="render")
        assert context.project_dir is not None
        project = context.project_dir
        video = project / "build" / "media" / "course.mp4"
        video.parent.mkdir(parents=True, exist_ok=True)
        video.write_bytes(b"stub-video")
        qa = project / "internal" / "qa"
        qa.mkdir(parents=True, exist_ok=True)
        manifest = FrameManifest(
            build_id=BUILD_ID,
            asset_id=spec.visual_id,
            fps_num=30,
            fps_den=1,
            width=320,
            height=180,
            total_frames=1,
            scenes=[SceneFrameSpan(scene_id="scene-001", start_frame=0, end_frame=1)],
            frames=[
                FrameEntry(
                    index=0,
                    path="frames/000000.png",
                    sha256="a" * 64,
                    width=320,
                    height=180,
                )
            ],
        )
        manifest_path = qa / "frame_manifest.json"
        manifest_path.write_text(manifest.model_dump_json(), encoding="utf-8")
        report_path = qa / "encode_report.json"
        report_path.write_text(
            json.dumps({"video_sha256": sha256_file(video), "frames": 1}), encoding="utf-8"
        )
        return RenderResult(
            status="completed",
            build_id=BUILD_ID,
            artifacts=(video, manifest_path, report_path),
        )

    def validate(self, spec, html, context=None):
        return []


@pytest.fixture(autouse=True)
def skip_video_probe(monkeypatch):
    """The stub video is not a real MP4; the real check runs in CI."""

    import content_studio.visuals as visuals

    monkeypatch.setattr(visuals, "verify_video_against_manifest", lambda video, manifest: [])


def _registry(renderer: Renderer | None = None) -> RendererRegistry:
    registry = RendererRegistry()
    registry.register(renderer or _StubAnimationRenderer())
    return registry


def test_build_renders_animation_and_records_assets(tmp_path):
    project = _project(tmp_path)
    output = project / "build" / "slides" / "index.html"

    build_public_html(
        _content(),
        template_dir(),
        output,
        project_dir=project,
        registry=_registry(),
    )

    html = output.read_text(encoding="utf-8")
    assert "<video controls" in html
    assert 'src="../media/course.mp4"' in html
    assert "课程动画" in html
    assert not (project / "build" / BUILD_MARKER).exists()

    assets = json.loads(
        (project / "internal" / "qa" / "visual_assets.json").read_text(encoding="utf-8")
    )
    animation = next(item for item in assets if item["asset_type"] == "animation")
    assert animation["build_id"] == BUILD_ID
    assert animation["source"] == "content/scenes/course.json"
    assert animation["parameters"]["visual_type"] == "animation"
    assert set(animation["output_hashes"]) == {
        "build/media/course.mp4",
        "internal/qa/frame_manifest.json",
        "internal/qa/encode_report.json",
    }
    assert verify_build_assets(project) == []


def test_failed_render_leaves_marker_and_old_video(tmp_path):
    project = _project(tmp_path)
    video = project / "build" / "media" / "course.mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"old-video")

    with pytest.raises(RenderError) as caught:
        build_public_html(
            _content(),
            template_dir(),
            project / "build" / "slides" / "index.html",
            project_dir=project,
            registry=_registry(_StubAnimationRenderer(fail=True)),
        )

    assert caught.value.code == "render_failed"
    assert (project / "build" / BUILD_MARKER).is_file()
    assert video.read_bytes() == b"old-video"
    assert not (project / "internal" / "qa" / "visual_assets.json").exists()


def test_release_refuses_an_incomplete_build(tmp_path):
    project = _project(tmp_path)
    (project / "build" / BUILD_MARKER).write_text("{}", encoding="utf-8")
    config = ProjectConfig(project_id="p21-demo", title="P2.1")

    with pytest.raises(ValidationFailure, match="build is incomplete"):
        build_release(project, config, "v1")


def test_legacy_template_path_rejects_animation(tmp_path):
    project = _project(tmp_path)
    with pytest.raises(RenderError, match="animation blocks require the renderer registry"):
        build_public_html(
            _content(),
            template_dir(),
            project / "build" / "slides" / "index.html",
            project_dir=project,
            use_registry=False,
        )


def test_more_than_one_animation_is_rejected_before_rendering(tmp_path):
    project = _project(tmp_path)
    blocks = [
        AnimationBlock(scene_file="content/scenes/course.json", alt="一"),
        AnimationBlock(scene_file="content/scenes/course.json", alt="二"),
    ]
    with pytest.raises(RenderError, match="at most one animation") as caught:
        render_content_visuals(
            _content(blocks=blocks),
            project_dir=project,
            output_dir=project / "build" / "slides",
            registry=_registry(),
        )
    assert caught.value.code == "invalid_input"


def test_scene_file_must_stay_under_content_scenes():
    with pytest.raises(ValidationError, match="content/scenes"):
        AnimationBlock(scene_file="content/other.json", alt="x")
    with pytest.raises(ValidationError, match="relative"):
        AnimationBlock(scene_file="content/../content/scenes/course.json", alt="x")


def test_missing_scene_file_is_an_input_failure(tmp_path):
    project = _project(tmp_path)
    (project / "content" / "scenes" / "course.json").unlink()
    with pytest.raises(RenderError, match="scene file not found") as caught:
        render_content_visuals(
            _content(),
            project_dir=project,
            output_dir=project / "build" / "slides",
            registry=_registry(),
        )
    assert caught.value.code == "invalid_input"


def test_wrong_video_output_path_is_rejected(tmp_path):
    project = _project(tmp_path, payload=_scene_payload(output_path="build/other.mp4"))
    with pytest.raises(RenderError, match="build/media/course.mp4") as caught:
        render_content_visuals(
            _content(),
            project_dir=project,
            output_dir=project / "build" / "slides",
            registry=_registry(),
        )
    assert caught.value.code == "invalid_input"


def test_project_id_mismatch_is_rejected(tmp_path):
    project = _project(tmp_path, payload=_scene_payload(project_id="other-project"))
    with pytest.raises(RenderError, match="project_id") as caught:
        render_content_visuals(
            _content(),
            project_dir=project,
            output_dir=project / "build" / "slides",
            registry=_registry(),
        )
    assert caught.value.code == "invalid_input"


def test_written_specs_keep_the_scene_source(tmp_path):
    project = _project(tmp_path)
    rendered = render_content_visuals(
        _content(),
        project_dir=project,
        output_dir=project / "build" / "slides",
        registry=_registry(),
    )
    assert rendered[0].spec.visual_type == "animation"
    assert rendered[0].spec.data["source_path"] == "content/scenes/course.json"
    assert len(rendered[0].spec.data["source_sha256"]) == 64
    assert rendered[0].build_id == BUILD_ID


def test_non_animation_build_still_writes_the_page(tmp_path):
    project = _project(tmp_path)
    content = PublicContent(
        project_id="p21-demo",
        title="P2.1",
        slides=[
            PublicSlide(
                slide_id="slide-001",
                title="第一节",
                body=[ParagraphBlock(text="只有正文")],
            )
        ],
    )
    output = project / "build" / "slides" / "index.html"
    build_public_html(content, template_dir(), output, project_dir=project)
    assert output.is_file()
    assert "<video" not in output.read_text(encoding="utf-8")


def test_gate3_requires_animation_media_and_evidence(tmp_path):
    from content_studio.validation import _animation_media_checks

    project = _project(tmp_path)
    check = _animation_media_checks(project, _content())[0]
    assert check.status == "fail"

    for relative in (
        "build/media/course.mp4",
        "internal/qa/frame_manifest.json",
        "internal/qa/encode_report.json",
    ):
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    check = _animation_media_checks(project, _content())[0]
    assert check.status == "pass"


def test_gate3_reports_an_incomplete_build(tmp_path):
    from content_studio.validation import _build_committed_check

    project = _project(tmp_path)
    assert _build_committed_check(project).status == "pass"
    (project / "build" / BUILD_MARKER).write_text("{}", encoding="utf-8")
    assert _build_committed_check(project).status == "fail"
