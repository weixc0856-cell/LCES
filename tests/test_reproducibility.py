"""P2.4-C: reproducibility comparison helpers."""

from __future__ import annotations

from content_studio.models import FrameEntry, FrameManifest, SceneFrameSpan
from content_studio.reproducibility import build_report, compare_manifests, compare_visual


def _manifest(*hashes: str, build_id: str = "build-a") -> FrameManifest:
    return FrameManifest(
        build_id=build_id,
        asset_id="course-v1",
        fps_num=30,
        fps_den=1,
        width=320,
        height=180,
        total_frames=len(hashes),
        scenes=[SceneFrameSpan(scene_id="scene-001", start_frame=0, end_frame=len(hashes))],
        frames=[
            FrameEntry(
                index=index,
                path=f"frames/project/{index:06d}.png",
                sha256=(value * 64)[:64],
                width=320,
                height=180,
            )
            for index, value in enumerate(hashes)
        ],
    )


def _visual(foreground: float, edges: float, status: str = "pass") -> dict:
    return {
        "status": status,
        "frames": [
            {"index": 5, "foreground_ratio": foreground, "edge_ratio": edges, "blank": False}
        ],
    }


def test_identical_frames_have_a_rate_of_one():
    comparison = compare_manifests(_manifest("a", "b"), _manifest("a", "b", build_id="build-b"))
    assert comparison.total == 2
    assert comparison.identical == 2
    assert comparison.rate == 1.0
    assert comparison.as_dict()["differing_frames"] == []


def test_differing_frames_are_listed_by_index():
    comparison = compare_manifests(_manifest("a", "b", "c"), _manifest("a", "d", "c"))
    assert comparison.identical == 2
    assert comparison.differing == [1]
    assert comparison.as_dict()["byte_identical_rate"] == 0.666667


def test_empty_comparison_does_not_divide_by_zero():
    from content_studio.reproducibility import FrameComparison

    assert FrameComparison(total=0, identical=0).rate == 0.0


def test_visual_deltas_are_reported():
    comparison = compare_visual(_visual(0.10, 0.05), _visual(0.13, 0.05))
    assert comparison["sampled_frames"] == [5]
    assert comparison["max_foreground_delta"] == 0.03
    assert comparison["max_edge_delta"] == 0.0
    assert comparison["status_match"] is True


def test_status_mismatch_is_recorded():
    comparison = compare_visual(_visual(0.1, 0.05), _visual(0.1, 0.05, status="fail"))
    assert comparison["status_match"] is False


def test_report_carries_environment_and_scope():
    report = build_report(
        scene={"type": "title", "width": 320, "height": 180, "frames": 2},
        first=_manifest("a", "b"),
        second=_manifest("a", "b", build_id="build-b"),
        first_visual=_visual(0.1, 0.05),
        second_visual=_visual(0.1, 0.05),
    )
    assert report["builds"] == ["build-a", "build-b"]
    assert report["frames"]["byte_identical_rate"] == 1.0
    assert report["environment"]["node_version"]
    assert report["environment"]["package_lock_sha256"]
    assert "same environment" in report["scope"]
