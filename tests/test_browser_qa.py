from pathlib import Path

import pytest

from content_studio import browser_qa
from content_studio.browser_qa import (
    BrowserQAResult,
    VisitResult,
    _compare_with_baseline,
    run_browser_qa,
)
from content_studio.validation import _browser_checks, _browser_result_checks

PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>测试课程</title></head>
<body><main><h1>测试标题</h1><article>正文</article></main></body></html>
"""


def _project(tmp_path: Path, html: str = PAGE) -> Path:
    root = tmp_path / "project"
    (root / "build" / "slides").mkdir(parents=True)
    (root / "build" / "slides" / "index.html").write_text(html, encoding="utf-8")
    return root


def _run(project: Path, **kwargs):
    result = run_browser_qa(
        project,
        pages=(("slides", "build/slides/index.html"),),
        viewports=(("desktop", 800, 600),),
        **kwargs,
    )
    if not result.ran:
        pytest.skip(result.reason)
    return result


def test_missing_build_reports_not_run(tmp_path):
    result = run_browser_qa(tmp_path / "empty")
    assert result.ran is False
    assert result.reason


def test_baseline_lifecycle(tmp_path):
    baseline = tmp_path / "baseline.png"
    current = tmp_path / "current.png"

    current.write_bytes(b"first")
    assert _compare_with_baseline(current, baseline) == "created"
    assert baseline.read_bytes() == b"first"

    assert _compare_with_baseline(current, baseline) == "same"

    current.write_bytes(b"second")
    assert _compare_with_baseline(current, baseline) == "changed"
    assert baseline.read_bytes() == b"first", "baseline must stay stable for review"


def test_rendered_page_passes_checks(tmp_path):
    project = _project(tmp_path)
    result = _run(project)

    assert len(result.visits) == 1
    visit = result.visits[0]
    assert visit.loaded is True
    assert visit.title == "测试课程"
    assert visit.h1 == "测试标题"
    assert visit.blocks >= 1
    assert visit.javascript_errors == []
    assert visit.broken_images == []
    assert Path(visit.screenshot).is_file()


def test_browser_checks_cover_default_viewports(tmp_path):
    reason = browser_qa.playwright_error()
    if reason:
        pytest.skip(reason)
    project = _project(tmp_path)
    checks = {check.check_id: check for check in _browser_checks(project, enabled=True)}
    if "browser_pages_load" not in checks:
        pytest.skip(checks["browser_visual_regression"].message)

    assert checks["browser_pages_load"].status == "pass"
    assert checks["browser_no_js_errors"].status == "pass"
    assert checks["browser_resources_loaded"].status == "pass"
    assert checks["browser_layout_no_overflow"].status == "pass"
    assert checks["browser_visual_regression"].status == "pass"
    assert "已建立基准截图" in checks["browser_visual_regression"].message
    assert (project / "internal" / "qa" / "baselines" / "slides-desktop.png").is_file()


def test_javascript_errors_and_overflow_are_reported(tmp_path):
    project = _project(
        tmp_path,
        """<!doctype html><html><head><meta charset="utf-8"><title>错误</title></head>
<body><main><h1>错误</h1><article><div style="width:3000px">宽</div></article>
<script>throw new Error("boom");</script></main></body></html>""",
    )
    result = _run(project)
    visit = result.visits[0]

    assert visit.loaded is True
    assert any("boom" in error for error in visit.javascript_errors)
    assert visit.overflow_px > 1

    checks = _browser_result_checks(
        BrowserQAResult(
            ran=True,
            visits=[_visit(console_errors=["Error: boom"], overflow_px=visit.overflow_px)],
        )
    )
    statuses = {check.check_id: check.status for check in checks}
    assert statuses["browser_no_js_errors"] == "fail"
    assert statuses["browser_layout_no_overflow"] == "fail"


def test_browser_checks_can_be_disabled():
    checks = _browser_checks(Path("unused"), enabled=False)
    assert [check.status for check in checks] == ["not_run"]
    assert checks[0].blocking is False


def test_unavailable_playwright_reports_not_run(tmp_path, monkeypatch):
    monkeypatch.setattr(browser_qa, "playwright_error", lambda: "Playwright 未安装")
    import content_studio.validation as validation

    checks = validation._browser_checks(tmp_path, enabled=True)
    assert [check.status for check in checks] == ["not_run"]
    assert "Playwright" in checks[0].message


def _visit(**overrides) -> VisitResult:
    values = {
        "page": "slides",
        "viewport": "desktop",
        "width": 800,
        "height": 600,
        "loaded": True,
    }
    values.update(overrides)
    return VisitResult(**values)


def test_checks_map_result_fields_to_gate_status():
    healthy = _browser_result_checks(BrowserQAResult(ran=True, visits=[_visit()]))
    assert {check.check_id: check.status for check in healthy}["browser_pages_load"] == "pass"

    failed = _browser_result_checks(
        BrowserQAResult(
            ran=True,
            visits=[
                _visit(
                    loaded=False,
                    console_errors=["TypeError: x"],
                    broken_images=["file:///missing.png"],
                    overflow_px=42,
                )
            ],
            visual_changes=["slides-desktop.png"],
        )
    )
    statuses = {check.check_id: check.status for check in failed}
    assert statuses["browser_pages_load"] == "fail"
    assert statuses["browser_no_js_errors"] == "fail"
    assert statuses["browser_resources_loaded"] == "fail"
    assert statuses["browser_layout_no_overflow"] == "fail"
    assert statuses["browser_visual_regression"] == "warn"
    assert all(check.blocking for check in failed if check.check_id != "browser_visual_regression")
