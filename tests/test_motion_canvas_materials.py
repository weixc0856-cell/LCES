"""P3-A: real renders of the frozen representative materials.

The contract/hash checks in ``test_motion_materials.py`` run everywhere. This
module renders the same materials through the real adapter and only runs on a
Linux host with the pinned toolchain, gated by ``LCES_MC_MATERIALS=1`` so a
normal PR does not pay for seven renders.

It records a per-material report (frames, resolution, bytes, visual metrics,
elapsed) to ``LCES_MATERIALS_OUT``. The report is evidence; a failure names
the material and the stage.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from content_studio import motion_canvas as mc
from content_studio.models import FrameManifest, VisualSpec
from content_studio.paths import ensure_project_layout
from content_studio.renderers import RenderContext
from content_studio.video_qa import verify_video_against_manifest

pytestmark = pytest.mark.motion

MATERIALS = Path(__file__).parent / "fixtures" / "motion"

requires_render = pytest.mark.skipif(
    os.environ.get("LCES_MC_MATERIALS") != "1",
    reason="set LCES_MC_MATERIALS=1 to render the representative materials",
)


def _materials() -> list[dict]:
    payload = json.loads((MATERIALS / "manifest.json").read_text(encoding="utf-8"))
    return payload["materials"]


def _payload(material: dict) -> dict:
    return json.loads((MATERIALS / material["file"]).read_text(encoding="utf-8"))


def _spec(material: dict) -> VisualSpec:
    return VisualSpec(
        visual_id=material["id"],
        visual_type="animation",
        renderer=mc.MotionCanvasRenderer.name,
        data=_payload(material),
    )


@pytest.mark.parametrize("material", _materials(), ids=lambda item: item["id"])
def test_material_builds_a_valid_spec(material):
    """Fast contract check: the adapter accepts every material before rendering."""

    problems = mc.MotionCanvasRenderer().validate_input(_spec(material))
    assert problems == [], material["id"]


@requires_render
def test_representative_materials_render(tmp_path):
    report: list[dict] = []
    for material in _materials():
        project = ensure_project_layout(tmp_path / material["id"])
        started = time.monotonic()
        renderer = mc.MotionCanvasRenderer(max_render_ms=300_000)
        result = renderer.render(
            _spec(material),
            RenderContext(project_dir=project, output_dir=project / "build", publish=True),
        )
        elapsed = time.monotonic() - started
        try:
            assert result.status == "completed", material["id"]
            build = project / "build" / "motion" / result.build_id
            manifest = FrameManifest.model_validate_json(
                (build / "frame_manifest.json").read_text(encoding="utf-8")
            )
            video = project / "build" / "media" / "course.mp4"
            assert manifest.total_frames == material["frames"], material["id"]
            assert (manifest.width, manifest.height) == (
                material["width"],
                material["height"],
            ), material["id"]
            assert (manifest.fps_num, manifest.fps_den) == (
                material["fps_num"],
                material["fps_den"],
            ), material["id"]
            assert verify_video_against_manifest(video, manifest) == [], material["id"]
            visual = json.loads((build / "visual_qa.json").read_text(encoding="utf-8"))
            assert visual["status"] == "pass", material["id"]
        except AssertionError:
            raise
        except Exception as exc:  # name the material and the stage
            raise AssertionError(
                f"material {material['id']} failed after {elapsed:.1f}s: "
                f"{exc.__class__.__name__}: {exc}"
            ) from exc
        report.append(
            {
                "id": material["id"],
                "template": material["template"],
                "frames": manifest.total_frames,
                "width": manifest.width,
                "height": manifest.height,
                "video_bytes": video.stat().st_size,
                "elapsed_s": round(elapsed, 2),
                "visual": visual["frames"],
            }
        )
    output = Path(os.environ.get("LCES_MATERIALS_OUT", str(tmp_path / "materials.json")))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps({"materials": report}, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    assert len(report) == len(_materials())
    print(json.dumps({"materials": report}, indent=2, ensure_ascii=False))
