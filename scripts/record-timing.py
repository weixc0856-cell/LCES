#!/usr/bin/env python
"""Record the real narration timing baseline for P9-D1.

    python scripts/record-timing.py --project projects/<course> \
        --audio build/media/narration-take1.m4a --method human_recording \
        --reader "author-name" \
        --scene-seconds build/media/scene-seconds.json \
        --notes "full read-through, one pause per scene"

Rules this tool enforces:

- only ``human_readthrough`` or ``human_recording`` may be recorded; TTS and
  text estimates cannot satisfy D1;
- the audio file must live inside the project (Gate B resolves it relative);
- the record is bound to the current ``speaker_script.json`` hash, so editing
  the script after recording invalidates it;
- per-scene seconds may cover a subset of slides (gaps are pauses), but every
  slide id must exist and every value must be positive.

The tool writes ``internal/qa/timing_evidence.json``; it does not confirm the
human acceptance and does not touch the contract.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from content_studio.content import load_speaker_script  # noqa: E402
from content_studio.course_quality import (  # noqa: E402
    TimingEvidence,
    load_contract,
    timing_path,
)
from content_studio.errors import LCESError  # noqa: E402
from content_studio.media import probe_duration  # noqa: E402
from content_studio.utils import sha256_file, utc_now, write_json_atomic  # noqa: E402

ALLOWED_METHODS = frozenset({"human_readthrough", "human_recording"})


def build_timing_evidence(
    project_dir: Path,
    *,
    audio: Path,
    method: str,
    measured_seconds: float | None = None,
    scene_seconds: dict[str, float] | None = None,
    voice: str = "",
    notes: str = "",
    expected_script_sha256: str = "",
) -> TimingEvidence:
    project_dir = Path(project_dir).resolve()
    if method not in ALLOWED_METHODS:
        raise ValueError(
            f"method must be one of {sorted(ALLOWED_METHODS)}; TTS and estimates cannot satisfy D1"
        )
    audio_path = Path(audio)
    if not audio_path.is_absolute():
        audio_path = (project_dir / audio_path).resolve()
    try:
        relative_audio = audio_path.relative_to(project_dir)
    except ValueError as exc:
        raise ValueError("audio must live inside the project workspace") from exc
    if not audio_path.is_file():
        raise ValueError(f"audio file not found: {relative_audio.as_posix()}")

    script = load_speaker_script(project_dir)
    if script is None:
        raise ValueError("internal/speaker_script.json is missing")
    contract = load_contract(project_dir)
    if contract is None:
        raise ValueError("the course contract is missing; target duration is unknown")

    seconds = measured_seconds if measured_seconds is not None else probe_duration(audio_path)
    if seconds <= 0:
        raise ValueError("measured seconds must be positive")
    script_hash = sha256_file(project_dir / "internal" / "speaker_script.json")
    if expected_script_sha256 and script_hash != expected_script_sha256:
        raise ValueError(
            "speaker_script.json changed since the recording plan "
            f"(expected {expected_script_sha256[:12]}…, got {script_hash[:12]}…)"
        )

    slides = {section.slide_id for section in script.sections}
    scenes = {str(key): float(value) for key, value in (scene_seconds or {}).items()}
    unknown = sorted(set(scenes) - slides)
    if unknown:
        raise ValueError(f"scene_seconds names unknown slides: {unknown}")
    if any(value <= 0 for value in scenes.values()):
        raise ValueError("scene seconds must be positive")
    if scenes and sum(scenes.values()) > float(seconds) + 1.0:
        raise ValueError("scene seconds exceed the measured total; check the per-scene split")

    return TimingEvidence(
        project_id=script.project_id,
        method=method,  # type: ignore[arg-type]
        measured_seconds=float(seconds),
        target_minutes=contract.target_duration_minutes,
        script_sha256=script_hash,
        audio_path=relative_audio.as_posix(),
        audio_sha256=sha256_file(audio_path),
        voice=voice.strip(),
        scene_seconds=scenes,
        generated_at=utc_now(),
        notes=notes.strip(),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--method", required=True, choices=sorted(ALLOWED_METHODS))
    parser.add_argument("--measured-seconds", type=float, default=None)
    parser.add_argument("--scene-seconds", type=Path, default=None)
    parser.add_argument("--reader", default="")
    parser.add_argument(
        "--expected-script-sha256",
        default="",
        help="Refuse if speaker_script.json no longer has this hash (frozen plan)",
    )
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    scenes: dict[str, float] = {}
    if args.scene_seconds is not None:
        scenes = json.loads(args.scene_seconds.read_text(encoding="utf-8"))

    try:
        record = build_timing_evidence(
            args.project,
            audio=args.audio,
            method=args.method,
            measured_seconds=args.measured_seconds,
            scene_seconds=scenes,
            voice=args.reader,
            notes=args.notes,
            expected_script_sha256=args.expected_script_sha256,
        )
    except (ValueError, OSError, LCESError) as exc:
        print(f"ERROR {exc}")
        return 1

    path = timing_path(args.project.resolve())
    write_json_atomic(path, record)
    print(f"wrote {path}")
    scene_sum = sum(record.scene_seconds.values())
    gap = record.measured_seconds - scene_sum
    print(
        f"method={record.method} measured={record.measured_seconds:.2f}s "
        f"target={record.target_minutes:.1f}min scenes={len(record.scene_seconds)} "
        f"scene_sum={scene_sum:.1f}s gap={gap:.1f}s"
    )
    print("Human acceptance must still confirm the timing; this file is evidence, not approval.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
