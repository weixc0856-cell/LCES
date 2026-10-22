import pytest

from content_studio.errors import ConfigurationError, IngestionError
from content_studio.ingestion import ingest_project, load_registry, load_source_text
from content_studio.models import ProjectConfig
from content_studio.paths import ensure_project_layout
from content_studio.settings import Settings


def _settings(tmp_path) -> Settings:
    return Settings(_env_file=None, provider="mock", database_path=tmp_path / "db.sqlite3")


def _project(tmp_path):
    root = ensure_project_layout(tmp_path / "project")
    (root / "input").mkdir(exist_ok=True)
    return root


def test_markdown_ingestion_records_hash_and_text(tmp_path):
    root = _project(tmp_path)
    (root / "input" / "sample.md").write_text("# 标题\n\n这是正文。\n", encoding="utf-8")
    config = ProjectConfig(project_id="demo-course", title="Demo", input_paths=["input/sample.md"])

    registry = ingest_project(root, config, _settings(tmp_path))

    assert len(registry.sources) == 1
    source = registry.sources[0]
    assert source.source_id == "source-001"
    assert source.kind == "markdown"
    assert source.sha256 and len(source.sha256) == 64
    assert (root / "internal" / "source_registry.json").is_file()
    assert "这是正文" in load_source_text(root, "source-001")
    assert load_registry(root) is not None


def test_html_ingestion_drops_script_content(tmp_path):
    root = _project(tmp_path)
    (root / "input" / "page.html").write_text(
        "<html><head><title>页面标题</title><script>secret()</script></head>"
        "<body><p>可见正文</p></body></html>",
        encoding="utf-8",
    )
    config = ProjectConfig(project_id="demo-course", title="Demo", input_paths=["input/page.html"])

    registry = ingest_project(root, config, _settings(tmp_path))

    text = load_source_text(root, registry.sources[0].source_id)
    assert registry.sources[0].title == "页面标题"
    assert "可见正文" in text
    assert "secret()" not in text


def test_second_ingest_assigns_next_id(tmp_path):
    root = _project(tmp_path)
    (root / "input" / "one.md").write_text("one", encoding="utf-8")
    (root / "input" / "two.txt").write_text("two", encoding="utf-8")
    config = ProjectConfig(project_id="demo-course", title="Demo", input_paths=["input/one.md"])
    ingest_project(root, config, _settings(tmp_path))

    config2 = config.model_copy(update={"input_paths": ["input/two.txt"]})
    registry = ingest_project(root, config2, _settings(tmp_path))

    assert [source.source_id for source in registry.sources] == ["source-001", "source-002"]


def test_unsupported_suffix_raises(tmp_path):
    root = _project(tmp_path)
    (root / "input" / "data.bin").write_bytes(b"\x00\x01")
    config = ProjectConfig(project_id="demo-course", title="Demo", input_paths=["input/data.bin"])

    with pytest.raises(IngestionError):
        ingest_project(root, config, _settings(tmp_path))


def test_external_path_blocked_by_default(tmp_path):
    root = _project(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("外部资料", encoding="utf-8")
    config = ProjectConfig(project_id="demo-course", title="Demo")

    with pytest.raises(ConfigurationError):
        ingest_project(root, config, _settings(tmp_path), extra_paths=[str(outside)])

    registry = ingest_project(
        root, config, _settings(tmp_path), extra_paths=[str(outside)], allow_external=True
    )
    assert registry.sources[0].kind == "markdown"
