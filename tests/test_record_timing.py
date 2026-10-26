"""P9-D1 timing record: only human methods, bound to the current script."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from content_studio.course_quality import (
    CourseContract,
    CourseModule,
    CourseObjective,
    TimingEvidence,
)
from content_studio.models import ScriptSection, SpeakerScript
from content_studio.paths import ensure_project_layout
from content_studio.utils import write_json, write_text

ROOT = Path(__file__).resolve().parents[1]


def _build():
    path = ROOT / "scripts" / "record-timing.py"
    spec = importlib.util.spec_from_file_location("record_timing", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.build_timing_evidence


def _project(tmp_path: Path) -> Path:
    root = ensure_project_layout(tmp_path / "project")
    write_json(
        root / "internal" / "speaker_script.json",
        SpeakerScript(
            project_id="timing-course",
            sections=[
                ScriptSection(slide_id="slide-001", narration="第一段", estimated_seconds=50),
                ScriptSection(slide_id="slide-002", narration="第二段", estimated_seconds=60),
            ],
        ),
    )
    write_json(
        root / "internal" / "plan" / "course_contract.json",
        CourseContract(
            project_id="timing-course",
            audience="测试受众",
            target_duration_minutes=20,
            timing_rule="以实测为准",
            objectives=[
                CourseObjective(
                    objective_id="objective-01", statement="解释", slide_ids=["slide-001"]
                )
            ],
            modules=[
                CourseModule(
                    module_id="module-01",
                    title="一",
                    target_minutes=20,
                    slide_ids=["slide-001"],
                )
            ],
            deliverables=["幻灯片"],
        ),
    )
    write_text(root / "build" / "media" / "narration.m4a", "fake-audio-bytes")
    return root


def test_builds_a_timing_record_bound_to_the_script(tmp_path):
    root = _project(tmp_path)

    record = _build()(
        root,
        audio=Path("build/media/narration.m4a"),
        method="human_recording",
        measured_seconds=1197.5,
        scene_seconds={"slide-001": 50, "slide-002": 60},
        voice="author",
        notes="one take",
    )

    assert isinstance(record, TimingEvidence)
    assert record.method == "human_recording"
    assert record.measured_seconds == 1197.5
    assert record.audio_path == "build/media/narration.m4a"
    assert record.scene_seconds == {"slide-001": 50.0, "slide-002": 60.0}
    assert record.script_sha256
    assert record.target_minutes == 20


def test_rejects_tts_and_estimates(tmp_path):
    root = _project(tmp_path)

    with pytest.raises(ValueError, match="TTS and estimates"):
        _build()(
            root,
            audio=Path("build/media/narration.m4a"),
            method="tts_readthrough",
            measured_seconds=100,
        )


def test_rejects_unknown_scene_ids_and_outside_audio(tmp_path):
    root = _project(tmp_path)
    outside = tmp_path / "outside.m4a"
    write_text(outside, "audio")

    with pytest.raises(ValueError, match="unknown slides"):
        _build()(
            root,
            audio=Path("build/media/narration.m4a"),
            method="human_recording",
            measured_seconds=100,
            scene_seconds={"slide-999": 10},
        )
    with pytest.raises(ValueError, match="inside the project"):
        _build()(
            root,
            audio=outside,
            method="human_recording",
            measured_seconds=100,
        )


def test_rejects_a_stale_frozen_script(tmp_path):
    root = _project(tmp_path)

    with pytest.raises(ValueError, match="changed since the recording plan"):
        _build()(
            root,
            audio=Path("build/media/narration.m4a"),
            method="human_recording",
            measured_seconds=100,
            expected_script_sha256="0" * 64,
        )


def test_rejects_scene_seconds_above_the_measured_total(tmp_path):
    root = _project(tmp_path)

    with pytest.raises(ValueError, match="exceed the measured total"):
        _build()(
            root,
            audio=Path("build/media/narration.m4a"),
            method="human_recording",
            measured_seconds=100,
            scene_seconds={"slide-001": 80, "slide-002": 80},
        )
