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
