from pathlib import Path

import pytest

from content_studio.errors import ConfigurationError
from content_studio.storage import TaskStore
from content_studio.usage import (
    UNMETERED_NOTE,
    UNPRICED_NOTE,
    PricingPolicy,
    UsageRow,
    apply_pricing,
    collect_usage,
    load_pricing,
    total_cost,
)


def _store(tmp_path) -> TaskStore:
    return TaskStore(tmp_path / "lces.sqlite3")


def _run(store, task_id, stage, provider, model, status, usage) -> None:
    run_id = store.start_stage(task_id, stage, provider, model)
    store.finish_stage(run_id, status=status, usage=usage)


def test_usage_is_aggregated_from_stage_records(tmp_path):
    store = _store(tmp_path)
    task_id = store.create_task("demo", "paper_course", "local", "qwen")
    _run(store, task_id, "research", "local", "qwen", "pass", {"input_tokens": 100})
    _run(store, task_id, "outline", "local", "qwen", "fail", {})
    _run(
        store,
        task_id,
        "generate",
        "deepseek",
        "deepseek-chat",
        "pass",
        {"input_tokens": 1_000_000, "output_tokens": 500_000},
    )

    rows = {(row.provider, row.model): row for row in collect_usage(store)}

    local = rows[("local", "qwen")]
    assert local.calls == 2
    assert local.failures == 1
    assert local.input_tokens == 100
    assert local.output_tokens == 0

    cloud = rows[("deepseek", "deepseek-chat")]
    assert cloud.calls == 1
    assert cloud.total_tokens == 1_500_000


def test_deterministic_stages_are_not_counted_as_model_calls(tmp_path):
    store = _store(tmp_path)
    task_id = store.create_task("demo", "paper_course", "local", "qwen")
    _run(store, task_id, "ingest", "none", "", "pass", {})
    _run(store, task_id, "research", "local", "qwen", "pass", {"input_tokens": 5})

    rows = collect_usage(store)
    assert [(row.provider, row.model) for row in rows] == [("local", "qwen")]


def test_usage_can_be_filtered_by_project(tmp_path):
    store = _store(tmp_path)
    first = store.create_task("one", "paper_course", "local", "qwen")
    second = store.create_task("two", "paper_course", "local", "qwen")
    _run(store, first, "research", "local", "qwen", "pass", {"input_tokens": 10})
    _run(store, second, "research", "local", "qwen", "pass", {"input_tokens": 20})

    rows = collect_usage(store, project_id="one")
    assert sum(row.input_tokens for row in rows) == 10


def test_shipped_pricing_file_prices_cloud_and_excludes_local():
    policy = load_pricing(Path("config/pricing.yaml"))
    assert policy.currency == "USD"
    assert policy.models["deepseek-chat"].input == pytest.approx(0.27)
    assert "local" in policy.unmetered_providers


def test_pricing_math_and_unmetered_note(tmp_path):
    store = _store(tmp_path)
    task_id = store.create_task("demo", "paper_course", "local", "qwen")
    _run(store, task_id, "research", "local", "qwen", "pass", {"input_tokens": 100})
    _run(
        store,
        task_id,
        "generate",
        "deepseek",
        "deepseek-chat",
        "pass",
        {"input_tokens": 1_000_000, "output_tokens": 500_000},
    )

    rows = {(row.provider, row.model): row for row in collect_usage(store)}
    apply_pricing(list(rows.values()), load_pricing(Path("config/pricing.yaml")))

    cloud = rows[("deepseek", "deepseek-chat")]
    assert cloud.cost == pytest.approx(1.0 * 0.27 + 0.5 * 1.10)

    local = rows[("local", "qwen")]
    assert local.cost is None
    assert local.cost_note == UNMETERED_NOTE

    total, excluded = total_cost(list(rows.values()))
    assert total == pytest.approx(0.82)
    assert excluded == ["local/qwen"]


def test_unpriced_model_is_not_costed_as_zero():
    row = UsageRow(provider="deepseek", model="unknown-model", input_tokens=1000)
    apply_pricing([row], PricingPolicy(models={}))
    assert row.cost is None
    assert row.cost_note == UNPRICED_NOTE


def test_invalid_pricing_file_is_rejected(tmp_path):
    path = tmp_path / "pricing.yaml"
    path.write_text("models:\n  x:\n    input: 1\n    bogus: 2\n", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="invalid pricing file"):
        load_pricing(path)
