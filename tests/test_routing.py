import pytest
from pydantic import ValidationError

from content_studio.errors import ConfigurationError
from content_studio.routing import RoutingPolicy, load_routing


def test_routing_file_resolves_stage_and_default(tmp_path):
    path = tmp_path / "routing.yaml"
    path.write_text("default: local\nstages:\n  research: deepseek\n", encoding="utf-8")
    policy = load_routing(path)
    assert policy.provider_for("research", "mock") == "deepseek"
    assert policy.provider_for("outline", "mock") == "local"


def test_routing_rejects_unknown_stage(tmp_path):
    path = tmp_path / "routing.yaml"
    path.write_text("stages:\n  ingest: local\n", encoding="utf-8")
    with pytest.raises(ConfigurationError):
        load_routing(path)


def test_routing_rejects_unknown_provider():
    with pytest.raises(ValidationError):
        RoutingPolicy(default="mystery-vendor")


def test_routing_missing_file(tmp_path):
    with pytest.raises(ConfigurationError):
        load_routing(tmp_path / "missing.yaml")


def test_routing_supports_per_stage_fallback(tmp_path):
    path = tmp_path / "routing.yaml"
    path.write_text(
        "default: local\n"
        "stages:\n"
        "  research: {provider: deepseek, fallback: local}\n"
        "  generate: local\n",
        encoding="utf-8",
    )
    policy = load_routing(path)

    assert policy.provider_for("research", "mock") == "deepseek"
    assert policy.fallback_for("research", "deepseek") == "local"
    assert policy.fallback_for("research", "local") == "", "no retry with the same provider"
    assert policy.fallback_for("generate", "local") == "", "plain stages have no fallback"


def test_routing_rejects_unknown_fallback_provider(tmp_path):
    path = tmp_path / "routing.yaml"
    path.write_text(
        "stages:\n  research: {provider: deepseek, fallback: mystery}\n", encoding="utf-8"
    )
    with pytest.raises(ConfigurationError):
        load_routing(path)
