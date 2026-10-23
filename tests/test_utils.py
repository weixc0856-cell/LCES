"""Small helpers used by the CLI and the evidence path."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from content_studio.cli import app
from content_studio.utils import redact_home


def test_redact_home_replaces_the_current_home_prefix():
    home = str(Path.home())
    redacted = redact_home(f"解释器: {home}/work/LCES/.venv/bin/python")
    assert home not in redacted
    assert redacted == "解释器: ~/work/LCES/.venv/bin/python"


def test_redact_home_keeps_other_users_and_relative_paths():
    assert redact_home("/home/other/work") == "/home/other/work"
    assert redact_home("var/lces.sqlite3") == "var/lces.sqlite3"


def test_doctor_never_prints_the_home_directory(tmp_path, monkeypatch):
    """Doctor output is uploaded as evidence (P2.3-E)."""

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0, result.output
    assert str(Path.home()) not in result.output
