"""MC-01 timeline allocation: integer milliseconds to frame boundaries.

All arithmetic is integer. The frame rate stays a rational (``fps_num`` /
``fps_den``) and durations stay integer milliseconds; converting to float
seconds before rounding drifts at .5 boundaries. Each cumulative boundary is
rounded once, and a scene's frame count is the difference between adjacent
boundaries -- never a per-scene rounded value added up.

    B_i = (2 * C_i * fps_num + 1000 * fps_den) // (2000 * fps_den)

where ``C_i`` is the cumulative duration in milliseconds. The half-way case
rounds up, matching the frozen specification in ``docs/design/MOTION_CANVAS.md``
section 5.3.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction

from content_studio.errors import RenderError
from content_studio.models import SceneContract

MAX_TOTAL_FRAMES = 1_000_000
MAX_DURATION_MS = 3_600_000
MAX_FPS_TERM = 1_000_000


@dataclass(frozen=True)
class TimelinePlan:
    """Frame boundaries for one video build.

    ``bounds[i]`` is the exclusive end frame of scene ``i``; scene ``i`` owns
    frames ``[bounds[i-1], bounds[i])`` with ``bounds[-1] == 0``.
    """

    fps_num: int
    fps_den: int
    durations_ms: tuple[int, ...]
    bounds: tuple[int, ...]
    scene_frames: tuple[int, ...]
    total_frames: int

    @property
    def expected_seconds(self) -> Fraction:
        """Exact duration implied by the frame count."""

        return Fraction(self.total_frames * self.fps_den, self.fps_num)

    @property
    def contract_seconds(self) -> Fraction:
        return Fraction(sum(self.durations_ms), 1000)

    @property
    def tolerance_seconds(self) -> Fraction:
        """One frame, in seconds."""

        return Fraction(self.fps_den, self.fps_num)

    @property
    def within_tolerance(self) -> bool:
        return abs(self.expected_seconds - self.contract_seconds) <= self.tolerance_seconds

    def range_seconds(self) -> float:
        """Motion Canvas ``shared.range`` end value, in seconds.

        The editor exports an inclusive frame range, so the end is
        ``(total_frames - 1) / fps``; using the full scene range produced two
        extra frames in the P0 experiment.
        """

        return float(Fraction((self.total_frames - 1) * self.fps_den, self.fps_num))

    def scene_bounds(self, scene_ids: Sequence[str]) -> list[tuple[str, int, int]]:
        if len(scene_ids) != len(self.scene_frames):
            raise ValueError("scene id count does not match the timeline plan")
        spans: list[tuple[str, int, int]] = []
        start = 0
        for scene_id, count in zip(scene_ids, self.scene_frames, strict=True):
            spans.append((scene_id, start, start + count))
            start += count
        return spans


def frame_boundary(cumulative_ms: int, fps_num: int, fps_den: int) -> int:
    """Round ``cumulative_ms * fps`` to the nearest frame, half up."""

    return (2 * cumulative_ms * fps_num + 1000 * fps_den) // (2000 * fps_den)


def plan_timeline(durations_ms: Sequence[int], *, fps_num: int, fps_den: int) -> TimelinePlan:
    """Allocate frames to scenes; raise ``invalid_input`` on any violation."""

    _require_positive_int(fps_num, "fps_num")
    _require_positive_int(fps_den, "fps_den")
    if fps_num > MAX_FPS_TERM or fps_den > MAX_FPS_TERM:
        raise _invalid("frame rate terms are out of range")
    if not durations_ms:
        raise _invalid("the scene set is empty")

    cumulative = 0
    bounds: list[int] = []
    durations: list[int] = []
    for index, duration in enumerate(durations_ms, start=1):
        if not isinstance(duration, int) or isinstance(duration, bool):
            raise _invalid(f"scene {index}: duration_ms must be an integer")
        if duration <= 0:
            raise _invalid(f"scene {index}: duration_ms must be positive")
        if duration > MAX_DURATION_MS:
            raise _invalid(f"scene {index}: duration_ms exceeds {MAX_DURATION_MS}")
        cumulative += duration
        if cumulative > MAX_DURATION_MS:
            raise _invalid(f"total duration exceeds {MAX_DURATION_MS} ms")
        bounds.append(frame_boundary(cumulative, fps_num, fps_den))
        durations.append(duration)

    scene_frames: list[int] = []
    previous = 0
    for index, bound in enumerate(bounds, start=1):
        count = bound - previous
        if count < 1:
            raise _invalid(
                f"scene {index}: {durations[index - 1]} ms allocates 0 frames "
                f"at {fps_num}/{fps_den} fps; no frame is silently added"
            )
        scene_frames.append(count)
        previous = bound

    total_frames = bounds[-1]
    if total_frames > MAX_TOTAL_FRAMES:
        raise _invalid(f"total frames exceed {MAX_TOTAL_FRAMES}")

    return TimelinePlan(
        fps_num=fps_num,
        fps_den=fps_den,
        durations_ms=tuple(durations),
        bounds=tuple(bounds),
        scene_frames=tuple(scene_frames),
        total_frames=total_frames,
    )


def plan_from_scenes(
    scenes: Sequence[SceneContract], *, fps_num: int, fps_den: int
) -> TimelinePlan:
    """Convenience wrapper for scene contracts."""

    return plan_timeline(
        [scene.duration_ms for scene in scenes],
        fps_num=fps_num,
        fps_den=fps_den,
    )


def _require_positive_int(value: object, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise _invalid(f"{name} must be a positive integer")


def _invalid(message: str) -> RenderError:
    return RenderError(message, code="invalid_input", stage="input")
