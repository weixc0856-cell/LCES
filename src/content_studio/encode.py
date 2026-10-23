"""Encode a verified frame sequence with the system FFmpeg (P1.3).

Encoding never writes the published path. The adapter encodes into a staging
directory on the same filesystem, verifies the result, and only then performs
an atomic ``os.replace``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from content_studio.errors import RenderError
from content_studio.media import ffmpeg_path, ffmpeg_version
from content_studio.models import FrameManifest
from content_studio.utils import sha256_file

DEFAULT_TIMEOUT_SECONDS = 600


def frame_sequence_dir(manifest: FrameManifest, build_root: Path) -> Path:
    return (build_root / manifest.frames[0].path).resolve().parent


def build_encode_command(
    manifest: FrameManifest,
    *,
    build_root: Path,
    output: Path,
    ffmpeg_bin: str,
) -> list[str]:
    parent = frame_sequence_dir(manifest, build_root)
    return [
        ffmpeg_bin,
        "-v",
        "error",
        "-y",
        "-framerate",
        f"{manifest.fps_num}/{manifest.fps_den}",
        "-start_number",
        "0",
        "-i",
        str(parent / "%06d.png"),
        "-frames:v",
        str(manifest.total_frames),
        "-an",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-preset",
        "medium",
        "-movflags",
        "+faststart",
        str(output),
    ]


def encode_frames(
    manifest: FrameManifest,
    *,
    build_root: Path,
    output: Path,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> Path:
    """Encode the manifest's frames to ``output``; raises ``encode_failed``."""

    binary = ffmpeg_path()
    if binary is None:
        raise RenderError("ffmpeg is not installed", code="encode_failed", stage="encode")
    command = build_encode_command(
        manifest, build_root=build_root, output=output, ffmpeg_bin=binary
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderError(
            f"ffmpeg encoding exceeded {timeout_seconds}s",
            code="encode_failed",
            stage="encode",
        ) from exc
    except OSError as exc:
        raise RenderError(
            f"ffmpeg could not run: {exc.__class__.__name__}",
            code="encode_failed",
            stage="encode",
        ) from exc
    if completed.returncode != 0:
        detail = (completed.stderr or "").strip().splitlines()
        message = detail[-1] if detail else f"exit code {completed.returncode}"
        raise RenderError(
            f"ffmpeg encoding failed: {message[:300]}",
            code="encode_failed",
            stage="encode",
        )
    if not output.is_file() or output.stat().st_size == 0:
        raise RenderError("ffmpeg produced no video", code="encode_failed", stage="encode")
    return output


def redact_command(command: list[str], path_root: Path) -> list[str]:
    """Replace build-specific absolute paths so the report can be shared.

    The encode report is uploaded as CI evidence. Absolute paths leak the
    runner's filesystem layout and mean nothing to a reviewer, while the
    relative frame path plus ``manifest_sha256`` keep the command auditable.
    The FFmpeg binary is reduced to its basename; ``ffmpeg_version`` records
    which build ran.
    """

    root = Path(os.path.abspath(path_root))
    redacted: list[str] = []
    for index, argument in enumerate(command):
        if index == 0:
            redacted.append(Path(argument).name or argument)
            continue
        if not Path(argument).is_absolute():
            redacted.append(argument)
            continue
        try:
            relative = Path(os.path.abspath(argument)).relative_to(root)
        except ValueError:
            redacted.append(argument)
            continue
        redacted.append(f"<build>/{relative.as_posix()}")
    return redacted


def encode_report(
    manifest: FrameManifest,
    *,
    output: Path,
    command: list[str],
    manifest_sha256: str,
    provenance: dict[str, str] | None = None,
    path_root: Path | None = None,
) -> dict:
    """The evidence a build records about how the video was produced.

    ``provenance`` (P2.3-C) carries the Level 1 input traceability for the
    render: tool versions and the hashes of the npm manifests the build
    consumed. It is optional so older callers keep the 1.0 shape; the
    Motion Canvas adapter always supplies it.

    ``path_root`` (P2.3-E) redacts the FFmpeg command to paths relative to
    the project's build directory. Reports are uploaded as artifacts, and a
    runner path is both a leak and noise; the manifest still pins the exact
    frame sequence.
    """

    if path_root is not None:
        schema_version = "1.2"
    elif provenance is not None:
        schema_version = "1.1"
    else:
        schema_version = "1.0"
    report: dict[str, Any] = {
        "schema_version": schema_version,
        "build_id": manifest.build_id,
        "asset_id": manifest.asset_id,
        "frames": manifest.total_frames,
        "fps_num": manifest.fps_num,
        "fps_den": manifest.fps_den,
        "width": manifest.width,
        "height": manifest.height,
        "ffmpeg_version": ffmpeg_version(),
        "command": redact_command(command, path_root) if path_root is not None else command,
        "command_paths": "build-relative" if path_root is not None else "absolute",
        "manifest_sha256": manifest_sha256,
        "video_sha256": sha256_file(output),
        "video_bytes": output.stat().st_size,
    }
    if provenance is not None:
        report["provenance"] = dict(provenance)
    return report
