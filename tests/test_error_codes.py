"""The shared failure table must stay the single source of truth."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from content_studio.errors import (
    ERROR_CODES,
    ERROR_CODES_PATH,
    RenderCancelled,
    RenderError,
    exit_code_for,
    terminal_for,
)
from content_studio.paths import repository_root


def _table() -> dict[str, dict[str, object]]:
    payload = json.loads(ERROR_CODES_PATH.read_text(encoding="utf-8"))
    return payload["codes"]


def test_python_table_matches_the_json_file():
    table = _table()
    assert set(ERROR_CODES) == set(table)
    for name, spec in table.items():
        assert ERROR_CODES[name].stage == spec["stage"]
        assert ERROR_CODES[name].exit_code == spec["exit_code"]
        assert ERROR_CODES[name].terminal == spec["terminal"]
        assert exit_code_for(name) == spec["exit_code"]
        assert terminal_for(name) == spec["terminal"]


def test_terminal_states_are_only_failed_or_cancelled():
    terminals = {spec.terminal for spec in ERROR_CODES.values()}
    assert terminals == {"failed", "cancelled"}


def test_exit_codes_are_unique():
    codes = [spec.exit_code for spec in ERROR_CODES.values()]
    assert len(codes) == len(set(codes))


def test_cancelled_is_the_only_non_failed_terminal():
    assert terminal_for("cancelled") == "cancelled"
    for name in ERROR_CODES:
        if name != "cancelled":
            assert terminal_for(name) == "failed"


def test_render_error_rejects_unknown_codes():
    with pytest.raises(ValueError, match="unknown LCES error code"):
        RenderError("boom", code="not_a_code")


def test_render_error_defaults_to_render_failed():
    error = RenderError("boom")
    assert error.code == "render_failed"
    assert error.terminal == "failed"
    assert error.exit_code == exit_code_for("render_failed")


def test_render_cancelled_is_terminal_cancelled():
    error = RenderCancelled("stopped")
    assert error.code == "cancelled"
    assert error.terminal == "cancelled"


def test_every_code_used_in_source_exists():
    pattern = re.compile(r'code="([a-z_]+)"')
    missing: set[str] = set()
    for path in (repository_root() / "src").rglob("*.py"):
        for name in pattern.findall(path.read_text(encoding="utf-8")):
            if name not in ERROR_CODES:
                missing.add(f"{path.name}:{name}")
    assert not missing


def test_node_contract_loads_the_shared_table():
    script = (repository_root() / "motion" / "contract.mjs").read_text(encoding="utf-8")
    assert "error_codes.json" in script
    assert "LCES_ERROR_CODES_PATH" in script
    # The table must be parsed, not duplicated as a literal map.
    assert "ERROR_TABLE = JSON.parse" in script


def test_spike_contract_only_uses_shared_codes():
    script = (repository_root() / "spike" / "motion-canvas" / "contract.mjs").read_text(
        encoding="utf-8"
    )
    for name in re.findall(r"'([a-z_]+)'", script):
        if name in {"failed", "cancelled", "linux"}:
            continue
        if re.fullmatch(r"[a-z]+_[a-z_]+", name):
            assert name in ERROR_CODES, f"spike code {name} missing from the table"


def test_error_codes_file_lives_in_config():
    assert ERROR_CODES_PATH == Path(repository_root() / "config" / "error_codes.json")


def test_classify_error_uses_a_bounded_vocabulary():
    from content_studio.errors import (
        ConfigurationError,
        IngestionError,
        OutputTruncatedError,
        ProviderError,
        ValidationFailure,
        classify_error,
    )

    assert classify_error(ProviderError("x", provider="local")) == "provider"
    assert classify_error(OutputTruncatedError("x")) == "output_truncated"
    assert classify_error(ValidationFailure("x")) == "validation"
    assert classify_error(ConfigurationError("x")) == "configuration"
    assert classify_error(IngestionError("x")) == "ingestion"
    assert classify_error(RenderCancelled("x")) == "cancelled"
    assert classify_error(TimeoutError("x")) == "timeout"
    assert classify_error(KeyError("x")) == "KeyError"
