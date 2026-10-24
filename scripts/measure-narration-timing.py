"""Measure a full narration read-through with Windows SAPI + FFprobe.

This is a *measured* audio duration, not a text estimate. It is still not a
human performance: the record stores ``method=tts_readthrough`` and the voice
name, and the human course acceptance must confirm the timing separately.

Usage (Windows)::

    uv run python scripts/measure-narration-timing.py projects/attention-is-all-you-need
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "src")

from content_studio.content import load_speaker_script
from content_studio.course_quality import TimingEvidence, timing_path
from content_studio.utils import utc_now, write_json_atomic

DEFAULT_VOICE = "Microsoft Huihui Desktop"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _duration(audio: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(audio),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"ffprobe failed: {result.stderr.strip()}")
    return float(result.stdout.strip())


def _synthesize(text: str, audio: Path, voice: str) -> None:
    with tempfile.TemporaryDirectory() as temp:
        text_path = Path(temp) / "narration.txt"
        text_path.write_text(text, encoding="utf-8")
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.SelectVoice('{voice}'); "
            f"$s.SetOutputToWaveFile('{audio}'); "
            f"$s.Speak([IO.File]::ReadAllText('{text_path}', [Text.Encoding]::UTF8)); "
            "$s.Dispose()"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise SystemExit(f"SAPI failed: {result.stderr.strip()}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    parser.add_argument("--audio", type=Path, default=Path("var/timing/narration.wav"))
    parser.add_argument("--target-minutes", type=float, default=0.0)
    args = parser.parse_args()

    project = args.project_dir.resolve()
    script = load_speaker_script(project)
    if script is None:
        raise SystemExit("speaker script is missing")
    text = "\n".join(section.narration for section in script.sections)
    audio = args.audio if args.audio.is_absolute() else project / args.audio
    audio.parent.mkdir(parents=True, exist_ok=True)
    _synthesize(text, audio, args.voice)
    seconds = _duration(audio)

    target = args.target_minutes
    if not target:
        import yaml

        payload = yaml.safe_load((project / "project.yaml").read_text(encoding="utf-8")) or {}
        target = float(payload.get("target_duration_minutes", 20) or 20)

    record = TimingEvidence(
        project_id=project.name,
        method="tts_readthrough",
        measured_seconds=round(seconds, 2),
        target_minutes=target,
        script_sha256=_sha256(project / "internal" / "speaker_script.json"),
        audio_path=audio.relative_to(project).as_posix()
        if audio.is_relative_to(project)
        else str(audio),
        audio_sha256=_sha256(audio),
        voice=args.voice,
        generated_at=utc_now(),
        notes=(
            "TTS read-through of the full narration. This is a measured audio duration, "
            "not a human performance; human acceptance must confirm timing."
        ),
    )
    path = timing_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, record)
    print(f"audio: {audio}")
    print(f"measured: {seconds / 60:.2f} min | target: {target:.1f} min")
    print(f"timing evidence: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
