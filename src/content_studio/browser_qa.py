"""Browser-level QA for built HTML (Phase 1: Playwright).

The checks here answer a different question from the template tests: does the
*rendered* page load, run without JavaScript errors, resolve its local
resources, and keep its layout inside each viewport? Screenshots are stored as
baselines so later runs can flag visual changes for human review.

Playwright is an optional extra; when it is not installed the caller must
report NOT_RUN, never PASS.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_VIEWPORTS: tuple[tuple[str, int, int], ...] = (
    ("desktop", 1280, 800),
    ("hd_16_9", 1920, 1080),
    ("qhd_16_9", 2560, 1440),
    ("uhd_16_9", 3840, 2160),
    ("mobile", 390, 844),
)

DEFAULT_PAGES: tuple[tuple[str, str], ...] = (
    ("slides", "build/slides/index.html"),
    ("reading", "build/reading_edition.html"),
)

# A one-pixel rounding difference between scrollWidth and clientWidth is not a
# layout defect; anything larger is treated as horizontal overflow.
OVERFLOW_TOLERANCE_PX = 1

_METRICS_JS = """() => {
  const root = document.documentElement;
  const h1 = document.querySelector('h1');
  return {
    title: document.title || '',
    h1: h1 ? (h1.textContent || '').trim() : '',
    blocks: document.querySelectorAll('article, section').length,
    images: Array.from(document.images).length,
    brokenImages: Array.from(document.images)
      .filter((img) => !img.complete || img.naturalWidth === 0)
      .map((img) => img.currentSrc || img.src),
    overflowPx: Math.max(0, root.scrollWidth - root.clientWidth),
  };
}"""


@dataclass
class VisitResult:
    page: str
    viewport: str
    width: int
    height: int
    loaded: bool = False
    title: str = ""
    h1: str = ""
    blocks: int = 0
    broken_images: list[str] = field(default_factory=list)
    failed_requests: list[str] = field(default_factory=list)
    console_errors: list[str] = field(default_factory=list)
    page_errors: list[str] = field(default_factory=list)
    overflow_px: int = 0
    screenshot: str = ""

    @property
    def javascript_errors(self) -> list[str]:
        return [*self.console_errors, *self.page_errors]


@dataclass
class BrowserQAResult:
    ran: bool
    reason: str = ""
    visits: list[VisitResult] = field(default_factory=list)
    baselines_created: list[str] = field(default_factory=list)
    visual_changes: list[str] = field(default_factory=list)
    error: str = ""


def playwright_error() -> str:
    """Return why browser QA cannot run here, or an empty string if it can."""

    try:
        import playwright.sync_api  # type: ignore[import-not-found]  # noqa: F401
    except ImportError:
        return (
            "Playwright 未安装；执行 `uv sync --extra browser` 后再运行 "
            "`uv run playwright install chromium`"
        )
    return ""


def run_browser_qa(
    project_dir: Path,
    *,
    viewports: tuple[tuple[str, int, int], ...] = DEFAULT_VIEWPORTS,
    pages: tuple[tuple[str, str], ...] = DEFAULT_PAGES,
    screenshots_dir: Path | None = None,
    baselines_dir: Path | None = None,
) -> BrowserQAResult:
    """Render every built page in Chromium and collect QA evidence."""

    reason = playwright_error()
    if reason:
        return BrowserQAResult(ran=False, reason=reason)

    project_dir = project_dir.resolve()
    available = [(name, project_dir / relative) for name, relative in pages]
    available = [(name, path) for name, path in available if path.is_file()]
    if not available:
        return BrowserQAResult(ran=False, reason="没有可检查的构建 HTML；先运行 `lces build`")

    screenshots_dir = screenshots_dir or project_dir / "internal" / "qa" / "screenshots"
    baselines_dir = baselines_dir or project_dir / "internal" / "qa" / "baselines"
    screenshots_dir.mkdir(parents=True, exist_ok=True)

    try:
        from playwright.sync_api import Error as PlaywrightError  # type: ignore[import-not-found]  # type: ignore[import-not-found]
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - playwright_error already checked
        return BrowserQAResult(ran=False, reason=str(exc))

    result = BrowserQAResult(ran=True)
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch()
            except PlaywrightError as exc:
                return BrowserQAResult(
                    ran=False,
                    reason=(
                        "Chromium 无法启动（通常是未安装）："
                        f"{exc.__class__.__name__}; 运行 `uv run playwright install chromium`"
                    ),
                )
            try:
                for page_name, html_path in available:
                    for viewport_name, width, height in viewports:
                        visit = _visit(
                            browser,
                            page_name,
                            html_path,
                            viewport_name,
                            width,
                            height,
                            screenshots_dir,
                        )
                        result.visits.append(visit)
                        if not visit.screenshot:
                            continue
                        state = _compare_with_baseline(
                            Path(visit.screenshot), baselines_dir / Path(visit.screenshot).name
                        )
                        if state == "created":
                            result.baselines_created.append(Path(visit.screenshot).name)
                        elif state == "changed":
                            result.visual_changes.append(Path(visit.screenshot).name)
            finally:
                browser.close()
    except PlaywrightError as exc:  # pragma: no cover - environment failure
        return BrowserQAResult(ran=False, reason=f"Playwright 运行失败: {exc}", error=str(exc))
    return result


def _visit(
    browser,
    page_name: str,
    html_path: Path,
    viewport_name: str,
    width: int,
    height: int,
    screenshots_dir: Path,
) -> VisitResult:
    from playwright.sync_api import Error as PlaywrightError  # type: ignore[import-not-found]

    screenshot_path = screenshots_dir / f"{page_name}-{viewport_name}.png"
    visit = VisitResult(
        page=page_name,
        viewport=viewport_name,
        width=width,
        height=height,
        screenshot=str(screenshot_path),
    )
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()
    console_errors: list[str] = []
    page_errors: list[str] = []
    failed_requests: list[str] = []

    def on_console(message) -> None:
        if message.type == "error":
            console_errors.append(message.text)

    def on_page_error(error) -> None:
        page_errors.append(str(error))

    def on_request_failed(request) -> None:
        failed_requests.append(f"{request.url} ({request.failure})")

    page.on("console", on_console)
    page.on("pageerror", on_page_error)
    page.on("requestfailed", on_request_failed)

    try:
        page.goto(html_path.as_uri(), wait_until="load", timeout=15_000)
        page.wait_for_timeout(150)  # let async layout settle before measuring
        visit.loaded = True
        metrics = page.evaluate(_METRICS_JS)
        visit.title = str(metrics.get("title", ""))
        visit.h1 = str(metrics.get("h1", ""))
        visit.blocks = int(metrics.get("blocks", 0))
        visit.broken_images = [str(item) for item in metrics.get("brokenImages", [])]
        visit.overflow_px = int(metrics.get("overflowPx", 0))
        page.screenshot(path=visit.screenshot, full_page=True)
    except PlaywrightError as exc:
        visit.page_errors.append(f"{exc.__class__.__name__}: {exc}")
        visit.screenshot = ""
    finally:
        visit.console_errors = console_errors
        visit.page_errors = [*visit.page_errors, *page_errors]
        visit.failed_requests = failed_requests
        context.close()
    return visit


def _compare_with_baseline(current: Path, baseline: Path) -> str:
    """Return ``created``, ``same`` or ``changed`` and keep the baseline stable."""

    if not current.is_file():
        return "missing"
    if not baseline.is_file():
        baseline.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(current, baseline)
        return "created"
    return "same" if baseline.read_bytes() == current.read_bytes() else "changed"
