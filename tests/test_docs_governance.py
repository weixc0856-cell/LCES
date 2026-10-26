"""The documentation checker must fail on the conditions it claims to catch."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    path = ROOT / "scripts" / "check_docs.py"
    spec = importlib.util.spec_from_file_location("check_docs", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_repository_documents_pass_the_checker():
    errors, warnings = _load().check(ROOT)

    assert errors == []
    assert isinstance(warnings, list)


def _seed(root: Path, *, with_banner: bool) -> None:
    (root / "docs" / "design").mkdir(parents=True)
    (root / "schemas").mkdir(parents=True)
    for name in _load().REQUIRED:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# doc\n", encoding="utf-8")
    banner = "> 历史计划（已归档）\n" if with_banner else ""
    (root / "docs" / "design" / "motion-canvas-p9-plan.md").write_text(
        f"# plan\n{banner}", encoding="utf-8"
    )
    (root / "README.md").write_text(
        "# doc\n[broken](docs/does-not-exist.md)\n`lces not-a-real-command`\n", encoding="utf-8"
    )


def test_checker_reports_broken_links_commands_and_banners(tmp_path):
    _seed(tmp_path, with_banner=False)

    errors, warnings = _load().check(tmp_path)

    assert any("broken link" in item for item in errors)
    assert any("unknown lces command" in item for item in errors)
    assert any("archive banner" in item for item in errors)
    assert warnings == []


def test_checker_accepts_a_clean_tree(tmp_path):
    _seed(tmp_path, with_banner=True)
    (tmp_path / "README.md").write_text("# doc\n", encoding="utf-8")

    errors, _warnings = _load().check(tmp_path)

    assert errors == []
