"""Independently check a downloaded production frame manifest.

Usage: uv run python scripts/verify-frame-manifest.py <artifact-dir>

Reads every manifest found under the artifact, picks the 300-frame production
build, and re-computes the evidence from the files on disk. This deliberately
does not import the project's verifier: the point is a second implementation.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import zlib
from pathlib import Path

SIGNATURE = bytes.fromhex("89504e470d0a1a0a")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def png_size(path: Path) -> tuple[int, int] | str:
    data = path.read_bytes()
    if not data.startswith(SIGNATURE):
        return "not a PNG"
    offset = 8
    width = height = 0
    saw_header = saw_end = False
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        kind = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            return f"truncated at {kind!r}"
        expected = int.from_bytes(data[end - 4 : end], "big")
        actual = zlib.crc32(data[offset + 4 : end - 4]) & 0xFFFFFFFF
        if expected != actual:
            return f"CRC mismatch in {kind!r}"
        if not saw_header and kind != b"IHDR":
            return "does not start with IHDR"
        if kind == b"IHDR":
            saw_header = True
            width = int.from_bytes(data[offset + 8 : offset + 12], "big")
            height = int.from_bytes(data[offset + 12 : offset + 16], "big")
        if kind == b"IEND":
            saw_end = True
            break
        offset = end
    if not saw_header or not saw_end:
        return "missing IHDR or IEND"
    return width, height


def main(root: Path) -> int:
    manifests = sorted(root.rglob("frame_manifest.json"))
    if not manifests:
        print("FAIL: no frame_manifest.json in the artifact")
        return 1
    chosen = None
    for path in manifests:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("total_frames") == 300:
            chosen = path
            break
    if chosen is None:
        print("FAIL: no 300-frame manifest found; manifests:", [str(p) for p in manifests])
        return 1

    build_root = chosen.parent
    manifest = json.loads(chosen.read_text(encoding="utf-8"))
    failures: list[str] = []
    before = len(failures)

    print("manifest:", chosen)
    print("manifest_sha256:", sha256(chosen))
    print("build_id:", manifest["build_id"], "| directory:", build_root.name)
    if manifest["build_id"] != build_root.name:
        failures.append("build_id does not match the build directory")

    report_path = next(build_root.rglob("report.json"), None)
    if report_path is None:
        failures.append("driver report.json is missing")
    else:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        print(
            "report:", {k: report.get(k) for k in ("build_id", "frames", "terminal", "error_code")}
        )
        if report.get("build_id") != manifest["build_id"]:
            failures.append("report build_id does not match the manifest")
        if report.get("frames") != manifest["total_frames"]:
            failures.append("report frame count does not match the manifest")
        if report.get("terminal") != "completed" or report.get("error_code"):
            failures.append("driver did not report a clean completed terminal state")

    if manifest["total_frames"] != 300:
        failures.append("total_frames is not 300")
    indices = [frame["index"] for frame in manifest["frames"]]
    if indices != list(range(300)):
        failures.append("frame indices are not contiguous 0..299")
    if len(indices) != len(set(indices)):
        failures.append("duplicate frame indices")

    start = 0
    for span in manifest["scenes"]:
        if span["start_frame"] != start:
            failures.append(f"scene span gap at {span['scene_id']}")
        start = span["end_frame"]
    if start != manifest["total_frames"]:
        failures.append("scene spans do not cover the whole build")
    print(
        "scenes:", [(s["scene_id"], s["start_frame"], s["end_frame"]) for s in manifest["scenes"]]
    )

    hashes_checked = 0
    pngs_checked = 0
    for frame in manifest["frames"]:
        path = (build_root / frame["path"]).resolve()
        try:
            path.relative_to(build_root.resolve())
        except ValueError:
            failures.append(f"frame {frame['index']}: path escapes the build")
            continue
        if not path.is_file():
            failures.append(f"frame {frame['index']}: missing file")
            continue
        if sha256(path) != frame["sha256"]:
            failures.append(f"frame {frame['index']}: hash mismatch")
        hashes_checked += 1
        size = png_size(path)
        if isinstance(size, str):
            failures.append(f"frame {frame['index']}: {size}")
        elif size != (manifest["width"], manifest["height"]):
            failures.append(f"frame {frame['index']}: {size} != expected dimensions")
        else:
            pngs_checked += 1

    actual = sorted(path for path in (build_root / "frames").rglob("*.png") if path.stem.isdigit())
    scheduled = {frame["path"] for frame in manifest["frames"]}
    listed_actual = {path.resolve().relative_to(build_root.resolve()).as_posix() for path in actual}
    if listed_actual != scheduled:
        failures.append(
            f"frame files differ from the manifest: +{sorted(listed_actual - scheduled)[:3]} "
            f"-{sorted(scheduled - listed_actual)[:3]}"
        )

    print(f"hashes_checked: {hashes_checked}/300")
    print(f"pngs_checked: {pngs_checked}/300")

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        print("decode: NOT_RUN (ffmpeg not on PATH; CI ran the decode as part of the build)")
    else:
        parent = (build_root / manifest["frames"][0]["path"]).resolve().parent
        completed = subprocess.run(
            [
                ffmpeg,
                "-v",
                "error",
                "-framerate",
                f"{manifest['fps_num']}/{manifest['fps_den']}",
                "-start_number",
                "0",
                "-i",
                str(parent / "%06d.png"),
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        print("decode exit:", completed.returncode)
        if completed.returncode != 0:
            failures.append("ffmpeg could not decode the sequence")

    if len(failures) == before:
        print("RESULT: PASS")
        return 0
    print("RESULT: FAIL")
    for failure in failures:
        print(" -", failure)
    return 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
