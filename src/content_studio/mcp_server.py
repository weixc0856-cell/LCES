"""Optional MCP binding over the permissioned tool layer (Phase 6).

MCP is a transport, not a second implementation: every tool delegates to
``tools.invoke_tool`` and therefore inherits its validation, permissions, and
logging. No release, approval, delete, or command-execution tool is exposed.
"""

from __future__ import annotations

from typing import Any

from content_studio.settings import Settings
from content_studio.tools import ToolContext, invoke_tool


def mcp_available() -> bool:
    try:
        import mcp.server.fastmcp  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return False
    return True


def build_server(
    settings: Settings,
    *,
    caller: str = "mcp-client",
    allow_write: bool = False,
):
    """Create a FastMCP server. Import failure is the caller's to report."""

    from mcp.server.fastmcp import FastMCP  # type: ignore[import-not-found]

    context = ToolContext(settings=settings, caller=caller, allow_write=allow_write)
    server = FastMCP("LCES")

    @server.tool()
    def project_status(project_id: str) -> dict[str, Any]:
        """Project metadata, latest task, and QA gate summary."""
        return invoke_tool("project_status", {"project_id": project_id}, context)

    @server.tool()
    def task_status(task_id: int) -> dict[str, Any]:
        """One task with its stage runs."""
        return invoke_tool("task_status", {"task_id": task_id}, context)

    @server.tool()
    def qa_report(project_id: str) -> dict[str, Any]:
        """Full QA report for a project."""
        return invoke_tool("qa_report", {"project_id": project_id}, context)

    @server.tool()
    def release_manifest(project_id: str, version: str) -> dict[str, Any]:
        """Verify a release directory and return its manifest."""
        return invoke_tool(
            "release_manifest",
            {"project_id": project_id, "version": version},
            context,
        )

    if allow_write:

        @server.tool()
        def run_validate(project_id: str) -> dict[str, Any]:
            """Re-run Gate 1-3 validation (does not release anything)."""
            return invoke_tool("run_validate", {"project_id": project_id}, context)

    return server


def run_stdio(
    settings: Settings,
    *,
    caller: str = "mcp-client",
    allow_write: bool = False,
) -> None:
    build_server(settings, caller=caller, allow_write=allow_write).run()
