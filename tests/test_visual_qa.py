"""P2.4-A: MC-04 automatic visual checks."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from content_studio import visual_qa
from content_studio.errors import RenderError
from content_studio.models import FrameEntry, FrameManifest, SceneFrameSpan
from content_studio.visual_qa import (
    FrameMetrics,
    VisualProfile,
    analyze_frames,
    gray_metrics,
    profile_for,
    sample_indices,
)


def _manifest(total: int = 30) -> FrameManifest:
    return FrameManifest(
        build_id="build-test-001",
        asset_id="course-v1",
        fps_num=30,
        fps_den=1,
        width=320,
        height=180,
        total_frames=total,
        scenes=[SceneFrameSpan(scene_id="scene-001", start_frame=0, end_frame=total)],
        frames=[
            FrameEntry(
                index=index,
                path=f"frames/project/{index:06d}.png",
                sha256="a" * 64,
                width=320,
                height=180,
            )
            for index in range(total)
        ],
    )


def _solid(value: int = 10, size: int = 16) -> bytes:
    return bytes([value] * (size * size))


def _content(size: int = 16) -> bytes:
    pixels = bytearray([10] * (size * size))
    for row in range(size):
        for column in range(4, 8):
            pixels[row * size + column] = 255
    return bytes(pixels)


def test_solid_frame_is_blank():
    background, foreground, edges = gray_metrics(_solid(), 16, 16)
    assert background == 1.0
    assert foreground == 0.0
    assert edges == 0.0


def test_frame_with_structure_is_not_blank():
    background, foreground, edges = gray_metrics(_content(), 16, 16)
    assert background > 0.5
    assert foreground > 0.05
    assert edges > 0.01


def test_short_buffers_are_rejected():
    with pytest.raises(ValueError):
        gray_metrics(b"\x00" * 10, 16, 16)


def test_sampling_skips_fades_and_caps_the_count():
    indices = sample_indices(300, 30, 1)
    assert len(indices) == 9
    assert indices[0] >= 30
    assert indices[-1] <= 284
    assert indices == sorted(set(indices))


def test_sampling_falls_back_to_the_middle_for_short_builds():
    assert sample_indices(30, 30, 1) == [15]
    assert sample_indices(0, 30, 1) == []
    assert sample_indices(1, 30, 1) == [0]


def test_unknown_template_gets_the_default_profile():
    profile = profile_for("unknown")
    assert profile.template == "unknown"
    assert profile.allow_blank is False


def test_analyze_frames_fails_on_blank_samples():
    report = analyze_frames(
        _manifest(),
        build_root=Path("/build"),
        template="title",
        ffmpeg_bin="ffmpeg",
        decode=lambda path: (_solid(), 16, 16),
    )
    assert report.status == "fail"
    assert (
        report.blank_frames == report.sampled[0].__dict__.get("index", None) or report.blank_frames
    )
    assert len(report.blank_frames) == len(sample_indices(30, 30, 1))


def test_analyze_frames_passes_with_content():
    report = analyze_frames(
        _manifest(),
        build_root=Path("/build"),
        template="flow",
        ffmpeg_bin="ffmpeg",
        decode=lambda path: (_content(), 16, 16),
    )
    assert report.status == "pass"
    assert report.blank_frames == []
    payload = report.as_dict()
    assert payload["schema_version"] == "1.0"
    assert payload["template"] == "flow"
    assert payload["sampled_frames"] == [15]
    assert payload["thresholds"]["min_foreground"] == report.profile.min_foreground


def test_allow_blank_profile_skips_the_verdict(monkeypatch):
    monkeypatch.setitem(visual_qa.VISUAL_PROFILES, "card", VisualProfile("card", allow_blank=True))
    report = analyze_frames(
        _manifest(),
        build_root=Path("/build"),
        template="card",
        ffmpeg_bin="ffmpeg",
        decode=lambda path: (_solid(), 16, 16),
    )
    assert report.status == "pass"
    assert report.blank_frames == []
    assert all(not metrics.blank for metrics in report.sampled)


def test_decode_failure_is_qa_failed(monkeypatch):
    def fail(*args, **kwargs):
        return subprocess.CompletedProcess([], returncode=1, stdout=b"", stderr=b"boom")

    monkeypatch.setattr(visual_qa.subprocess, "run", fail)
    with pytest.raises(RenderError) as caught:
        analyze_frames(
            _manifest(), build_root=Path("/build"), template="title", ffmpeg_bin="ffmpeg"
        )
    assert caught.value.code == "qa_failed"


def test_frame_metrics_serialise_with_rounding():
    metrics = FrameMetrics(
        index=3, background_share=0.1234567, foreground_ratio=0.01, edge_ratio=0.002, blank=False
    )
    assert metrics.as_dict()["background_share"] == 0.123457
