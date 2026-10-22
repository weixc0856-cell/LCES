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
