"""MC-01: integer timeline allocation, no float drift, no silent frame padding."""

from __future__ import annotations

import random
from fractions import Fraction

import pytest

from content_studio.errors import RenderError
from content_studio.models import SceneContract
from content_studio.timeline import frame_boundary, plan_from_scenes, plan_timeline


def test_counter_example_allocates_two_one_two():
    plan = plan_timeline([50, 50, 50], fps_num=30, fps_den=1)
    assert plan.scene_frames == (2, 1, 2)
    assert plan.total_frames == 5
    assert plan.bounds == (2, 3, 5)
    # 5 frames at 30 fps vs 150 ms: half a frame apart, inside the one-frame
    # tolerance. (The specification calls this "exactly one frame"; at 30 fps
    # the delta is 16.67 ms, which is half a frame -- the pass/fail conclusion
    # is unchanged, the boundary description is not.)
    assert abs(plan.expected_seconds - plan.contract_seconds) == plan.tolerance_seconds / 2
    assert plan.within_tolerance


def test_per_scene_rounding_would_not_match():
    # Guard against a "round each scene then add" regression: that yields 6.
    plan = plan_timeline([50, 50, 50], fps_num=30, fps_den=1)
    naive = sum(round(Fraction(d, 1000) * 30) for d in (50, 50, 50))
    assert naive == 6
    assert plan.total_frames == 5


def test_frame_boundary_rounds_half_up():
    assert frame_boundary(50, 30, 1) == 2  # 1.5 -> 2
    assert frame_boundary(30_000, 30, 1) == 900
    assert frame_boundary(10, 30, 1) == 0  # 0.3 -> 0, caught as a zero-frame scene


def test_ntsc_rate_keeps_exact_arithmetic():
    plan = plan_timeline([1000], fps_num=30000, fps_den=1001)
    assert plan.total_frames == 30
    assert plan.expected_seconds == Fraction(30 * 1001, 30000)
    assert plan.within_tolerance
    assert plan.range_seconds() == pytest.approx(29 / (30000 / 1001))


def test_range_end_is_one_frame_before_the_duration():
    plan = plan_timeline([10_000], fps_num=30, fps_den=1)
    assert plan.total_frames == 300
    # P0 measured 302 frames for the full 10.03 s range; the editor range must
    # end at frame 299 so the export is exactly 300 frames.
    assert plan.range_seconds() == pytest.approx(299 / 30)


@pytest.mark.parametrize("duration", [10, 1])
def test_zero_frame_scene_is_invalid_input(duration):
    with pytest.raises(RenderError) as caught:
        plan_timeline([duration], fps_num=30, fps_den=1)
    assert caught.value.code == "invalid_input"
    assert "0 frames" in str(caught.value)


@pytest.mark.parametrize("duration", [0, -5])
def test_non_positive_duration_is_invalid_input(duration):
    with pytest.raises(RenderError) as caught:
        plan_timeline([500, duration], fps_num=30, fps_den=1)
    assert caught.value.code == "invalid_input"


def test_empty_scene_set_is_invalid_input():
    with pytest.raises(RenderError):
        plan_timeline([], fps_num=30, fps_den=1)


@pytest.mark.parametrize("fps_num,fps_den", [(0, 1), (-30, 1), (30, 0), (30, -1), (1_000_001, 1)])
def test_invalid_frame_rate_is_rejected(fps_num, fps_den):
    with pytest.raises(RenderError):
        plan_timeline([1000], fps_num=fps_num, fps_den=fps_den)


def test_total_frame_cap_is_enforced():
    with pytest.raises(RenderError, match="total frames"):
        plan_timeline([3_600_000], fps_num=300, fps_den=1)


def test_duration_cap_is_enforced():
    with pytest.raises(RenderError, match="duration"):
        plan_timeline([3_600_001], fps_num=30, fps_den=1)


def test_sum_of_scene_frames_equals_total_frames_for_random_sets():
    rng = random.Random(20261022)
    for _ in range(200):
        durations = [rng.randint(40, 4000) for _ in range(rng.randint(1, 8))]
        fps_num = rng.choice([24, 25, 30, 50, 60, 30000])
        fps_den = 1001 if fps_num == 30000 else 1
        try:
            plan = plan_timeline(durations, fps_num=fps_num, fps_den=fps_den)
        except RenderError:
            # A sub-frame scene is a rejection, never a silent repair.
            continue
        assert sum(plan.scene_frames) == plan.total_frames
        assert all(count >= 1 for count in plan.scene_frames)
        assert plan.bounds[-1] == plan.total_frames
        assert plan.within_tolerance


def test_plan_from_scene_contracts():
    scenes = [
        SceneContract(scene_id="scene-001", scene_type="title", duration_ms=2500),
        SceneContract(scene_id="scene-002", scene_type="title", duration_ms=2500),
    ]
    plan = plan_from_scenes(scenes, fps_num=30, fps_den=1)
    assert plan.total_frames == 150
    assert plan.scene_bounds(["scene-001", "scene-002"]) == [
        ("scene-001", 0, 75),
        ("scene-002", 75, 150),
    ]
