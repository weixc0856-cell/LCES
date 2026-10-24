import pytest

from content_studio.errors import (
    ConfigurationError,
    OutputTruncatedError,
    ProviderResponseError,
)
from content_studio.models import ContentOutline
from content_studio.providers.base import (
    GenerationRequest,
    GenerationResult,
    Message,
    ModelProvider,
    Usage,
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

    def __init__(
        self,
        outputs: list[str],
        *,
        finish_reason: str = "",
        usage: Usage | None = None,
    ) -> None:
        self.outputs = list(outputs)
        self.calls = 0
        self.finish_reason = finish_reason
        self.usage = usage or Usage()

    def generate(self, request: GenerationRequest) -> GenerationResult:
        self.calls += 1
        text = self.outputs.pop(0)
        self.last_result = GenerationResult(
            text=text,
            provider=self.name,
            model=self.model,
            usage=self.usage,
            finish_reason=self.finish_reason,
        )
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


def test_structured_output_rejects_a_truncated_response():
    provider = ScriptedProvider([VALID_OUTLINE], finish_reason="length")

    with pytest.raises(OutputTruncatedError) as caught:
        provider.generate_structured(_request(), ContentOutline)

    assert caught.value.finish_reason == "length"
    assert caught.value.provider == "scripted"
    assert provider.calls == 1


def test_structured_usage_sums_every_call_in_the_stage():
    provider = ScriptedProvider(
        [VALID_OUTLINE, VALID_OUTLINE], usage=Usage(input_tokens=1, output_tokens=2)
    )

    provider.generate_structured(_request(), ContentOutline)
    provider.generate_structured(_request(), ContentOutline)

    assert provider.structured_usage.input_tokens == 2
    assert provider.structured_usage.output_tokens == 4
    assert provider.structured_usage.total_tokens == 6


def test_max_tokens_reaches_the_request_unchanged():
    provider = ScriptedProvider([VALID_OUTLINE])
    provider.generate_structured(
        GenerationRequest(messages=[Message("user", "x")], max_tokens=16384), ContentOutline
    )
    assert provider.calls == 1


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
