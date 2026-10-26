"""The per-unit timing helper concatenates PCM WAV sections without re-encoding."""

from __future__ import annotations

import importlib.util
import wave
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "scripts" / "measure-narration-timing.py"
    spec = importlib.util.spec_from_file_location("measure_timing", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _wav(path: Path, *, rate: int = 8000, frames: int = 800) -> Path:
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * frames)
    return path


def test_sections_are_concatenated(tmp_path):
    first = _wav(tmp_path / "a.wav")
    second = _wav(tmp_path / "b.wav")
    out = tmp_path / "all.wav"

    _load()._concat_wavs([first, second], out)

    with wave.open(str(out), "rb") as handle:
        assert handle.getnframes() == 1600
        assert handle.getframerate() == 8000
        assert handle.getnchannels() == 1


def test_different_formats_are_refused(tmp_path):
    first = _wav(tmp_path / "a.wav")
    second = _wav(tmp_path / "b.wav", rate=16000)

    with pytest.raises(SystemExit, match="format differs"):
        _load()._concat_wavs([first, second], tmp_path / "all.wav")
