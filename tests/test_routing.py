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
