"""Task-level model evaluation (continuous work, PRD section 9).

A benchmark is a fixed JSONL set of prompts plus mechanical expectations, so
the same tasks can be run against local and cloud providers and compared. Only
checkable properties are scored; "reads nicely" is not a criterion here.
"""

from __future__ import annotations

import json
import platform
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from content_studio import __version__
from content_studio.errors import ConfigurationError
from content_studio.providers.base import (
    GenerationRequest,
    Message,
    ModelProvider,
    elapsed_ms,
)
from content_studio.utils import extract_json_object, utc_now, write_json

CheckKind = Literal["json_object", "choice", "contains_all", "min_chars"]


class Expect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: CheckKind
    keys: list[str] = Field(default_factory=list)
    choices: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    min_chars: int = Field(default=0, ge=0)


class EvalTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    task_type: str
    system: str = ""
    prompt: str
    expect: Expect
    max_tokens: int = Field(default=300, ge=16, le=4096)
    temperature: float = Field(default=0.2, ge=0, le=2)


@dataclass
class EvalResult:
    task_id: str
    task_type: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    latency_ms: int = 0
    usage: dict[str, int] = field(default_factory=dict)
    output_excerpt: str = ""
    error: str = ""


@dataclass
class EvalReport:
    provider: str
    model: str
    results: list[EvalResult]
    generated_at: str = ""

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result.passed)

    def summary(self) -> str:
        total = len(self.results)
        latency = [r.latency_ms for r in self.results if r.latency_ms]
        average = int(sum(latency) / len(latency)) if latency else 0
        return f"通过 {self.passed}/{total} | 平均延迟 {average}ms"


def load_tasks(path: Path) -> list[EvalTask]:
    if not path.is_file():
        raise ConfigurationError(f"benchmark set not found: {path}")
    tasks: list[EvalTask] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        try:
            tasks.append(EvalTask.model_validate(json.loads(line)))
        except (ValueError, ValidationError) as exc:
            raise ConfigurationError(f"invalid task on line {number} of {path}: {exc}") from exc
    if not tasks:
        raise ConfigurationError(f"benchmark set is empty: {path}")
    return tasks


def evaluate_output(task: EvalTask, text: str) -> list[str]:
    expect = task.expect
    if expect.kind == "min_chars":
        if len(text.strip()) < expect.min_chars:
            return [f"输出 {len(text.strip())} 字，少于要求的 {expect.min_chars} 字"]
        return []
    if expect.kind == "contains_all":
        missing = [term for term in expect.terms if term.lower() not in text.lower()]
        return [f"缺少必需内容: {', '.join(missing)}"] if missing else []
    if expect.kind == "choice":
        lowered = text.lower()
        hits = [choice for choice in expect.choices if choice.lower() in lowered]
        if not hits:
            return [f"输出未包含任一允许选项: {', '.join(expect.choices)}"]
        return []
    try:
        payload = extract_json_object(text)
    except ValueError:
        return ["输出不是合法 JSON"]
    missing = [key for key in expect.keys if key not in payload]
    return [f"JSON 缺少字段: {', '.join(missing)}"] if missing else []


def run_tasks(tasks: list[EvalTask], provider: ModelProvider) -> list[EvalResult]:
    results: list[EvalResult] = []
    for task in tasks:
        messages = []
        if task.system:
            messages.append(Message("system", task.system))
        messages.append(Message("user", task.prompt))
        started = time.perf_counter()
        try:
            result = provider.generate(
                GenerationRequest(
                    messages=messages,
                    temperature=task.temperature,
                    max_tokens=task.max_tokens,
                )
            )
            usage = result.usage.as_dict()
            failures = evaluate_output(task, result.text)
            results.append(
                EvalResult(
                    task_id=task.id,
                    task_type=task.task_type,
                    passed=not failures,
                    failures=failures,
                    latency_ms=result.latency_ms or elapsed_ms(started),
                    usage=usage,
                    output_excerpt=result.text[:500],
                )
            )
        except Exception as exc:  # a failed call is a failed task, not a crash
            results.append(
                EvalResult(
                    task_id=task.id,
                    task_type=task.task_type,
                    passed=False,
                    latency_ms=elapsed_ms(started),
                    error=f"{exc.__class__.__name__}: {exc}",
                )
            )
    return results


def build_report(provider: ModelProvider, results: list[EvalResult]) -> EvalReport:
    return EvalReport(
        provider=provider.name,
        model=provider.model,
        results=results,
        generated_at=utc_now().isoformat(),
    )


def write_report(report: EvalReport, output_dir: Path) -> Path:
    stamp = utc_now().strftime("%Y%m%d-%H%M%S")
    path = output_dir / f"{stamp}-{report.provider}.json"
    write_json(
        path,
        {
            "generated_at": report.generated_at,
            "provider": report.provider,
            "model": report.model,
            "lces_version": __version__,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "passed": report.passed,
            "total": len(report.results),
            "results": [result.__dict__ for result in report.results],
        },
    )
    return path
