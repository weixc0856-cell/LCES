"""Provider-neutral model interface (PRD section 6)."""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, replace
from typing import Literal, TypeVar

from pydantic import BaseModel, ValidationError

from content_studio.errors import ConfigurationError, ProviderResponseError
from content_studio.utils import extract_json_object

Role = Literal["system", "user", "assistant"]
ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass
class Message:
    role: Role
    content: str


@dataclass
class GenerationRequest:
    messages: list[Message]
    temperature: float = 0.2
    max_tokens: int = 4096
    json_mode: bool = False
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def as_dict(self) -> dict[str, int]:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class GenerationResult:
    text: str
    provider: str
    model: str
    usage: Usage = field(default_factory=Usage)
    latency_ms: int = 0


class ModelProvider(ABC):
    """Business code talks to this interface only."""

    name: str = "base"
    model: str = ""
    native_json_mode: bool = False
    last_result: GenerationResult | None = None

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Generate text for a request."""

    def generate_structured(self, request: GenerationRequest, schema: type[ModelT]) -> ModelT:
        """Generate and validate JSON matching a Pydantic contract.

        One repair attempt is made when the first response is not valid JSON or
        does not satisfy the schema. No silent coercion is performed.
        """

        instruction = (
            "Return only one JSON object that validates against the JSON Schema below. "
            "Do not wrap it in Markdown fences and do not add commentary.\n"
            + json.dumps(schema.model_json_schema(), ensure_ascii=False)
        )
        messages = list(request.messages)
        if messages and messages[0].role == "system":
            messages[0] = Message("system", messages[0].content + "\n\n" + instruction)
        else:
            messages.insert(0, Message("system", instruction))

        pending = replace(request, messages=messages, json_mode=True)
        last_error: Exception | None = None
        for _attempt in range(2):
            result = self.generate(pending)
            self.last_result = result
            try:
                payload = extract_json_object(result.text)
                return schema.model_validate(payload)
            except (ValueError, ValidationError) as exc:
                last_error = exc
                pending = replace(
                    pending,
                    messages=[
                        *pending.messages,
                        Message("assistant", result.text),
                        Message(
                            "user",
                            "That response was not valid for the contract. Error: "
                            f"{exc}. Return corrected JSON only.",
                        ),
                    ],
                )
        raise ProviderResponseError(
            f"{self.name} did not return a valid {schema.__name__}: {last_error}",
            provider=self.name,
        )

    def get_usage(self, result: GenerationResult) -> Usage:
        return result.usage


def elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)


class NullProvider(ModelProvider):
    """Placeholder for stages that never call a model (ingest/build/validate).

    Keeping it explicit avoids requiring API keys for local-only commands and
    prevents a misleading provider name in task records.
    """

    name = "none"
    model = ""

    def generate(self, request: GenerationRequest) -> GenerationResult:
        raise ConfigurationError("this stage does not use a model provider")
