import pytest
from pydantic import ValidationError

from content_studio.models import SceneContract, SceneSet, VideoContract, VisualAsset


def _asset(**overrides) -> VisualAsset:
    values = {
        "asset_id": "chart-001",
        "asset_type": "chart",
        "source": "content/charts/bleu.svg",
    }
    values.update(overrides)
    return VisualAsset(**values)


def test_visual_asset_accepts_workspace_relative_paths():
    asset = _asset(
        output_paths=["build/charts/bleu.svg"],
        dependencies=["content/charts/bleu.svg"],
        output_hashes={"build/charts/bleu.svg": "a" * 64},
        renderer="vega_lite.chart",
        renderer_version="1.0.0",
    )
    assert asset.status == "pending"
    assert asset.output_hashes["build/charts/bleu.svg"] == "a" * 64


@pytest.mark.parametrize(
    "path",
    ["C:/secret/x.svg", "/etc/passwd", "../outside.svg", "\\\\server\\share\\x.svg"],
)
def test_visual_asset_rejects_paths_outside_the_workspace(path):
    with pytest.raises(ValidationError, match="relative|workspace"):
        _asset(source=path)


def test_visual_asset_rejects_bad_hashes():
    with pytest.raises(ValidationError, match="sha256"):
        _asset(output_hashes={"x.svg": "not-a-hash"})
    with pytest.raises(ValidationError):
        _asset(source_hash="1234")


def test_visual_asset_requires_supported_schema_major():
    with pytest.raises(ValidationError, match="unsupported asset schema_version"):
        _asset(schema_version="2.0")


def test_scene_contract_uses_integer_milliseconds():
    scene = SceneContract(
        scene_id="scene-001",
        scene_type="title",
        duration_ms=2500,
        renderer="motion-canvas",
        fallback_policy="fail",
    )
    assert scene.duration_ms == 2500
    assert scene.transition_in == "cut"

    with pytest.raises(ValidationError):
        SceneContract(scene_id="scene-001", scene_type="title", duration_ms=0)
    with pytest.raises(ValidationError):
        SceneContract(
            scene_id="scene-001",
            scene_type="title",
            duration_ms=100,
            fallback_policy="guess",
        )


def test_video_contract_keeps_frame_rate_rational():
    video = VideoContract(
        project_id="demo",
        video_id="course-v1",
        content_version="v1",
        width=1920,
        height=1080,
        fps_num=30000,
        fps_den=1001,
        scene_ids=["scene-001"],
        output_path="build/media/course.mp4",
    )
    assert video.fps == pytest.approx(29.97, rel=1e-3)
    assert video.audio_channels == 2
    assert video.subtitle_format == "srt"


def test_video_contract_rejects_absolute_output():
    with pytest.raises(ValidationError, match="relative|workspace"):
        VideoContract(
            project_id="demo",
            video_id="course-v1",
            content_version="v1",
            width=1920,
            height=1080,
            fps_num=30,
            scene_ids=["scene-001"],
            output_path="D:/media/course.mp4",
        )


def test_video_contract_requires_scenes_and_valid_hash():
    with pytest.raises(ValidationError):
        VideoContract(
            project_id="demo",
            video_id="course-v1",
            content_version="v1",
            width=1920,
            height=1080,
            fps_num=30,
            scene_ids=[],
            output_path="build/media/course.mp4",
        )
    with pytest.raises(ValidationError):
        VideoContract(
            project_id="demo",
            video_id="course-v1",
            content_version="v1",
            width=1920,
            height=1080,
            fps_num=30,
            scene_ids=["scene-001"],
            output_path="build/media/course.mp4",
            build_hash="xyz",
        )


def test_scene_contract_carries_template_data():
    scene = SceneContract(
        scene_id="scene-001",
        scene_type="title",
        duration_ms=2500,
        data={"title": "Hello", "subtitle": "world"},
    )
    assert scene.data["title"] == "Hello"
    # Unknown keys stay rejected at the contract level.
    with pytest.raises(ValidationError):
        SceneContract(scene_id="scene-001", scene_type="title", duration_ms=2500, timing={})


def test_scene_set_keeps_order_and_rejects_duplicates():
    scenes = SceneSet(
        scenes=[
            SceneContract(scene_id="scene-001", scene_type="title", duration_ms=1000),
            SceneContract(scene_id="scene-002", scene_type="title", duration_ms=1000),
        ]
    )
    assert scenes.scene_ids == ["scene-001", "scene-002"]

    with pytest.raises(ValidationError, match="duplicate scene_id"):
        SceneSet(
            scenes=[
                SceneContract(scene_id="scene-001", scene_type="title", duration_ms=1000),
                SceneContract(scene_id="scene-001", scene_type="title", duration_ms=1000),
            ]
        )


def test_scene_set_needs_at_least_one_scene():
    with pytest.raises(ValidationError):
        SceneSet(scenes=[])
