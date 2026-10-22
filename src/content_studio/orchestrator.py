"""Stage orchestration and task state transitions (PRD section 13)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from content_studio.content import (
    generate_outline,
    generate_public_content,
    generate_reading_edition,
    generate_speaker_script,
    load_outline,
    load_public_content,
    load_reading_edition,
)
from content_studio.errors import LCESError, ValidationFailure
from content_studio.ingestion import ingest_project, load_registry
from content_studio.models import ProjectConfig, QAReport, TaskStatus
from content_studio.paths import template_dir
from content_studio.providers.base import ModelProvider, NullProvider
from content_studio.providers.factory import build_provider
from content_studio.release import load_qa_report
from content_studio.rendering import build_public_html, build_reading_html
from content_studio.research import load_evidence_ledger, load_research_brief, run_research
from content_studio.routing import load_routing
from content_studio.settings import Settings
from content_studio.storage import TaskStore
from content_studio.validation import run_validation

STAGES = ("ingest", "research", "outline", "generate", "build", "validate")
MODEL_STAGES = frozenset({"research", "outline", "generate"})

STAGE_STATUS: dict[str, TaskStatus] = {
    "ingest": "INGESTING",
    "research": "RESEARCHING",
    "outline": "PLANNING",
    "generate": "GENERATING",
    "build": "GENERATING",
    "validate": "VALIDATING",
}


@dataclass
class PipelineResult:
    task_id: int
    status: str
    completed_stages: list[str]
    qa: QAReport | None = None
    failed_stage: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.failed_stage is None


def _require_brief(project_dir: Path):
    brief = load_research_brief(project_dir)
    if brief is None:
        raise ValidationFailure("research brief missing; run the research stage first")
    return brief


def _stage_ingest(
    project_dir: Path, config: ProjectConfig, settings: Settings, provider: ModelProvider
) -> None:
    ingest_project(project_dir, config, settings)


def _stage_research(
    project_dir: Path, config: ProjectConfig, settings: Settings, provider: ModelProvider
) -> None:
    budget = (
        settings.local_prompt_char_budget
        if provider.name == "local"
        else settings.prompt_char_budget
    )
    run_research(
        project_dir,
        config,
        provider,
        prompt_char_budget=budget,
    )


def _stage_outline(
    project_dir: Path, config: ProjectConfig, settings: Settings, provider: ModelProvider
) -> None:
    brief = _require_brief(project_dir)
    ledger = load_evidence_ledger(project_dir)
    generate_outline(project_dir, config, brief, ledger, provider)


def _stage_generate(
    project_dir: Path, config: ProjectConfig, settings: Settings, provider: ModelProvider
) -> None:
    outline = load_outline(project_dir)
    if outline is None:
        raise ValidationFailure("outline missing; run the outline stage first")
    ledger = load_evidence_ledger(project_dir)
    registry = load_registry(project_dir)
    if registry is None:
        raise ValidationFailure("source registry missing; run the ingest stage first")
    generate_public_content(project_dir, config, outline, ledger, registry, provider)
    generate_speaker_script(project_dir, config, outline, ledger, provider)
    generate_reading_edition(project_dir, config, outline, ledger, registry, provider)


def _stage_build(
    project_dir: Path, config: ProjectConfig, settings: Settings, provider: ModelProvider
) -> None:
    public = load_public_content(project_dir)
    reading = load_reading_edition(project_dir)
    if public is None:
        raise ValidationFailure("public content missing; run the generate stage first")
    if reading is None:
        raise ValidationFailure("reading edition missing; run the generate stage first")
    templates = template_dir()
    build_public_html(
        public,
        templates,
        project_dir / "build" / "slides" / "index.html",
        project_dir=project_dir,
    )
    build_reading_html(
        reading,
        templates,
        project_dir / "build" / "reading_edition.html",
        project_dir=project_dir,
    )


def _stage_validate(
    project_dir: Path, config: ProjectConfig, settings: Settings, provider: ModelProvider
) -> QAReport:
    return run_validation(project_dir, config, template_dir(), browser_qa=settings.browser_qa)


_STAGE_FUNCS = {
    "ingest": _stage_ingest,
    "research": _stage_research,
    "outline": _stage_outline,
    "generate": _stage_generate,
    "build": _stage_build,
    "validate": _stage_validate,
}


def _select_stages(from_stage: str | None, only_stage: str | None) -> list[str]:
    if only_stage:
        if only_stage not in STAGES:
            raise ValidationFailure(
                f"unknown stage '{only_stage}'; choose from {', '.join(STAGES)}"
            )
        return [only_stage]
    if from_stage:
        if from_stage not in STAGES:
            raise ValidationFailure(
                f"unknown stage '{from_stage}'; choose from {', '.join(STAGES)}"
            )
        return list(STAGES[STAGES.index(from_stage) :])
    return list(STAGES)


def run_pipeline(
    project_dir: Path,
    config: ProjectConfig,
    settings: Settings,
    *,
    provider_name: str | None = None,
    from_stage: str | None = None,
    only_stage: str | None = None,
    task_id: int | None = None,
    store: TaskStore | None = None,
    routing_path: Path | None = None,
) -> PipelineResult:
    project_dir = project_dir.resolve()
    stages = _select_stages(from_stage, only_stage)
    configured_routing = routing_path or settings.routing_file
    policy = load_routing(configured_routing) if configured_routing else None

    def provider_for(stage: str) -> ModelProvider:
        if stage not in MODEL_STAGES:
            return NullProvider()
        if provider_name:
            return build_provider(settings, provider_name)
        if policy is not None:
            return build_provider(settings, policy.provider_for(stage, settings.provider))
        return build_provider(settings)

    store = store or TaskStore(settings.database_path)
    task_provider = provider_name or (
        policy.default if policy is not None and policy.default else settings.provider
    )
    if task_id is None:
        task_id = store.create_task(
            config.project_id,
            config.content_mode,
            task_provider,
            settings.model_for(task_provider),
        )
    store.log_event(task_id, "info", f"pipeline stages: {', '.join(stages)}")

    completed: list[str] = []
    qa: QAReport | None = None

    for stage in stages:
        provider = provider_for(stage)
        store.update_task(task_id, status=STAGE_STATUS[stage], stage=stage)
        run_id = store.start_stage(task_id, stage, provider.name, provider.model)
        try:
            outcome = _STAGE_FUNCS[stage](project_dir, config, settings, provider)
            usage = provider.last_result.usage.as_dict() if provider.last_result else {}
            store.finish_stage(run_id, status="pass", usage=usage)
            completed.append(stage)
            store.log_event(task_id, "info", f"stage {stage} completed")
            if isinstance(outcome, QAReport):
                qa = outcome
        except Exception as exc:  # stage boundary: record, then report to caller
            message = f"{exc.__class__.__name__}: {exc}"
            store.finish_stage(run_id, status="fail", error=message)
            store.update_task(task_id, status="FAILED", stage=stage, error=message)
            store.log_event(task_id, "error", f"stage {stage} failed: {message}")
            return PipelineResult(
                task_id=task_id,
                status="FAILED",
                completed_stages=completed,
                failed_stage=stage,
                error=message,
            )
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()

    if qa is None:
        qa = load_qa_report(project_dir)
    final: TaskStatus
    if qa is not None and qa.blocking_failures:
        final = "NEEDS_REVISION"
    elif "validate" in completed:
        final = "REVIEW_REQUIRED"
    elif completed:
        final = STAGE_STATUS[completed[-1]]
    else:
        final = "CREATED"
    store.update_task(task_id, status=final, stage=completed[-1] if completed else "")
    return PipelineResult(task_id=task_id, status=final, completed_stages=completed, qa=qa)


def load_project_config(path: Path) -> ProjectConfig:
    import yaml

    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        return ProjectConfig.model_validate(data)
    except ValueError as exc:
        raise LCESError(f"invalid project.yaml: {exc}") from exc
