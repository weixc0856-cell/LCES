# MCP and the Tool Layer

Phase 6 exposes a small, permissioned tool surface over MCP. It is an adapter,
not a second implementation: every MCP tool calls `tools.invoke_tool`, so
validation, permissions, and logging behave exactly as they do elsewhere.

MCP is optional. Without the `mcp` extra the CLI works unchanged, and
`lces mcp-serve` explains how to install it.

## Tools

| Tool | Access | What it returns |
|---|---|---|
| `project_status` | read | Project metadata, latest task, QA gate summary, blocking check ids |
| `task_status` | read | One task plus its stage runs |
| `qa_report` | read | Full QA report (checks, gates, timestamps) |
| `release_manifest` | read | Release verification result and manifest |
| `run_validate` | write | Re-runs Gate 1-3 and returns the new status/gates |

Access levels:

- `read` — always allowed for a connected client.
- `write` — only when the server started with `--allow-write`.
- `release` — reserved; **no release, approve, delete, or shell tool exists**.

`run_validate` only runs the validation stage. It cannot approve, release, or
bypass a failing gate: the tool returns the QA verdict, and the normal
`approve`/`release` commands still enforce every check.

## Running

```powershell
uv sync --extra mcp
uv run lces mcp-serve --caller "my-client"            # read-only
uv run lces mcp-serve --caller "my-client" --allow-write
```

The server speaks MCP over stdio. Register it in the client's MCP config as
`uv run lces mcp-serve`.

## Validation, permissions, logging

- Inputs are Pydantic models (`ProjectInput`, `TaskInput`, `ReleaseInput`) with
  `project_id`/`version` patterns and a positive `task_id`; invalid payloads
  never reach a handler.
- Project paths are resolved from `LCES_PROJECTS_DIR` plus a validated
  `project_id`; tools cannot read arbitrary files.
- Every call appends one JSONL line to `var/tool_calls.jsonl`:
  timestamp, caller, tool, access, status (`ok`/`error`/`invalid`/`denied`),
  scalar parameters, error text, duration. No file contents, prompts, or keys
  are logged.
- An unauthorized call is logged as `denied` and raises `ToolPermissionError`.

## What MCP deliberately cannot do

- Publish or approve a release.
- Read files outside the projects directory.
- Execute shell commands.
- Bypass Gate 1-4. A client that wants to publish still has to go through
  `lces approve` and `lces release` on the host.

## Adding a tool

1. Add a Pydantic input model and a handler in `tools.py`; reuse existing
   business functions rather than reimplementing them.
2. Choose the lowest access level that works.
3. Add a `ToolSpec` to `TOOLS`, a thin wrapper in `mcp_server.py`, and tests for
   success, invalid input, and permission denial.
