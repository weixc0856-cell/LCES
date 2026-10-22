"""FrameManifest construction and independent verification (P1.2).

A manifest is an evidence document, not proof by itself: every path is
re-hashed, re-checked structurally, and decoded again after the manifest is
written. A PNG with a correct SHA-256 can still be unreadable, so both checks
must pass independently.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import zlib
from collections.abc import Sequence
from pathlib import Path

from pydantic import ValidationError

from content_studio.errors import RenderError
from content_studio.models import FrameEntry, FrameManifest, SceneFrameSpan
from content_studio.paths import symlink_components, symlinks_in_tree
from content_studio.timeline import TimelinePlan
from content_studio.utils import sha256_file, write_json

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
FRAME_NAME = re.compile(r"^\d{6}\.png$")
MAX_REPORTED_PROBLEMS = 5
DECODE_TIMEOUT_SECONDS = 180


def _frame_paths(frames_dir: Path) -> list[tuple[int, Path]]:
    entries: list[tuple[int, Path]] = []
    if not frames_dir.is_dir():
        return entries
    for path in frames_dir.rglob("*.png"):
        if FRAME_NAME.match(path.name):
            entries.append((int(path.stem), path))
    entries.sort(key=lambda item: item[0])
    return entries


def png_problems(path: Path, width: int, height: int) -> list[str]:
    """Structural PNG check: signature, chunk order, CRC, dimensions, IEND."""

    try:
        data = path.read_bytes()
    except OSError as exc:
        return [f"{path.name}: cannot be read ({exc.__class__.__name__})"]
    if not data.startswith(PNG_SIGNATURE):
        return [f"{path.name}: not a PNG"]
    offset = 8
    seen_header = False
    seen_end = False
    actual_width = actual_height = 0
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            return [f"{path.name}: truncated at {chunk_type.decode('latin1', 'replace')}"]
        expected_crc = int.from_bytes(data[end - 4 : end], "big")
        actual_crc = zlib.crc32(data[offset + 4 : end - 4]) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            return [f"{path.name}: CRC mismatch in {chunk_type.decode('latin1', 'replace')}"]
        if not seen_header and chunk_type != b"IHDR":
            return [f"{path.name}: does not start with IHDR"]
        if chunk_type == b"IHDR":
            seen_header = True
            actual_width = int.from_bytes(data[offset + 8 : offset + 12], "big")
            actual_height = int.from_bytes(data[offset + 12 : offset + 16], "big")
        if chunk_type == b"IEND":
            seen_end = True
            break
        offset = end
    if not seen_header or not seen_end:
        return [f"{path.name}: missing IHDR or IEND"]
    if (actual_width, actual_height) != (width, height):
        return [f"{path.name}: {actual_width}x{actual_height} does not match {width}x{height}"]
    return []


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise RenderError(
            f"frame {path} is outside the build directory", code="qa_failed", stage="qa"
        ) from exc


def build_frame_manifest(
    *,
    build_id: str,
    asset_id: str,
    plan: TimelinePlan,
    scene_ids: Sequence[str],
    frames_dir: Path,
    build_root: Path,
    width: int,
    height: int,
) -> FrameManifest:
    """Scan the rendered frames and build the evidence manifest.

    The scan is deliberately strict: a gap, an extra frame, or a structurally
    invalid PNG fails here instead of producing a manifest over bad output.
    """

    links = symlinks_in_tree(frames_dir)
    if links:
        raise RenderError(
            f"frame directory contains a symlink: {links[0].as_posix()}",
            code="qa_failed",
            stage="qa",
        )
    entries = _frame_paths(frames_dir)
    if not entries:
        raise RenderError("no frames were rendered", code="output_missing", stage="output")
    if len(entries) != plan.total_frames:
        raise RenderError(
            f"expected {plan.total_frames} frames, found {len(entries)}",
            code="frame_mismatch",
            stage="output",
        )
    indices = [index for index, _path in entries]
    if indices != list(range(len(entries))):
        missing = sorted(set(range(len(entries))) - set(indices))[:5]
        raise RenderError(
            f"frame indices are not contiguous; missing {missing}",
            code="frame_mismatch",
            stage="output",
        )

    frames: list[FrameEntry] = []
    problems: list[str] = []
    for index, path in entries:
        found = png_problems(path, width, height)
        if found:
            problems.extend(found)
            continue
        frames.append(
            FrameEntry(
                index=index,
                path=_relative(path, build_root),
                sha256=sha256_file(path),
                width=width,
                height=height,
            )
        )
    if problems:
        raise RenderError(
            "; ".join(problems[:MAX_REPORTED_PROBLEMS]),
            code="output_corrupt",
            stage="output",
        )

    spans = [
        SceneFrameSpan(scene_id=scene_id, start_frame=start, end_frame=end)
        for scene_id, start, end in plan.scene_bounds(scene_ids)
    ]
    try:
        return FrameManifest(
            build_id=build_id,
            asset_id=asset_id,
            fps_num=plan.fps_num,
            fps_den=plan.fps_den,
            width=width,
            height=height,
            total_frames=plan.total_frames,
            scenes=spans,
            frames=frames,
        )
    except ValidationError as exc:
        raise RenderError(
            f"frame manifest is invalid: {exc}", code="qa_failed", stage="qa"
        ) from exc


def write_frame_manifest(manifest: FrameManifest, path: Path) -> Path:
    return write_json(path, manifest)


def verify_frame_manifest(
    manifest: FrameManifest,
    *,
    build_root: Path,
    frames_dir: Path,
    plan: TimelinePlan,
    decode_frames: bool = True,
) -> list[str]:
    """Re-check the manifest against the files, independently of the builder."""

    problems: list[str] = []
    if manifest.fps_num != plan.fps_num or manifest.fps_den != plan.fps_den:
        problems.append(
            f"manifest fps {manifest.fps_num}/{manifest.fps_den} does not match "
            f"{plan.fps_num}/{plan.fps_den}"
        )
    if manifest.total_frames != plan.total_frames:
        problems.append(
            f"manifest total_frames {manifest.total_frames} does not match {plan.total_frames}"
        )
    if len(manifest.scenes) != len(plan.scene_frames):
        problems.append(
            f"manifest has {len(manifest.scenes)} scene spans, expected {len(plan.scene_frames)}"
        )
    else:
        for span, count in zip(manifest.scenes, plan.scene_frames, strict=True):
            if span.end_frame - span.start_frame != count:
                problems.append(
                    f"scene '{span.scene_id}' covers {span.end_frame - span.start_frame} "
                    f"frames, expected {count}"
                )

    root = build_root.resolve()
    for link in symlinks_in_tree(frames_dir):
        problems.append(f"frame directory contains a symlink: {link.as_posix()}")
    listed: set[str] = set()
    for entry in manifest.frames:
        unresolved = build_root / entry.path
        if unresolved.is_symlink() or symlink_components(unresolved, root):
            problems.append(f"frame {entry.index}: path contains a symlink")
            continue
        path = unresolved.resolve()
        try:
            path.relative_to(root)
        except ValueError:
            problems.append(f"frame {entry.index}: path escapes the build directory")
            continue
        listed.add(path.relative_to(root).as_posix())
        if not path.is_file():
            problems.append(f"frame {entry.index}: missing {entry.path}")
            continue
        if sha256_file(path) != entry.sha256:
            problems.append(f"frame {entry.index}: sha256 does not match")
        structural = png_problems(path, entry.width, entry.height)
        if structural:
            problems.extend(structural)

    actual: set[str] = set()
    for _index, path in _frame_paths(frames_dir):
        if path.is_symlink():
            continue  # already reported above
        try:
            actual.add(path.resolve().relative_to(root).as_posix())
        except ValueError:
            problems.append(f"frame {path.name} resolves outside the build directory")
    missing = sorted(listed - actual)
    unexpected = sorted(actual - listed)
    if missing:
        problems.append(f"manifest lists frames that are absent: {missing[:5]}")
    if unexpected:
        problems.append(f"build directory has frames absent from the manifest: {unexpected[:5]}")

    if decode_frames and not problems:
        decode = _decode_problems(manifest, build_root)
        if decode:
            problems.append(decode)
    return problems[:MAX_REPORTED_PROBLEMS]


def _decode_problems(manifest: FrameManifest, build_root: Path) -> str:
    binary = shutil.which("ffmpeg")
    if binary is None:
        return "ffmpeg is not installed, so the frame sequence cannot be decoded"
    parents = {(build_root / entry.path).resolve().parent for entry in manifest.frames}
    if len(parents) != 1:
        return "frames are spread across several directories; cannot decode a sequence"
    parent = parents.pop()
    pattern = parent / "%06d.png"
    command = [
        binary,
        "-v",
        "error",
        "-framerate",
        f"{manifest.fps_num}/{manifest.fps_den}",
        "-start_number",
        "0",
        "-i",
        str(pattern),
        "-f",
        "null",
        "-",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=DECODE_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"ffmpeg decode could not run: {exc.__class__.__name__}"
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        message = detail[-1] if detail else f"exit code {completed.returncode}"
        return f"ffmpeg could not decode the frame sequence: {message[:300]}"
    return ""
