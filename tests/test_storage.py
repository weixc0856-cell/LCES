import json
import sqlite3

from content_studio.models import ApprovalRecord
from content_studio.storage import TaskStore


def test_task_lifecycle(tmp_path):
    store = TaskStore(tmp_path / "db.sqlite3")
    task_id = store.create_task("demo-course", "paper_course", "mock", "mock-deterministic")
    assert store.get_task(task_id)["status"] == "CREATED"

    run_id = store.start_stage(task_id, "research", "mock", "mock-deterministic")
    store.finish_stage(run_id, status="pass", usage={"input_tokens": 10})
    store.update_task(task_id, status="RESEARCHING", stage="research")

    task = store.get_task(task_id)
    assert task is not None and task["stage"] == "research"
    runs = store.stage_runs(task_id)
    assert len(runs) == 1 and runs[0]["usage_json"] == '{"input_tokens": 10}'


def test_task_listing_filters_projects(tmp_path):
    store = TaskStore(tmp_path / "db.sqlite3")
    store.create_task("a-course", "paper_course")
    store.create_task("b-course", "paper_course")
    assert len(store.list_tasks(project_id="a-course")) == 1
    assert len(store.list_tasks()) == 2


def test_approval_roundtrip(tmp_path):
    store = TaskStore(tmp_path / "db.sqlite3")
    record = ApprovalRecord(
        project_id="demo-course", version="v1", approved_by="reviewer", notes="checked"
    )
    store.save_approval(record)
    stored = store.get_approval("demo-course", "v1")
    assert stored is not None and stored["approved_by"] == "reviewer"


def test_events(tmp_path):
    store = TaskStore(tmp_path / "db.sqlite3")
    task_id = store.create_task("demo-course", "paper_course")
    store.log_event(task_id, "info", "started")
    events = store.events(task_id)
    assert events and events[0]["message"] == "started"


def test_task_records_run_id_input_and_config(tmp_path):
    store = TaskStore(tmp_path / "db.sqlite3")

    task_id = store.create_task(
        "demo-course",
        "paper_course",
        "mock",
        "mock-deterministic",
        run_id="run-fixed-001",
        input_sha256="a" * 64,
        config={"provider": "mock", "stages": ["ingest"]},
    )

    task = store.get_task(task_id)
    assert task is not None
    assert task["run_id"] == "run-fixed-001"
    assert task["input_sha256"] == "a" * 64
    assert json.loads(task["config_json"])["provider"] == "mock"


def test_create_task_generates_a_run_id_when_omitted(tmp_path):
    store = TaskStore(tmp_path / "db.sqlite3")
    task_id = store.create_task("demo-course", "paper_course")
    task = store.get_task(task_id)
    assert task is not None and len(task["run_id"]) == 32


def test_stage_run_records_error_class_retry_and_artifacts(tmp_path):
    store = TaskStore(tmp_path / "db.sqlite3")
    task_id = store.create_task("demo-course", "paper_course")
    run_id = store.start_stage(task_id, "research", "local", "qwen", retry_count=1)

    store.finish_stage(
        run_id,
        status="fail",
        error="ProviderError: timeout",
        error_class="provider",
        artifacts=["internal/evidence_ledger.csv"],
    )

    run = store.stage_runs(task_id)[0]
    assert run["retry_count"] == 1
    assert run["error_class"] == "provider"
    assert json.loads(run["artifacts_json"]) == ["internal/evidence_ledger.csv"]


def test_existing_database_gains_run_columns_without_losing_rows(tmp_path):
    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id TEXT NOT NULL,
            content_mode TEXT NOT NULL DEFAULT '',
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            stage TEXT NOT NULL DEFAULT '',
            error TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE stage_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id INTEGER NOT NULL,
            stage TEXT NOT NULL,
            status TEXT NOT NULL,
            provider TEXT NOT NULL DEFAULT '',
            model TEXT NOT NULL DEFAULT '',
            usage_json TEXT NOT NULL DEFAULT '{}',
            error TEXT NOT NULL DEFAULT '',
            started_at TEXT NOT NULL,
            finished_at TEXT
        );
        INSERT INTO tasks (project_id, status, created_at, updated_at)
            VALUES ('legacy-course', 'CREATED', '2026-01-01', '2026-01-01');
        """
    )
    conn.commit()
    conn.close()

    store = TaskStore(path)

    task = store.get_task(1)
    assert task is not None and task["project_id"] == "legacy-course"
    assert task["run_id"] == "" and task["config_json"] == "{}"
    run_id = store.start_stage(1, "ingest")
    store.finish_stage(run_id, status="pass", error_class="", artifacts=[])
    assert store.stage_runs(1)[0]["retry_count"] == 0
