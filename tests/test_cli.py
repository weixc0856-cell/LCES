import json

from typer.testing import CliRunner

from content_studio.cli import app


def test_models_command_without_probe(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["models", "--no-probe"])
    assert result.exit_code == 0, result.output
    assert "默认 provider" in result.output


def test_help_lists_local_capable_commands(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "models" in result.output
    assert "run" in result.output


def test_mcp_serve_without_sdk_explains_the_extra(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import content_studio.mcp_server as mcp_server

    monkeypatch.setattr(mcp_server, "mcp_available", lambda: False)

    result = CliRunner().invoke(app, ["mcp-serve"])
    assert result.exit_code == 1
    assert "uv sync --extra mcp" in result.output


def test_review_claims_records_a_decision(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project"
    (project / "internal").mkdir(parents=True)
    (project / "project.yaml").write_text("project_id: demo\ntitle: 示例\n", encoding="utf-8")
    (project / "internal" / "claims.json").write_text(
        json.dumps(
            [
                {
                    "claim_id": "claim-001",
                    "statement": "示例主张",
                    "claim_type": "fact",
                    "importance": "key",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = CliRunner().invoke(
        app,
        [
            "review-claims",
            str(project),
            "--claim",
            "claim-001",
            "--status",
            "supported",
            "--by",
            "tester",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "supported" in result.output

    stored = json.loads((project / "internal" / "claims.json").read_text(encoding="utf-8"))
    assert stored[0]["verification_status"] == "supported"
    assert stored[0]["reviewer"] == "tester"


def test_review_claims_rejects_unknown_status(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project = tmp_path / "project"
    (project / "internal").mkdir(parents=True)
    (project / "project.yaml").write_text("project_id: demo\ntitle: 示例\n", encoding="utf-8")
    (project / "internal" / "claims.json").write_text("[]", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        ["review-claims", str(project), "--claim", "claim-001", "--status", "ok", "--by", "x"],
    )
    assert result.exit_code == 1
    assert "unknown review status" in result.output


def test_status_shows_run_lineage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from content_studio.storage import TaskStore

    store = TaskStore(tmp_path / "var" / "lces.sqlite3")
    task_id = store.create_task(
        "demo-course",
        "paper_course",
        "mock",
        "mock-deterministic",
        input_sha256="b" * 64,
        config={"provider": "mock"},
    )
    run_id = store.start_stage(task_id, "ingest", "mock", "mock-deterministic")
    store.finish_stage(run_id, status="pass", artifacts=["internal/source_registry.json"])

    result = CliRunner().invoke(app, ["status", "--task", str(task_id)])

    assert result.exit_code == 0, result.output
    assert "run_id=" in result.output
    assert "b" * 64 in result.output
    assert "retry=0" in result.output
    assert "internal/source_registry.json" in result.output
