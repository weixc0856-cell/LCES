import pytest

from content_studio.errors import ConfigurationError, ProviderResponseError
from content_studio.models import ContentOutline
from content_studio.providers.base import (
    GenerationRequest,
    GenerationResult,
    Message,
    ModelProvider,
)
from content_studio.providers.factory import build_provider
from content_studio.providers.mock import MockProvider
from content_studio.settings import Settings
from content_studio.utils import extract_json_object

VALID_OUTLINE = """
{
  "project_id": "demo-course",
  "title": "Demo",
  "audience": "testers",
  "prerequisites": [],
  "sections": [
    {
      "slide_id": "slide-001",
      "title": "Intro",
      "learning_objectives": [],
      "key_points": [],
      "evidence_ids": [],
      "visual_requirements": [],
      "estimated_minutes": 3
    }
  ],
  "total_minutes": 3
}
"""


class ScriptedProvider(ModelProvider):
    name = "scripted"
    model = "scripted-1"

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = list(outputs)
        self.calls = 0

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls += 1
        text = self.outputs.pop(0)
        self.last_result = GenerationResult(text=text, provider=self.name, model=self.model)
        return self.last_result


def _request() -> GenerationRequest:
    return GenerationRequest(messages=[Message("user", "design a course")])


def test_structured_output_accepts_code_fences():
    provider = ScriptedProvider([f"```json\n{VALID_OUTLINE}\n```"])
    outline = provider.generate_structured(_request(), ContentOutline)
    assert outline.sections[0].slide_id == "slide-001"


def test_structured_output_repairs_once():
    provider = ScriptedProvider(["not json at all", VALID_OUTLINE])
    outline = provider.generate_structured(_request(), ContentOutline)
    assert outline.total_minutes == 3
    assert provider.calls == 2


def test_structured_output_fails_after_repair():
    provider = ScriptedProvider(["nope", "still nope"])
    with pytest.raises(ProviderResponseError):
        provider.generate_structured(_request(), ContentOutline)


def test_extract_json_object_handles_prose():
    payload = extract_json_object('Here you go: {"a": 1} thanks')
    assert payload == {"a": 1}


def test_mock_provider_returns_valid_contract():
    provider = MockProvider()
    outline = provider.generate_structured(
        GenerationRequest(
            messages=[Message("user", "x")],
            metadata={"project_id": "demo-course", "title": "Demo", "evidence_ids": "evidence-001"},
        ),
        ContentOutline,
    )
    assert len(outline.sections) == 3
    assert outline.sections[0].evidence_ids == ["evidence-001"]


def test_factory_builds_mock_and_rejects_unknown():
    settings = Settings(_env_file=None, provider="mock")
    assert isinstance(build_provider(settings), MockProvider)
    with pytest.raises(ConfigurationError):
        build_provider(settings, "unknown-vendor")


def test_deepseek_requires_api_key():
    settings = Settings(_env_file=None, provider="deepseek", deepseek_api_key="")
    with pytest.raises(ConfigurationError):
        build_provider(settings)
