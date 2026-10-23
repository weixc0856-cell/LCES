#!/usr/bin/env python3
"""Collect Motion Canvas evidence from a pytest basetemp tree.

Layout produced by the E2E tests::

    <root>/<test>/motion/<build_id>/frame_manifest.json
    <root>/<test>/motion/<build_id>/frames/report.json
    <root>/<test>/motion/<build_id>/frames/project/000000.png ...
    <root>/<test>/media/course.mp4
    <root>/<test>/project/internal/qa/{frame_manifest,encode_report}.json

This script uses only the Python standard library so the CI evidence step does
not depend on `find`, `head`, `sort`, or shell pipeline exit codes.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def frame_files(build: Path) -> list[Path]:
    frames = sorted(path for path in (build / "frames").rglob("*.png") if path.stem.isdigit())
    return frames


def build_label(manifest: Path, root: Path) -> str:
    """A unique label for a build or a project QA directory.

    Both a rendered build and the adapter's ``internal/qa`` copy contain a
    ``frame_manifest.json``; using only the final directory name would make
    every QA copy collide on ``qa``.
    """

    relative = manifest.parent.relative_to(root)
    parts = [part for part in relative.parts if part]
    if "qa" in parts:
        return "-".join(parts[:1] + ["qa"]) if len(parts) > 1 else "qa"
    return "-".join(parts)


def copy_if_file(source: Path, target: Path) -> None:
    if source.is_file():
        shutil.copy2(source, target)


def collect(root: Path, out: Path, *, keep_frames: bool, frames_out: Path | None) -> int:
    manifests = sorted(root.rglob("frame_manifest.json"))
    if not manifests:
        # A failed test may leave no build at all; the failure diagnostics
        # step handles that, so this is not a second error.
        print(f"no frame_manifest.json under {root}")
        return 0
    collected = 0
    for manifest in manifests:
        build = manifest.parent
        # The Gate 4 fixture stores its manifest under <test>/project/internal/qa;
        # that directory has no frames and is labelled by its own name.
        build_id = build.name
        target = out / "manifests" / build_label(manifest, root)
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(manifest, target / "frame_manifest.json")
        copy_if_file(build / "frames" / "report.json", target / "report.json")
        copy_if_file(build / "driver.log", target / "driver.log")
        copy_if_file(build / "encode_report.json", target / "encode_report.json")
        # MC-04 (P2.4-A): the QA copy sits next to the other evidence and is
        # its own manifest entry (internal/qa), so copy it from the build dir
        # as well as from a resolvable project root below.
        copy_if_file(build / "visual_qa.json", target / "visual_qa.json")
        # The adapter also copies its build evidence into the project's
        # internal/qa directory; keep that copy as the Gate 4 input. The
        # production test puts the build under <project>/build/motion/...,
        # so find the project root instead of assuming one directory depth.
        project_root = next(
            (parent for parent in build.parents if (parent / "project.yaml").is_file()),
            None,
        )
        qa_dir = project_root / "internal" / "qa" if project_root is not None else None
        if qa_dir is not None and qa_dir.is_dir():
            for name in (
                "encode_report.json",
                "frame_manifest.json",
                "visual_qa.json",
                "visual_assets.json",
                "render_manifest.json",
            ):
                copy_if_file(qa_dir / name, target / f"qa-{name}")
        frames = frame_files(build)
        if frames:
            shutil.copy2(frames[0], target / "first.png")
            shutil.copy2(frames[-1], target / "last.png")
        # <test>/motion/<build_id> -> <test>/media/course.mp4
        if len(build.parents) >= 2:
            copy_if_file(build.parents[1] / "media" / "course.mp4", target / "course.mp4")
        if keep_frames and frames_out is not None:
            staging = frames_out / build_id
            if staging.exists():
                shutil.rmtree(staging)
            staging.mkdir(parents=True)
            shutil.copy2(manifest, staging / "frame_manifest.json")
            copy_if_file(build / "frames" / "report.json", staging / "report.json")
            copy_if_file(build / "driver.log", staging / "driver.log")
            shutil.copytree(build / "frames", staging / "frames", dirs_exist_ok=True)
        print(f"{build_id}: {len(frames)} frames")
        collected += 1
    print(f"collected {collected} build(s) into {out}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--keep-frames", action="store_true")
    parser.add_argument("--frames-out", type=Path, default=None)
    args = parser.parse_args()
    if args.keep_frames and args.frames_out is None:
        parser.error("--keep-frames requires --frames-out")
    return collect(
        args.root,
        args.out,
        keep_frames=args.keep_frames,
        frames_out=args.frames_out,
    )


if __name__ == "__main__":
    raise SystemExit(main())
