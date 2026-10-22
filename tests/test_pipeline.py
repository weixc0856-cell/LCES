from pathlib import Path

import pytest

from content_studio.content import load_public_content, load_speaker_script
from content_studio.errors import ProviderError, ValidationFailure
from content_studio.models import ProjectConfig
from content_studio.orchestrator import STAGES, run_pipeline
from content_studio.paths import ensure_project_layout
from content_studio.release import build_release
from content_studio.settings import Settings
from content_studio.storage import TaskStore


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        provider="mock",
        database_path=tmp_path / "var" / "lces.sqlite3",
        projects_dir=tmp_path / "projects",
        temperature=0.2,
    )


def _project(tmp_path: Path) -> tuple[Path, ProjectConfig]:
    root = ensure_project_layout(tmp_path / "project")
    (root / "input" / "sample.md").write_text(
        "# 示例论文\n\n这是用于测试的正文段落，不包含真实研究结论。\n", encoding="utf-8"
    )
    config = ProjectConfig(
        project_id="demo-course",
        title="示例课程",
        input_paths=["input/sample.md"],
        target_duration_minutes=12,
    )
    return root, config


def test_full_pipeline_runs_all_stages(tmp_path):
    root, config = _project(tmp_path)
    settings = _settings(tmp_path)

    result = run_pipeline(root, config, settings, provider_name="mock")

    assert result.failed_stage is None
    assert result.completed_stages == list(STAGES)
    assert result.qa is not None

    assert (root / "internal" / "source_registry.json").is_file()
    assert (root / "internal" / "evidence_ledger.csv").is_file()
    assert (root / "internal" / "research_brief.md").is_file()
    assert (root / "content" / "outline.json").is_file()
    assert (root / "content" / "public_content.json").is_file()
    assert (root / "internal" / "speaker_script.json").is_file()
    assert (root / "content" / "reading_edition.json").is_file()
    assert (root / "build" / "slides" / "index.html").is_file()
    assert (root / "build" / "reading_edition.html").is_file()

    public = load_public_content(root)
    script = load_speaker_script(root)
    assert public is not None and script is not None
    assert [slide.slide_id for slide in public.slides] == [
        section.slide_id for section in script.sections
    ]

    assert result.qa.blocking_failures
    assert result.status == "NEEDS_REVISION"

    store = TaskStore(settings.database_path)
    task = store.get_task(result.task_id)
    assert task is not None and task["status"] == "NEEDS_REVISION"


def test_pipeline_retries_stage_with_fallback(tmp_path, monkeypatch):
    root, config = _project(tmp_path)
    settings = _settings(tmp_path).model_copy(update={"local_model": "qwen-local"})
    routing = tmp_path / "routing.yaml"
    routing.write_text("stages:\n  outline: {provider: local, fallback: mock}\n", encoding="utf-8")

    from content_studio import orchestrator

    calls: list[str] = []

    def fake_outline(project_dir, config, settings, provider):
        calls.append(provider.name)
        if provider.name == "local":
            raise ProviderError("local exploded", provider="local")
        return None

    monkeypatch.setitem(orchestrator._STAGE_FUNCS, "outline", fake_outline)

    result = run_pipeline(root, config, settings, only_stage="outline", routing_path=routing)

    assert result.failed_stage is None
    assert calls == ["local", "mock"]

    runs = TaskStore(settings.database_path).stage_runs(result.task_id)
    assert [run["status"] for run in runs] == ["fail", "pass"]
    assert [run["provider"] for run in runs] == ["local", "mock"]


def test_pipeline_stops_when_no_fallback_is_configured(tmp_path, monkeypatch):
    root, config = _project(tmp_path)
    settings = _settings(tmp_path)

    from content_studio import orchestrator

    def failing(project_dir, config, settings, provider):
        raise ProviderError("boom", provider=provider.name)

    monkeypatch.setitem(orchestrator._STAGE_FUNCS, "outline", failing)

    result = run_pipeline(root, config, settings, only_stage="outline")

    assert result.status == "FAILED"
    assert "ProviderError" in (result.error or "")


def test_pipeline_can_rerun_single_stage(tmp_path):
    root, config = _project(tmp_path)
    settings = _settings(tmp_path)
    run_pipeline(root, config, settings, provider_name="mock")

    rerun = run_pipeline(root, config, settings, only_stage="build")
    assert rerun.failed_stage is None
    assert rerun.completed_stages == ["build"]


def test_pipeline_reports_failed_stage(tmp_path):
    root, config = _project(tmp_path)
    settings = _settings(tmp_path)

    # Skip ingest and start at research: there is no source registry.
    result = run_pipeline(root, config, settings, only_stage="research")
    assert result.failed_stage == "research"
    assert result.status == "FAILED"


def test_release_is_blocked_when_qa_fails(tmp_path):
    root, config = _project(tmp_path)
    settings = _settings(tmp_path)
    run_pipeline(root, config, settings, provider_name="mock")
    with pytest.raises(ValidationFailure):
        build_release(root, config, "v1")


def test_pipeline_applies_stage_routing(tmp_path):
    root, config = _project(tmp_path)
    settings = Settings(
        _env_file=None,
        provider="deepseek",
        deepseek_api_key="",
        database_path=tmp_path / "var" / "lces.sqlite3",
        projects_dir=tmp_path / "projects",
    )
    routing = tmp_path / "routing.yaml"
    routing.write_text(
        "default: mock\nstages:\n  research: mock\n  outline: mock\n  generate: mock\n",
        encoding="utf-8",
    )

    result = run_pipeline(root, config, settings, routing_path=routing)

    assert result.failed_stage is None
    store = TaskStore(settings.database_path)
    runs = {run["stage"]: run for run in store.stage_runs(result.task_id)}
    assert runs["research"]["provider"] == "mock"
    assert runs["outline"]["provider"] == "mock"
    assert runs["generate"]["provider"] == "mock"
    assert runs["ingest"]["provider"] == "none"
