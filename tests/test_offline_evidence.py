"""The offline verifier must judge the right report and the right video path."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "verify-offline-evidence.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("verify_offline_evidence", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def verifier() -> ModuleType:
    return _load()


def _build(root: Path, *, requests: list[str] | None = None, failures: int = 2) -> Path:
    test_dir = root / "test_smoke0"
    frames = test_dir / "motion" / "build-001" / "frames"
    frames.mkdir(parents=True)
    media = test_dir / "media"
    media.mkdir()
    (media / "course.mp4").write_bytes(b"encoded")
    (frames / "report.json").write_text(
        json.dumps(
            {
                "mode": "render",
                "terminal": "completed",
                "finished": True,
                "frames": 30,
                "expected_frames": 30,
                "external_requests": ["https://fonts.googleapis.com/x"]
                if requests is None
                else requests,
                "request_failures": failures,
            }
        ),
        encoding="utf-8",
    )
    return root


def test_completed_offline_build_passes(verifier, tmp_path):
    failures, summaries = verifier.verify(_build(tmp_path))
    assert failures == []
    assert len(summaries) == 1


def test_missing_external_attempts_fail(verifier, tmp_path):
    failures, _summaries = verifier.verify(_build(tmp_path, requests=[]))
    assert any("no external request was attempted" in failure for failure in failures)


def test_unblocked_external_requests_fail(verifier, tmp_path):
    failures, _summaries = verifier.verify(_build(tmp_path, failures=0))
    assert any("no external request failed" in failure for failure in failures)


def test_missing_video_fails(verifier, tmp_path):
    root = _build(tmp_path)
    (root / "test_smoke0" / "media" / "course.mp4").unlink()
    failures, _summaries = verifier.verify(root)
    assert any("no published video" in failure for failure in failures)


def test_cancelled_and_timeout_reports_are_not_completions(verifier, tmp_path):
    root = _build(tmp_path)
    report = root / "test_smoke0" / "motion" / "build-001" / "frames" / "report.json"
    payload = json.loads(report.read_text(encoding="utf-8"))
    payload.update({"terminal": "cancelled", "finished": False})
    report.write_text(json.dumps(payload), encoding="utf-8")
    failures, summaries = verifier.verify(root)
    assert any("no completed render report" in failure for failure in failures)
    assert summaries == []
