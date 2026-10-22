import json

import pytest

from content_studio.errors import ConfigurationError, ToolPermissionError, ValidationFailure
from content_studio.settings import Settings
from content_studio.tools import ToolContext, invoke_tool


def _settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        projects_dir=tmp_path / "projects",
        database_path=tmp_path / "var" / "lces.sqlite3",
        tool_log_path=tmp_path / "var" / "tool_calls.jsonl",
    )


def _project(settings: Settings) -> None:
    root = settings.projects_dir / "demo"
    root.mkdir(parents=True)
    (root / "project.yaml").write_text("project_id: demo\ntitle: 示例课程\n", encoding="utf-8")


def _context(settings: Settings, **kwargs) -> ToolContext:
    values = {"settings": settings, "caller": "pytest"}
    values.update(kwargs)
    return ToolContext(**values)


def _log_lines(settings: Settings) -> list[dict]:
    path = settings.tool_log_path
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_project_status_is_available_to_read_callers(tmp_path):
    settings = _settings(tmp_path)
    _project(settings)

    result = invoke_tool("project_status", {"project_id": "demo"}, _context(settings))

    assert result["project_id"] == "demo"
    assert result["title"] == "示例课程"
    assert result["latest_task"] is None

    log = _log_lines(settings)
    assert log[-1]["tool"] == "project_status"
    assert log[-1]["caller"] == "pytest"
    assert log[-1]["status"] == "ok"
    assert log[-1]["params"] == {"project_id": "demo"}


def test_unknown_project_is_a_validation_failure(tmp_path):
    settings = _settings(tmp_path)
    with pytest.raises(ValidationFailure, match="project not found"):
        invoke_tool("project_status", {"project_id": "missing"}, _context(settings))
    assert _log_lines(settings)[-1]["status"] == "error"


def test_invalid_input_is_rejected_before_the_handler(tmp_path):
    settings = _settings(tmp_path)
    with pytest.raises(ValidationFailure, match="invalid input"):
        invoke_tool("project_status", {"project_id": "BAD!"}, _context(settings))
    assert _log_lines(settings)[-1]["status"] == "invalid"


def test_unknown_tool_is_rejected(tmp_path):
    settings = _settings(tmp_path)
    with pytest.raises(ConfigurationError, match="unknown tool"):
        invoke_tool("delete_everything", {}, _context(settings))


def test_write_tool_requires_explicit_permission(tmp_path):
    settings = _settings(tmp_path)
    _project(settings)

    with pytest.raises(ToolPermissionError, match="requires 'write' access"):
        invoke_tool("run_validate", {"project_id": "demo"}, _context(settings))

    denied = _log_lines(settings)[-1]
    assert denied["status"] == "denied"
    assert denied["tool"] == "run_validate"


def test_release_permission_is_not_granted_to_read_only_context(tmp_path):
    settings = _settings(tmp_path)
    _project(settings)
    context = _context(settings)
    assert context.allow_release is False


def test_task_status_reports_missing_task(tmp_path):
    settings = _settings(tmp_path)
    with pytest.raises(ValidationFailure, match="task not found"):
        invoke_tool("task_status", {"task_id": 999}, _context(settings))


def test_qa_report_requires_a_report(tmp_path):
    settings = _settings(tmp_path)
    _project(settings)
    with pytest.raises(ValidationFailure, match="QA report missing"):
        invoke_tool("qa_report", {"project_id": "demo"}, _context(settings))


def test_mcp_server_reuses_the_same_tools(tmp_path):
    pytest.importorskip("mcp")
    import asyncio

    from content_studio.mcp_server import build_server

    settings = _settings(tmp_path)
    read_server = build_server(settings, caller="mcp-test")
    read_names = {tool.name for tool in asyncio.run(read_server.list_tools())}
    assert read_names == {"project_status", "task_status", "qa_report", "release_manifest"}

    write_server = build_server(settings, caller="mcp-test", allow_write=True)
    write_names = {tool.name for tool in asyncio.run(write_server.list_tools())}
    assert "run_validate" in write_names
    assert "release" not in write_names
