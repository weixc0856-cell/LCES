"""P1.2: FrameManifest evidence must match the files it describes."""

from __future__ import annotations

import shutil
import zlib
from pathlib import Path

import pytest
from pydantic import ValidationError

from content_studio.errors import RenderError
from content_studio.frame_manifest import (
    build_frame_manifest,
    verify_frame_manifest,
    write_frame_manifest,
)
from content_studio.models import FrameEntry, FrameManifest, SceneFrameSpan
from content_studio.timeline import plan_timeline

WIDTH, HEIGHT = 320, 180
SCENES = ["scene-001", "scene-002"]


def _chunk(kind: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return len(payload).to_bytes(4, "big") + kind + payload + crc.to_bytes(4, "big")


def _png(width: int = WIDTH, height: int = HEIGHT) -> bytes:
    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    return bytes.fromhex("89504e470d0a1a0a") + _chunk(b"IHDR", header) + _chunk(b"IEND", b"")


def _plan(total_scenes: int = 2):
    durations = [1000, 500][:total_scenes]
    return plan_timeline(durations, fps_num=30, fps_den=1)


def _build(tmp_path: Path, plan=None):
    plan = plan or _plan()
    build_root = tmp_path / "build"
    frames_dir = build_root / "frames" / "project"
    frames_dir.mkdir(parents=True)
    for index in range(plan.total_frames):
        (frames_dir / f"{index:06d}.png").write_bytes(_png())
    manifest = build_frame_manifest(
        build_id="build-test-001",
        asset_id="course-v1",
        plan=plan,
        scene_ids=SCENES,
        frames_dir=frames_dir,
        build_root=build_root,
        width=WIDTH,
        height=HEIGHT,
    )
    return build_root, frames_dir, plan, manifest


def _verify(manifest, build_root, frames_dir, plan, *, decode=False):
    return verify_frame_manifest(
        manifest,
        build_root=build_root,
        frames_dir=frames_dir,
        plan=plan,
        decode_frames=decode,
    )


def test_builds_and_verifies_a_complete_manifest(tmp_path):
    build_root, frames_dir, plan, manifest = _build(tmp_path)
    path = write_frame_manifest(manifest, build_root / "frame_manifest.json")
    assert path.is_file()
    assert manifest.total_frames == 45
    assert manifest.fps_num == 30
    assert [(span.scene_id, span.start_frame, span.end_frame) for span in manifest.scenes] == [
        ("scene-001", 0, 30),
        ("scene-002", 30, 45),
    ]
    assert manifest.frames[0].path == "frames/project/000000.png"
    assert manifest.frames[-1].index == 44
    assert _verify(manifest, build_root, frames_dir, plan) == []


def test_tampered_frame_is_detected_by_hash(tmp_path):
    build_root, frames_dir, plan, manifest = _build(tmp_path)
    target = frames_dir / "000007.png"
    target.write_bytes(_png(width=321, height=180))
    problems = _verify(manifest, build_root, frames_dir, plan)
    assert any("frame 7: sha256 does not match" in problem for problem in problems)
    assert any("does not match 320x180" in problem for problem in problems)


def test_truncated_frame_fails_at_build(tmp_path):
    plan = _plan(1)
    build_root = tmp_path / "build"
    frames_dir = build_root / "frames" / "project"
    frames_dir.mkdir(parents=True)
    for index in range(plan.total_frames):
        data = _png()
        (frames_dir / f"{index:06d}.png").write_bytes(data[:20] if index == 3 else data)
    with pytest.raises(RenderError) as caught:
        build_frame_manifest(
            build_id="build-test-001",
            asset_id="course-v1",
            plan=plan,
            scene_ids=["scene-001"],
            frames_dir=frames_dir,
            build_root=build_root,
            width=WIDTH,
            height=HEIGHT,
        )
    assert caught.value.code == "output_corrupt"
    assert "000003.png" in str(caught.value)


def test_missing_frame_fails_at_build(tmp_path):
    plan = _plan(1)
    build_root = tmp_path / "build"
    frames_dir = build_root / "frames" / "project"
    frames_dir.mkdir(parents=True)
    for index in range(plan.total_frames - 1):
        (frames_dir / f"{index:06d}.png").write_bytes(_png())
    with pytest.raises(RenderError) as caught:
        build_frame_manifest(
            build_id="build-test-001",
            asset_id="course-v1",
            plan=plan,
            scene_ids=["scene-001"],
            frames_dir=frames_dir,
            build_root=build_root,
            width=WIDTH,
            height=HEIGHT,
        )
    assert caught.value.code == "frame_mismatch"


def test_index_gap_fails_at_build(tmp_path):
    plan = _plan(1)
    build_root = tmp_path / "build"
    frames_dir = build_root / "frames" / "project"
    frames_dir.mkdir(parents=True)
    for index in range(plan.total_frames):
        name = 99 if index == plan.total_frames - 1 else index
        (frames_dir / f"{name:06d}.png").write_bytes(_png())
    with pytest.raises(RenderError) as caught:
        build_frame_manifest(
            build_id="build-test-001",
            asset_id="course-v1",
            plan=plan,
            scene_ids=["scene-001"],
            frames_dir=frames_dir,
            build_root=build_root,
            width=WIDTH,
            height=HEIGHT,
        )
    assert caught.value.code == "frame_mismatch"
    assert "not contiguous" in str(caught.value)


def test_extra_frame_is_detected_by_verify(tmp_path):
    build_root, frames_dir, plan, manifest = _build(tmp_path)
    shutil.copy2(frames_dir / "000044.png", frames_dir / "000045.png")
    problems = _verify(manifest, build_root, frames_dir, plan)
    assert any("absent from the manifest" in problem for problem in problems)


def test_scene_spans_must_match_the_plan(tmp_path):
    build_root, frames_dir, plan, manifest = _build(tmp_path)
    other = plan_timeline([500, 1000], fps_num=30, fps_den=1)
    problems = _verify(manifest, build_root, frames_dir, other)
    assert any("covers" in problem and "expected" in problem for problem in problems)


def test_manifest_model_rejects_path_escape(tmp_path):
    with pytest.raises(ValidationError, match="workspace|relative"):
        FrameEntry(index=0, path="../escape.png", sha256="a" * 64, width=1, height=1)


def test_manifest_model_rejects_bad_hash_and_span_gap():
    with pytest.raises(ValidationError):
        FrameEntry(index=0, path="frames/000000.png", sha256="nope", width=1, height=1)
    with pytest.raises(ValidationError, match="expected 10"):
        FrameManifest(
            build_id="build-test-001",
            asset_id="course-v1",
            fps_num=30,
            width=10,
            height=10,
            total_frames=20,
            scenes=[
                SceneFrameSpan(scene_id="scene-001", start_frame=0, end_frame=10),
                SceneFrameSpan(scene_id="scene-002", start_frame=11, end_frame=20),
            ],
            frames=[
                FrameEntry(
                    index=index,
                    path=f"frames/{index:06d}.png",
                    sha256="a" * 64,
                    width=10,
                    height=10,
                )
                for index in range(20)
            ],
        )


def test_decode_rejects_structurally_valid_but_undecodable_pngs(tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg is required for the decode check")
    build_root, frames_dir, plan, manifest = _build(tmp_path)
    # The synthetic frames carry IHDR/IEND but no image data, so ffmpeg must
    # reject them even though every hash and structure check passes.
    problems = _verify(manifest, build_root, frames_dir, plan, decode=True)
    assert any("ffmpeg" in problem for problem in problems)
