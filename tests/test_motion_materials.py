"""P3-A: representative materials are valid and frozen.

The fixtures are the inputs for the production-level render tests. Their
hashes live in ``manifest.json`` so a change is a deliberate act: edit the
scene, update the manifest, and review the diff. Nothing here renders.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from content_studio.models import SceneSet, VideoContract
from content_studio.motion_templates import data_problems
from content_studio.utils import sha256_file

MATERIALS = Path(__file__).parent / "fixtures" / "motion"
TEMPLATES = {"title", "flow", "compare"}


def _manifest() -> dict:
    return json.loads((MATERIALS / "manifest.json").read_text(encoding="utf-8"))


def _materials() -> list[dict]:
    return _manifest()["materials"]


def test_the_set_covers_every_template_and_the_planned_tags():
    materials = _materials()
    assert {item["template"] for item in materials} == TEMPLATES
    tags = {tag for item in materials for tag in item["tags"]}
    assert {"cjk", "english", "boundary", "long-text", "1080p"} <= tags
    assert len({item["id"] for item in materials}) == len(materials)


def test_manifest_hashes_match_the_files():
    for item in _materials():
        path = MATERIALS / item["file"]
        assert path.is_file(), item["file"]
        assert sha256_file(path) == item["sha256"], f"{item['file']} changed without the manifest"


def test_every_material_validates_against_the_current_contract():
    for item in _materials():
        payload = json.loads((MATERIALS / item["file"]).read_text(encoding="utf-8"))
        scenes = SceneSet.model_validate(payload["scene_set"])
        video = VideoContract.model_validate(payload["video"])
        assert video.scene_ids == scenes.scene_ids
        assert video.output_path == "build/media/course.mp4"
        assert video.width == item["width"] and video.height == item["height"]
        assert video.fps_num == item["fps_num"] and video.fps_den == item["fps_den"]
        scene = scenes.scenes[0]
        assert scene.scene_type == item["template"]
        assert scene.duration_ms == item["duration_ms"]
        assert data_problems(scene.scene_type, scene.data, video.width, video.height) == []


def test_expected_frame_counts_derive_from_duration_and_fps():
    for item in _materials():
        expected = item["duration_ms"] * item["fps_num"] // (1000 * item["fps_den"])
        assert item["frames"] == expected, item["id"]


@pytest.mark.parametrize("material_id", ["title-boundary-max", "flow-zh-6nodes", "compare-zh-long"])
def test_boundary_materials_are_present(material_id):
    assert any(item["id"] == material_id for item in _materials())
