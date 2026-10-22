import json
from pathlib import Path

import pytest

from content_studio.errors import ConfigurationError
from content_studio.eval import (
    EvalTask,
    build_report,
    evaluate_output,
    load_tasks,
    run_tasks,
    write_report,
)
from content_studio.providers.base import GenerationRequest, GenerationResult, ModelProvider


def _task(**overrides) -> EvalTask:
    values = {
        "id": "task-001",
        "task_type": "json_fields",
        "prompt": "输出 JSON",
        "expect": {"kind": "json_object", "keys": ["a"]},
    }
    values.update(overrides)
    return EvalTask.model_validate(values)


class _StubProvider(ModelProvider):
    name = "stub"
    model = "stub-1"

    def __init__(self, outputs: list[str], fail_on: int | None = None) -> None:
        self._outputs = list(outputs)
        self._fail_on = fail_on
        self._index = 0

    def generate(self, request: GenerationRequest) -> GenerationResult:
        index = self._index
        self._index += 1
        if self._fail_on is not None and index == self._fail_on:
            raise RuntimeError("provider exploded")
        return GenerationResult(
            text=self._outputs[index],
            provider=self.name,
            model=self.model,
            latency_ms=5,
        )


def test_load_tasks_skips_comments_and_blank_lines(tmp_path):
    path = tmp_path / "set.jsonl"
    path.write_text(
        "# comment\n\n"
        + json.dumps(_task().model_dump(mode="json"))
        + "\n"
        + json.dumps(_task(id="task-002").model_dump(mode="json"))
        + "\n",
        encoding="utf-8",
    )
    tasks = load_tasks(path)
    assert [task.id for task in tasks] == ["task-001", "task-002"]


def test_load_tasks_rejects_invalid_lines(tmp_path):
    path = tmp_path / "set.jsonl"
    path.write_text('{"id": "bad id"}\n', encoding="utf-8")
    with pytest.raises(ConfigurationError, match="invalid task on line 1"):
        load_tasks(path)


def test_shipped_benchmark_is_valid():
    tasks = load_tasks(Path("evals/basic.jsonl"))
    assert len(tasks) == 8
    assert len({task.id for task in tasks}) == 8
    assert {task.task_type for task in tasks} >= {
        "json_fields",
        "classification",
        "outline",
        "rewrite",
        "concept_explanation",
        "multi_source_summary",
        "evidence_matching",
        "complex_analysis",
    }


def test_json_object_check():
    task = _task(expect={"kind": "json_object", "keys": ["a", "b"]})
    assert evaluate_output(task, '{"a": 1, "b": 2}') == []
    assert "缺少字段" in evaluate_output(task, '{"a": 1}')[0]
    assert "不是合法 JSON" in evaluate_output(task, "not json")[0]


def test_choice_check():
    task = _task(expect={"kind": "choice", "choices": ["transformer", "cnn"]})
    assert evaluate_output(task, "Transformer") == []
    assert evaluate_output(task, "rnn") == ["输出未包含任一允许选项: transformer, cnn"]


def test_contains_all_and_min_chars():
    task = _task(expect={"kind": "contains_all", "terms": ["成本", "隐私"]})
    assert evaluate_output(task, "成本与隐私的权衡") == []
    assert "缺少必需内容" in evaluate_output(task, "只谈成本")[0]

    long_task = _task(expect={"kind": "min_chars", "min_chars": 10})
    assert evaluate_output(long_task, "一二三四五六七八九十") == []
    assert "少于要求" in evaluate_output(long_task, "太短")[0]


def test_run_tasks_scores_and_isolates_failures():
    tasks = [
        _task(id="ok-task", expect={"kind": "json_object", "keys": ["a"]}),
        _task(id="bad-task", expect={"kind": "choice", "choices": ["x"]}),
        _task(id="boom-task", expect={"kind": "min_chars", "min_chars": 1}),
    ]
    provider = _StubProvider(['{"a": 1}', "y", "never used"], fail_on=2)

    results = run_tasks(tasks, provider)

    assert [result.passed for result in results] == [True, False, False]
    assert results[1].failures
    assert "RuntimeError" in results[2].error


def test_report_records_provider_and_counts(tmp_path):
    provider = _StubProvider(['{"a": 1}'])
    results = run_tasks([_task()], provider)
    report = build_report(provider, results)
    path = write_report(report, tmp_path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["provider"] == "stub"
    assert payload["model"] == "stub-1"
    assert payload["passed"] == 1
    assert payload["total"] == 1
    assert payload["lces_version"]
    assert payload["results"][0]["task_id"] == "task-001"
