"""Permissioned tool layer shared by MCP and any other client (Phase 6).

Tools are thin wrappers over existing business logic: they validate their
input with Pydantic, check the caller's access level, delegate, and append one
JSONL record. Nothing here can bypass the QA gates: there is no release,
approval, delete, or arbitrary-command tool, and running validation only
re-runs ``lces validate``.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from content_studio.errors import ConfigurationError, ToolPermissionError, ValidationFailure
from content_studio.orchestrator import load_project_config, run_pipeline
from content_studio.paths import safe_project_id
from content_studio.release import load_qa_report, verify_release
from content_studio.settings import Settings
from content_studio.storage import TaskStore
from content_studio.utils import utc_now

Access = Literal["read", "write", "release"]


class ProjectInput(BaseModel):
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")


class TaskInput(BaseModel):
    task_id: int = Field(ge=1)


class ReleaseInput(BaseModel):
    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    version: str = Field(pattern=r"^v[0-9]+$")


class EmptyInput(BaseModel):
    pass


@dataclass(frozen=True)
class ToolContext:
    settings: Settings
    caller: str
    allow_write: bool = False
    allow_release: bool = False
    log_path: Path | None = None


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[BaseModel]
    access: Access
    handler: Callable[[Any, ToolContext], dict[str, Any]]


def _project_root(context: ToolContext, project_id: str) -> Path:
    root = context.settings.projects_dir / safe_project_id(project_id)
    if not (root / "project.yaml").is_file():
        raise ValidationFailure(f"project not found: {project_id}")
    return root


def _project_status(data: ProjectInput, context: ToolContext) -> dict[str, Any]:
    root = _project_root(context, data.project_id)
    config = load_project_config(root / "project.yaml")
    store = TaskStore(context.settings.database_path)
    tasks = store.list_tasks(limit=1, project_id=config.project_id)
    report = load_qa_report(root)
    return {
        "project_id": config.project_id,
        "title": config.title,
        "content_mode": config.content_mode,
        "latest_task": tasks[0] if tasks else None,
        "gates": report.gate_status() if report else {},
        "blocking_failures": [item.check_id for item in report.blocking_failures] if report else [],
    }


def _task_status(data: TaskInput, context: ToolContext) -> dict[str, Any]:
    store = TaskStore(context.settings.database_path)
    task = store.get_task(data.task_id)
    if task is None:
        raise ValidationFailure(f"task not found: {data.task_id}")
    return {
        "task": task,
        "stages": store.stage_runs(data.task_id),
    }


def _qa_report(data: ProjectInput, context: ToolContext) -> dict[str, Any]:
    root = _project_root(context, data.project_id)
    report = load_qa_report(root)
    if report is None:
        raise ValidationFailure("QA report missing; run validation first")
    return {
        "project_id": report.project_id,
        "generated_at": report.generated_at.isoformat(),
        "gates": report.gate_status(),
        "checks": [check.model_dump(mode="json") for check in report.checks],
    }


def _release_manifest(data: ReleaseInput, context: ToolContext) -> dict[str, Any]:
    root = _project_root(context, data.project_id)
    manifest, errors = verify_release(root, data.version)
    return {
        "project_id": data.project_id,
        "version": data.version,
        "verified": manifest is not None and not errors,
        "errors": errors,
        "manifest": manifest.model_dump(mode="json") if manifest is not None else None,
    }


def _run_validate(data: ProjectInput, context: ToolContext) -> dict[str, Any]:
    root = _project_root(context, data.project_id)
    config = load_project_config(root / "project.yaml")
    result = run_pipeline(root, config, context.settings, only_stage="validate")
    gates = result.qa.gate_status() if result.qa is not None else {}
    return {
        "project_id": config.project_id,
        "task_id": result.task_id,
        "status": result.status,
        "gates": gates,
        "blocking_failures": [item.check_id for item in result.qa.blocking_failures]
        if result.qa
        else [],
    }


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            "project_status",
            "Project metadata, latest task, and QA gate summary.",
            ProjectInput,
            "read",
            _project_status,
        ),
        ToolSpec(
            "task_status",
            "One task with its stage runs.",
            TaskInput,
            "read",
            _task_status,
        ),
        ToolSpec(
            "qa_report",
            "Full QA report for a project.",
            ProjectInput,
            "read",
            _qa_report,
        ),
        ToolSpec(
            "release_manifest",
            "Verify a release directory and return its manifest.",
            ReleaseInput,
            "read",
            _release_manifest,
        ),
        ToolSpec(
            "run_validate",
            "Re-run Gate 1-3 validation for a project (does not release).",
            ProjectInput,
            "write",
            _run_validate,
        ),
    )
}


def _allowed(access: Access, context: ToolContext) -> bool:
    if access == "read":
        return True
    if access == "write":
        return context.allow_write
    return context.allow_release


def invoke_tool(name: str, payload: dict[str, Any], context: ToolContext) -> dict[str, Any]:
    """Validate, authorize, execute, and log one tool call."""

    spec = TOOLS.get(name)
    if spec is None:
        raise ConfigurationError(f"unknown tool '{name}'; known: {', '.join(sorted(TOOLS))}")
    if not _allowed(spec.access, context):
        _write_log(context, name, spec.access, "denied", payload, "permission denied")
        raise ToolPermissionError(
            f"tool '{name}' requires '{spec.access}' access; caller '{context.caller}' "
            "was not granted it"
        )

    started = time.perf_counter()
    try:
        data = spec.input_model.model_validate(payload)
    except ValidationError as exc:
        _write_log(context, name, spec.access, "invalid", payload, str(exc))
        raise ValidationFailure(f"invalid input for '{name}': {exc}") from exc

    try:
        result = spec.handler(data, context)
    except Exception as exc:
        _write_log(
            context,
            name,
            spec.access,
            "error",
            payload,
            f"{exc.__class__.__name__}: {exc}",
            started=started,
        )
        raise

    _write_log(context, name, spec.access, "ok", payload, "", started=started)
    return result


def _write_log(
    context: ToolContext,
    tool: str,
    access: Access,
    status: str,
    payload: dict[str, Any],
    error: str,
    *,
    started: float | None = None,
) -> None:
    path = context.log_path or context.settings.tool_log_path
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": utc_now().isoformat(),
        "caller": context.caller,
        "tool": tool,
        "access": access,
        "status": status,
        "params": _sanitize(payload),
        "error": error[:300],
        "duration_ms": int((time.perf_counter() - started) * 1000) if started else 0,
    }
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _sanitize(payload: dict[str, Any]) -> dict[str, str]:
    """Keep the log to short scalar parameters; never record file contents."""

    sanitized: dict[str, str] = {}
    for key, value in payload.items():
        if isinstance(value, (str, int, float, bool)):
            sanitized[str(key)] = str(value)[:200]
    return sanitized
