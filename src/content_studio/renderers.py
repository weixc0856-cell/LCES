"""Renderer registry and the renderers that back it (Phase 2).

Content models describe *what* to show; a :class:`VisualSpec` describes the
visual as structured data; a renderer turns that spec into an artifact. The
registry is the only place that maps ``visual_type`` to an implementation, so
an unknown type fails loudly instead of silently rendering nothing.

The HTML produced here must escape every value it interpolates: templates
insert it with ``| safe``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Literal
from xml.etree import ElementTree

from content_studio.errors import (
    ConfigurationError,
    RenderCancelled,
    RenderError,
    UnsupportedVisualType,
)
from content_studio.models import VisualSpec
from content_studio.paths import repository_root
from content_studio.utils import sha256_file

MAX_INLINE_SVG_BYTES = 2_000_000

# Custom or generated SVG is inlined into a public page, so anything active or
# remote is refused rather than sanitised in place.
_SVG_DANGEROUS = (
    (re.compile(r"<\s*script", re.IGNORECASE), "<script>"),
    (re.compile(r"<\s*foreignObject", re.IGNORECASE), "<foreignObject>"),
    (re.compile(r"<\s*(iframe|object|embed)\b", re.IGNORECASE), "<iframe>/<object>/<embed>"),
    (re.compile(r"javascript:", re.IGNORECASE), "javascript: URL"),
    (re.compile(r"(?<![\w-])on[a-z]+\s*=", re.IGNORECASE), "inline event handler"),
    (
        re.compile(r"(?:href|src)\s*=\s*[\"']\s*(?:https?:)?//", re.IGNORECASE),
        "external reference",
    ),
)


@dataclass(frozen=True)
class RenderContext:
    """Where a renderer may read assets from and write side artifacts to.

    ``publish`` is reserved for the production build path: a renderer may then
    write the artifacts a release consumes (for example
    ``build/media/course.mp4``). Standalone ``render-scene`` calls leave it
    false and keep writing under ``output_dir``.
    """

    project_dir: Path | None = None
    output_dir: Path | None = None
    publish: bool = False


@dataclass
class RenderOutput:
    html: str
    renderer: str
    renderer_version: str
    artifacts: tuple[Path, ...] = field(default_factory=tuple)
    build_id: str = ""
    manifest: Path | None = None
    status: Literal["completed"] = "completed"

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.html.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RenderResult:
    """A renderer's own report for a build.

    Renderers that embed HTML fragments can keep returning a plain string.
    A renderer that owns a multi-file build (frames, manifest, video) returns
    this instead, so the registry can carry the build id and manifest path
    without a second output channel. ``status`` is the *declared* terminal
    state; the registry refuses anything other than ``completed``.
    """

    status: Literal["completed", "cancelled", "failed"] = "completed"
    html: str = ""
    build_id: str = ""
    artifacts: tuple[Path, ...] = field(default_factory=tuple)
    manifest: Path | None = None
    message: str = ""


@dataclass(frozen=True)
class ResourceEstimate:
    """Rough cost of one render; 0 means "not measured", not "free"."""

    cpu_seconds: float = 0.0
    memory_mb: int = 0
    notes: str = ""


class Renderer(ABC):
    name: str = ""
    version: str = "1.0.0"
    visual_types: frozenset[str] = frozenset()

    def validate_input(self, spec: VisualSpec) -> list[str]:
        """Reject a spec before any rendering work starts."""

        return []

    def check_environment(self) -> list[str]:
        """Return missing tools or versions; empty means the renderer can run."""

        return []

    def environment_error_code(self) -> str:
        """Failure code used when ``check_environment`` is not empty.

        A renderer that refuses the whole host (for example an unsupported
        platform) overrides this so the caller sees the real reason.
        """

        return "environment_unavailable"

    def estimate_resources(self, spec: VisualSpec) -> ResourceEstimate:
        return ResourceEstimate()

    def cancel(self) -> None:
        """Best-effort cancellation hook; sync renderers are atomic."""

        return None

    def collect_outputs(self, spec: VisualSpec, context: RenderContext) -> list[Path]:
        return []

    def get_diagnostics(self) -> list[str]:
        return []

    @abstractmethod
    def render(self, spec: VisualSpec, context: RenderContext) -> str | RenderResult:
        """Return the rendered artifact; raise RenderError on failure."""

    @abstractmethod
    def validate(
        self, spec: VisualSpec, html: str, context: RenderContext | None = None
    ) -> list[str]:
        """Return problems with the spec or output; an empty list means valid."""


class TableRenderer(Renderer):
    name = "html.table"
    version = "1.0.0"
    visual_types = frozenset({"table"})

    def validate_input(self, spec: VisualSpec) -> list[str]:
        columns = spec.data.get("columns")
        rows = spec.data.get("rows")
        if not isinstance(columns, list) or not columns:
            return [f"visual '{spec.visual_id}': columns must be a non-empty list"]
        if not isinstance(rows, list) or not rows:
            return [f"visual '{spec.visual_id}': rows must be a non-empty list"]
        problems: list[str] = []
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, list) or len(row) != len(columns):
                problems.append(
                    f"visual '{spec.visual_id}': row {index} has the wrong number of cells"
                )
        return problems

    def estimate_resources(self, spec: VisualSpec) -> ResourceEstimate:
        return ResourceEstimate(cpu_seconds=0.1, memory_mb=32, notes="pure Python")

    def render(self, spec: VisualSpec, context: RenderContext) -> str:
        columns = _string_list(spec.data.get("columns"), "columns")
        rows = spec.data.get("rows")
        if not isinstance(rows, list) or not rows:
            raise RenderError(f"visual '{spec.visual_id}': rows must be a non-empty list")
        table_rows: list[list[str]] = []
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, list):
                raise RenderError(f"visual '{spec.visual_id}': row {index} is not a list")
            table_rows.append([escape(str(cell)) for cell in row])

        caption = str(spec.data.get("caption") or "")
        parts = ["<table>"]
        if caption:
            parts.append(f'<caption class="table-caption">{escape(caption)}</caption>')
        header = "".join(f'<th scope="col">{escape(column)}</th>' for column in columns)
        parts.append(f"<thead><tr>{header}</tr></thead>")
        body = "".join(
            "<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in table_rows
        )
        parts.append(f"<tbody>{body}</tbody>")
        parts.append("</table>")
        return "".join(parts)

    def validate(
        self, spec: VisualSpec, html: str, context: RenderContext | None = None
    ) -> list[str]:
        problems: list[str] = []
        columns = spec.data.get("columns")
        rows = spec.data.get("rows")
        if not isinstance(columns, list) or not columns:
            return [f"visual '{spec.visual_id}': columns must be a non-empty list"]
        if not isinstance(rows, list) or not rows:
            return [f"visual '{spec.visual_id}': rows must be a non-empty list"]
        for index, row in enumerate(rows, start=1):
            if not isinstance(row, list) or len(row) != len(columns):
                problems.append(
                    f"visual '{spec.visual_id}': row {index} has the wrong number of cells"
                )
        if "<table>" not in html:
            problems.append(f"visual '{spec.visual_id}': renderer produced no table element")
        return problems


class FigureRenderer(Renderer):
    name = "html.figure"
    version = "1.0.0"
    visual_types = frozenset({"figure_image"})

    def validate_input(self, spec: VisualSpec) -> list[str]:
        problems: list[str] = []
        if not str(spec.data.get("path") or ""):
            problems.append(f"visual '{spec.visual_id}': path is required")
        if not str(spec.data.get("alt") or ""):
            problems.append(f"visual '{spec.visual_id}': alt text is required")
        return problems

    def estimate_resources(self, spec: VisualSpec) -> ResourceEstimate:
        return ResourceEstimate(cpu_seconds=0.1, memory_mb=32, notes="static image reference")

    def render(self, spec: VisualSpec, context: RenderContext) -> str:
        path = str(spec.data.get("path") or "")
        alt = str(spec.data.get("alt") or "")
        if not path or not alt:
            raise RenderError(f"visual '{spec.visual_id}': path and alt are required")
        if context.project_dir is not None:
            candidate = context.project_dir / "content" / path
            if not candidate.is_file():
                raise RenderError(f"visual '{spec.visual_id}': missing asset {path}")
        parts = [
            "<figure>",
            f'<img src="{escape(path)}" alt="{escape(alt)}" loading="lazy">',
        ]
        caption = str(spec.data.get("caption") or "")
        if caption:
            parts.append(f'<figcaption class="figure-caption">{escape(caption)}</figcaption>')
        parts.append("</figure>")
        return "".join(parts)

    def validate(
        self, spec: VisualSpec, html: str, context: RenderContext | None = None
    ) -> list[str]:
        problems: list[str] = []
        if not str(spec.data.get("path") or ""):
            problems.append(f"visual '{spec.visual_id}': path is required")
        if not str(spec.data.get("alt") or ""):
            problems.append(f"visual '{spec.visual_id}': alt text is required")
        if "<img" not in html:
            problems.append(f"visual '{spec.visual_id}': renderer produced no image element")
        return problems


class CustomSvgRenderer(Renderer):
    """Inline a curated SVG file after structural and safety checks."""

    name = "svg.custom"
    version = "1.0.0"
    visual_types = frozenset({"custom_svg"})

    def validate_input(self, spec: VisualSpec) -> list[str]:
        problems: list[str] = []
        if not str(spec.data.get("path") or ""):
            problems.append(f"visual '{spec.visual_id}': path is required")
        if not str(spec.data.get("alt") or ""):
            problems.append(f"visual '{spec.visual_id}': alt text is required")
        return problems

    def estimate_resources(self, spec: VisualSpec) -> ResourceEstimate:
        return ResourceEstimate(cpu_seconds=0.2, memory_mb=64, notes="XML parse and inline")

    def render(self, spec: VisualSpec, context: RenderContext) -> str:
        relative = str(spec.data.get("path") or "")
        alt = str(spec.data.get("alt") or "")
        if not relative or not alt:
            raise RenderError(f"visual '{spec.visual_id}': path and alt are required")
        if context.project_dir is None:
            raise RenderError(f"visual '{spec.visual_id}': custom SVG needs a project directory")
        candidate = (context.project_dir / "content" / relative).resolve()
        content_root = (context.project_dir / "content").resolve()
        try:
            candidate.relative_to(content_root)
        except ValueError as exc:
            raise RenderError(
                f"visual '{spec.visual_id}': SVG must live under content/{relative}"
            ) from exc
        if not candidate.is_file():
            raise RenderError(f"visual '{spec.visual_id}': missing asset {relative}")
        if candidate.stat().st_size > MAX_INLINE_SVG_BYTES:
            raise RenderError(f"visual '{spec.visual_id}': SVG exceeds the size limit")
        svg = _strip_prolog(candidate.read_text(encoding="utf-8"))
        problems = svg_problems(svg, f"visual '{spec.visual_id}'")
        if problems:
            raise RenderError("; ".join(problems))
        return _figure(svg, alt, str(spec.data.get("caption") or ""), css_class="svg-visual")

    def validate(
        self, spec: VisualSpec, html: str, context: RenderContext | None = None
    ) -> list[str]:
        problems: list[str] = []
        if not str(spec.data.get("alt") or ""):
            problems.append(f"visual '{spec.visual_id}': alt text is required")
        if "<svg" not in html:
            problems.append(f"visual '{spec.visual_id}': renderer produced no SVG element")
        return problems


class VegaLiteRenderer(Renderer):
    """Render a Vega-Lite spec to static SVG with vl-convert (no Node.js)."""

    name = "vega_lite.chart"
    version = "1.0.0"
    visual_types = frozenset({"data_chart"})

    def validate_input(self, spec: VisualSpec) -> list[str]:
        problems: list[str] = []
        chart = spec.data.get("vega_lite")
        if not isinstance(chart, dict) or not chart:
            problems.append(f"visual '{spec.visual_id}': vega_lite spec must be an object")
        if not str(spec.data.get("alt") or ""):
            problems.append(f"visual '{spec.visual_id}': alt text is required")
        return problems

    def check_environment(self) -> list[str]:
        try:
            import vl_convert  # noqa: F401  # type: ignore[import-not-found]
        except ImportError:
            return ["vl-convert-python 未安装；运行 `uv sync --extra charts`"]
        return []

    def estimate_resources(self, spec: VisualSpec) -> ResourceEstimate:
        return ResourceEstimate(cpu_seconds=2.0, memory_mb=256, notes="vl-convert (V8)")

    def collect_outputs(self, spec: VisualSpec, context: RenderContext) -> list[Path]:
        if context.output_dir is None:
            return []
        artifact = context.output_dir / "visuals" / f"{spec.visual_id}.svg"
        return [artifact] if artifact.is_file() else []

    def render(self, spec: VisualSpec, context: RenderContext) -> str:
        try:
            import vl_convert  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RenderError(
                "vl-convert-python is not installed; run `uv sync --extra charts`"
            ) from exc

        chart = spec.data.get("vega_lite")
        alt = str(spec.data.get("alt") or "")
        if not isinstance(chart, dict) or not chart:
            raise RenderError(f"visual '{spec.visual_id}': vega_lite spec must be an object")
        if not alt:
            raise RenderError(f"visual '{spec.visual_id}': alt text is required")
        if context.output_dir is None:
            raise RenderError(
                f"visual '{spec.visual_id}': chart rendering needs an output directory"
            )
        try:
            svg = vl_convert.vegalite_to_svg(json.dumps(chart, ensure_ascii=False))
        except Exception as exc:  # vl-convert surfaces spec errors as exceptions
            raise RenderError(
                f"visual '{spec.visual_id}': Vega-Lite rendering failed: {exc}"
            ) from exc
        problems = svg_problems(svg, f"visual '{spec.visual_id}'")
        if problems:
            raise RenderError("; ".join(problems))

        artifacts_dir = context.output_dir / "visuals"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        artifact = artifacts_dir / f"{spec.visual_id}.svg"
        artifact.write_text(svg, encoding="utf-8", newline="\n")
        return _figure(
            svg,
            alt,
            str(spec.data.get("caption") or ""),
            css_class="data-chart",
        )

    def validate(
        self, spec: VisualSpec, html: str, context: RenderContext | None = None
    ) -> list[str]:
        problems: list[str] = []
        if not isinstance(spec.data.get("vega_lite"), dict):
            problems.append(f"visual '{spec.visual_id}': vega_lite spec is missing")
        if not str(spec.data.get("alt") or ""):
            problems.append(f"visual '{spec.visual_id}': alt text is required")
        if "<svg" not in html:
            problems.append(f"visual '{spec.visual_id}': renderer produced no SVG element")
        return problems


MERMAID_CONFIG: dict[str, object] = {
    "startOnLoad": False,
    "securityLevel": "strict",
    "theme": "neutral",
    "htmlLabels": False,
    "maxTextSize": 20_000,
    "maxEdges": 500,
    "flowchart": {"htmlLabels": False, "useMaxWidth": True},
}

_MERMAID_RENDER_JS = """
async ({code, id, config}) => {
  window.mermaid.initialize(config);
  const result = await window.mermaid.render(id, code);
  return result.svg;
}
"""


def mermaid_runtime_path() -> Path:
    return repository_root() / "vendor" / "mermaid" / "mermaid.min.js"


def mermaid_status() -> tuple[bool, str]:
    problem = _mermaid_runtime_problem()
    if problem:
        return False, problem
    version = "unknown"
    try:
        manifest = json.loads(
            (mermaid_runtime_path().parent / "manifest.json").read_text(encoding="utf-8")
        )
        version = str(manifest.get("version") or version)
    except ValueError:
        pass
    return True, f"vendored {version}（离线，sha256 已校验）"


def _mermaid_runtime_problem() -> str:
    runtime = mermaid_runtime_path()
    manifest_path = runtime.parent / "manifest.json"
    if not runtime.is_file() or not manifest_path.is_file():
        return f"Mermaid 运行时缺失: {runtime}"
    try:
        expected = json.loads(manifest_path.read_text(encoding="utf-8")).get("sha256")
    except ValueError:
        return "Mermaid manifest.json 无法解析"
    if not isinstance(expected, str) or not expected:
        return "Mermaid manifest.json 未记录 sha256"
    if sha256_file(runtime) != expected:
        return "Mermaid 运行时校验失败（sha256 不匹配）；按 vendor/mermaid/README.md 重新入库"
    return ""


@lru_cache(maxsize=1)
def _chromium_problem() -> str:
    try:
        from playwright.sync_api import Error as PlaywrightError  # type: ignore[import-not-found]
        from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
    except ImportError:
        return "Playwright 未安装；运行 `uv sync --extra browser`"
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            browser.close()
    except PlaywrightError as exc:
        return f"Chromium 无法启动；运行 `uv run playwright install chromium`: {exc}"
    return ""


class MermaidRenderer(Renderer):
    """Render Mermaid source to SVG with the vendored runtime (offline)."""

    name = "mermaid.diagram"
    version = "1.0.0"
    visual_types = frozenset({"diagram"})
    timeout_ms = 15_000
    max_source_chars = 20_000

    def validate_input(self, spec: VisualSpec) -> list[str]:
        problems: list[str] = []
        code = spec.data.get("mermaid")
        if not isinstance(code, str) or not code.strip():
            problems.append(f"visual '{spec.visual_id}': mermaid source is required")
        else:
            if len(code) > self.max_source_chars:
                problems.append(
                    f"visual '{spec.visual_id}': mermaid source exceeds "
                    f"{self.max_source_chars} characters"
                )
            if "%%{" in code:
                problems.append(
                    f"visual '{spec.visual_id}': init directives (%%{...}%%) are not allowed"
                )
            if re.search(r"(?im)^\s*click\s", code):
                problems.append(f"visual '{spec.visual_id}': click directives are not allowed")
        if not str(spec.data.get("alt") or ""):
            problems.append(f"visual '{spec.visual_id}': alt text is required")
        return problems

    def check_environment(self) -> list[str]:
        problems: list[str] = []
        runtime = _mermaid_runtime_problem()
        if runtime:
            problems.append(runtime)
        chromium = _chromium_problem()
        if chromium:
            problems.append(chromium)
        return problems

    def estimate_resources(self, spec: VisualSpec) -> ResourceEstimate:
        return ResourceEstimate(cpu_seconds=3.0, memory_mb=512, notes="Chromium + Mermaid")

    def collect_outputs(self, spec: VisualSpec, context: RenderContext) -> list[Path]:
        if context.output_dir is None:
            return []
        artifact = context.output_dir / "visuals" / f"{spec.visual_id}.svg"
        return [artifact] if artifact.is_file() else []

    def render(self, spec: VisualSpec, context: RenderContext) -> str:
        try:
            from playwright.sync_api import Error as PlaywrightError  # type: ignore[import-not-found]
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError  # type: ignore[import-not-found]
            from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - check_environment covers this
            raise RenderError("Playwright is not installed; run `uv sync --extra browser`") from exc

        code = str(spec.data.get("mermaid") or "")
        alt = str(spec.data.get("alt") or "")
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                try:
                    page = browser.new_context(offline=True).new_page()
                    page.set_default_timeout(self.timeout_ms)
                    page.set_content(
                        "<!doctype html><html><body><div id='lces-mermaid'></div></body></html>"
                    )
                    page.add_script_tag(path=str(mermaid_runtime_path()))
                    svg = page.evaluate(
                        _MERMAID_RENDER_JS,
                        {
                            "code": code,
                            "id": f"lces-{spec.visual_id}",
                            "config": MERMAID_CONFIG,
                        },
                    )
                finally:
                    browser.close()
        except PlaywrightTimeoutError as exc:
            raise RenderError(
                f"visual '{spec.visual_id}': Mermaid 渲染超时（{self.timeout_ms}ms）"
            ) from exc
        except PlaywrightError as exc:
            message = str(exc).strip().splitlines()
            detail = message[0] if message else exc.__class__.__name__
            raise RenderError(
                f"visual '{spec.visual_id}': Mermaid 渲染失败: {detail[:300]}"
            ) from exc

        if not isinstance(svg, str) or not svg.lstrip().startswith("<svg"):
            raise RenderError(f"visual '{spec.visual_id}': Mermaid 未返回 SVG")
        problems = svg_problems(svg, f"visual '{spec.visual_id}'")
        if problems:
            raise RenderError("; ".join(problems))

        if context.output_dir is not None:
            artifacts = context.output_dir / "visuals"
            artifacts.mkdir(parents=True, exist_ok=True)
            (artifacts / f"{spec.visual_id}.svg").write_text(svg, encoding="utf-8", newline="\n")
        return _figure(
            svg,
            alt,
            str(spec.data.get("caption") or ""),
            css_class="mermaid-diagram",
        )

    def validate(
        self, spec: VisualSpec, html: str, context: RenderContext | None = None
    ) -> list[str]:
        problems: list[str] = []
        if "<svg" not in html:
            problems.append(f"visual '{spec.visual_id}': renderer produced no SVG element")
        if "foreignObject" in html:
            problems.append(f"visual '{spec.visual_id}': SVG contains foreignObject HTML labels")
        return problems


GRAPHVIZ_MIN_VERSION = (2, 40)


def graphviz_dot_path() -> str | None:
    """Controlled executable path: ``LCES_DOT_BIN`` or ``dot`` on PATH."""

    override = os.environ.get("LCES_DOT_BIN", "").strip()
    if override:
        return override if Path(override).is_file() else None
    return shutil.which("dot")


def graphviz_status() -> tuple[bool, str]:
    binary = graphviz_dot_path()
    if binary is None:
        return False, (
            "未安装 Graphviz (dot)；固定版本安装示例："
            "winget install --id Graphviz.Graphviz -e --version 16.1.0"
        )
    try:
        completed = subprocess.run(
            [binary, "-V"], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"无法运行 dot: {exc.__class__.__name__}"
    output = (completed.stderr or completed.stdout or "").strip()
    match = re.search(r"graphviz version (\d+\.\d+(?:\.\d+)?)", output)
    if completed.returncode != 0 or match is None:
        return False, f"dot 版本无法识别: {output[:120] or completed.returncode}"
    full = match.group(1)
    parts = tuple(int(part) for part in full.split("."))
    if parts[:2] < GRAPHVIZ_MIN_VERSION:
        return False, (
            f"Graphviz {full} 过低；需要 >= {GRAPHVIZ_MIN_VERSION[0]}.{GRAPHVIZ_MIN_VERSION[1]}"
        )
    return True, f"{full} ({binary})"


class GraphvizRenderer(Renderer):
    """Render a DOT graph to SVG with a pinned, externally installed Graphviz."""

    name = "graphviz.dot"
    version = "1.0.0"
    visual_types = frozenset({"graph"})
    timeout_seconds = 15
    max_source_chars = 20_000

    def validate_input(self, spec: VisualSpec) -> list[str]:
        problems: list[str] = []
        source = spec.data.get("dot")
        if not isinstance(source, str) or not source.strip():
            problems.append(f"visual '{spec.visual_id}': dot source is required")
        else:
            if len(source) > self.max_source_chars:
                problems.append(
                    f"visual '{spec.visual_id}': dot source exceeds "
                    f"{self.max_source_chars} characters"
                )
            if re.search(r"(?i)<\s*(script|iframe|object|embed)\b", source):
                problems.append(f"visual '{spec.visual_id}': dot source contains active HTML")
            if re.search(r"(?<![\w-])on[a-z]+\s*=", source, re.IGNORECASE):
                problems.append(f"visual '{spec.visual_id}': dot source contains event handlers")
        if not str(spec.data.get("alt") or ""):
            problems.append(f"visual '{spec.visual_id}': alt text is required")
        return problems

    def check_environment(self) -> list[str]:
        available, message = graphviz_status()
        return [] if available else [message]

    def estimate_resources(self, spec: VisualSpec) -> ResourceEstimate:
        return ResourceEstimate(cpu_seconds=1.0, memory_mb=256, notes="Graphviz dot")

    def collect_outputs(self, spec: VisualSpec, context: RenderContext) -> list[Path]:
        if context.output_dir is None:
            return []
        artifact = context.output_dir / "visuals" / f"{spec.visual_id}.svg"
        return [artifact] if artifact.is_file() else []

    def render(self, spec: VisualSpec, context: RenderContext) -> str:
        binary = graphviz_dot_path()
        if binary is None:
            raise RenderError("Graphviz dot is not installed")
        source = str(spec.data.get("dot") or "")
        alt = str(spec.data.get("alt") or "")
        try:
            completed = subprocess.run(
                [binary, "-Tsvg"],
                input=source,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RenderError(
                f"visual '{spec.visual_id}': Graphviz 渲染超时（{self.timeout_seconds}s）"
            ) from exc
        except OSError as exc:
            raise RenderError(f"visual '{spec.visual_id}': 无法运行 dot: {exc}") from exc

        if completed.returncode != 0:
            detail = (completed.stderr or "").strip().splitlines()
            message = detail[-1] if detail else f"exit code {completed.returncode}"
            raise RenderError(f"visual '{spec.visual_id}': Graphviz 渲染失败: {message[:300]}")
        svg = _strip_prolog(completed.stdout)
        if not svg.startswith("<svg"):
            raise RenderError(f"visual '{spec.visual_id}': Graphviz 未返回 SVG")
        problems = svg_problems(svg, f"visual '{spec.visual_id}'")
        if problems:
            raise RenderError("; ".join(problems))

        if context.output_dir is not None:
            artifacts = context.output_dir / "visuals"
            artifacts.mkdir(parents=True, exist_ok=True)
            (artifacts / f"{spec.visual_id}.svg").write_text(svg, encoding="utf-8", newline="\n")
        return _figure(
            svg,
            alt,
            str(spec.data.get("caption") or ""),
            css_class="graphviz-diagram",
        )

    def validate(
        self, spec: VisualSpec, html: str, context: RenderContext | None = None
    ) -> list[str]:
        if "<svg" not in html:
            return [f"visual '{spec.visual_id}': renderer produced no SVG element"]
        return []


def svg_problems(svg: str, label: str) -> list[str]:
    """Structural and safety checks shared by every SVG-producing renderer."""

    problems: list[str] = []
    if len(svg.encode("utf-8")) > MAX_INLINE_SVG_BYTES:
        problems.append(f"{label}: SVG exceeds the inline size limit")
    try:
        root = ElementTree.fromstring(svg)
    except ElementTree.ParseError as exc:
        return [f"{label}: SVG is not well-formed XML ({exc})"]
    if not root.tag.endswith("svg"):
        problems.append(f"{label}: root element is not <svg>")
    for pattern, description in _SVG_DANGEROUS:
        if pattern.search(svg):
            problems.append(f"{label}: SVG contains a forbidden {description}")
    return problems


def _strip_prolog(svg: str) -> str:
    """Drop XML declaration, doctype, and leading comments before ``<svg>``.

    Graphviz emits a two-line DOCTYPE and a "Generated by graphviz" comment
    before the root element; both are invalid once the SVG is inlined.
    """

    stripped = svg.lstrip()
    while True:
        if stripped.startswith("<?"):
            end = stripped.find("?>")
            if end == -1:
                break
            stripped = stripped[end + 2 :].lstrip()
        elif stripped.startswith("<!--"):
            end = stripped.find("-->")
            if end == -1:
                break
            stripped = stripped[end + 3 :].lstrip()
        elif stripped.startswith("<!DOCTYPE"):
            end = stripped.find(">")
            if end == -1:
                break
            stripped = stripped[end + 1 :].lstrip()
        else:
            break
    return stripped


def _figure(svg: str, alt: str, caption: str, *, css_class: str) -> str:
    root_tag = svg.split(">", 1)[0]
    attributes: list[str] = []
    # Keep a renderer's own role (Mermaid marks graphics-document), but never
    # ship an unlabelled graphic.
    if "aria-label=" not in root_tag:
        attributes.append(f'aria-label="{escape(alt)}"')
    if "role=" not in root_tag:
        attributes.append('role="img"')
    # Charts often carry a fixed pixel width; without this a narrow viewport
    # overflows. Inline styles win over the page stylesheet.
    if "style=" not in root_tag:
        attributes.append('style="max-width:100%;height:auto"')
    labelled = svg
    if attributes:
        labelled = svg.replace("<svg", "<svg " + " ".join(attributes), 1)
    parts = [f'<figure class="{css_class}">', labelled]
    if caption:
        parts.append(f'<figcaption class="figure-caption">{escape(caption)}</figcaption>')
    parts.append("</figure>")
    return "".join(parts)


def inline_svg_figure(
    svg: str, alt: str, caption: str = "", *, css_class: str = "figure-svg"
) -> str:
    """Sanitise an authored SVG and wrap it in a labelled ``<figure>``.

    Raises:
        RenderError: the SVG is malformed, too large, or contains active
            content. The course build refuses it rather than sanitising it
            in place.
    """

    cleaned = _strip_prolog(svg)
    problems = svg_problems(cleaned, "inline figure")
    if problems:
        raise RenderError("; ".join(problems), code="invalid_input", stage="input")
    return _figure(cleaned, alt, caption, css_class=css_class)


class RendererRegistry:
    """Dispatch a spec to the renderer registered for its ``visual_type``.

    Routing is deny-by-default: an unregistered type, an explicit renderer
    mismatch, a failed environment check, or invalid input stops the call
    before any rendering work starts. Failures are kept in ``diagnostics()``.
    """

    def __init__(self) -> None:
        self._by_type: dict[str, Renderer] = {}
        self._diagnostics: list[str] = []

    def register(self, renderer: Renderer) -> None:
        if not renderer.visual_types:
            raise ConfigurationError(f"renderer '{renderer.name}' declares no visual_types")
        for visual_type in renderer.visual_types:
            if visual_type in self._by_type:
                raise ConfigurationError(
                    f"visual_type '{visual_type}' already registered to "
                    f"'{self._by_type[visual_type].name}'"
                )
            self._by_type[visual_type] = renderer

    def known_types(self) -> list[str]:
        return sorted(self._by_type)

    def diagnostics(self) -> list[str]:
        return list(self._diagnostics)

    def estimate(self, spec: VisualSpec) -> ResourceEstimate:
        return self.resolve(spec.visual_type).estimate_resources(spec)

    def check_environment(self, visual_type: str) -> list[str]:
        return self.resolve(visual_type).check_environment()

    def resolve(self, visual_type: str) -> Renderer:
        try:
            return self._by_type[visual_type]
        except KeyError as exc:
            known = ", ".join(self.known_types()) or "none"
            raise UnsupportedVisualType(
                f"no renderer registered for visual_type '{visual_type}' (known: {known})"
            ) from exc

    def render(self, spec: VisualSpec, context: RenderContext | None = None) -> RenderOutput:
        self._diagnostics = []
        renderer = self.resolve(spec.visual_type)
        if spec.renderer and spec.renderer != renderer.name:
            raise UnsupportedVisualType(
                f"visual '{spec.visual_id}' requests renderer '{spec.renderer}', "
                f"but visual_type '{spec.visual_type}' resolves to '{renderer.name}'"
            )

        environment = renderer.check_environment()
        if environment:
            self._fail(spec, renderer, "environment", environment)
            raise RenderError(
                f"renderer '{renderer.name}' is not ready: " + "; ".join(environment),
                code=renderer.environment_error_code(),
                stage="environment",
            )

        input_problems = renderer.validate_input(spec)
        if input_problems:
            self._fail(spec, renderer, "input", input_problems)
            raise RenderError("; ".join(input_problems), code="invalid_input", stage="input")

        render_context = context or RenderContext()
        try:
            outcome = renderer.render(spec, render_context)
        except RenderError as exc:
            self._fail(spec, renderer, "render", [str(exc)])
            raise

        if isinstance(outcome, RenderResult):
            if outcome.status == "cancelled":
                self._fail(spec, renderer, "render", [outcome.message or "cancelled"])
                raise RenderCancelled(outcome.message or f"visual '{spec.visual_id}' was cancelled")
            if outcome.status != "completed":
                self._fail(spec, renderer, "render", [outcome.message or outcome.status])
                raise RenderError(
                    outcome.message or f"visual '{spec.visual_id}' did not complete",
                    stage="render",
                )
            html = outcome.html
            artifacts = list(outcome.artifacts)
            build_id = outcome.build_id
            manifest = outcome.manifest
        else:
            html = outcome
            artifacts = []
            build_id = ""
            manifest = None

        problems = renderer.validate(spec, html, render_context)
        if problems:
            self._fail(spec, renderer, "output", problems)
            raise RenderError("; ".join(problems), code="output_corrupt", stage="output")

        if not artifacts:
            artifacts = renderer.collect_outputs(spec, render_context)
        return RenderOutput(
            html=html,
            renderer=renderer.name,
            renderer_version=renderer.version,
            artifacts=tuple(artifacts),
            build_id=build_id,
            manifest=manifest,
        )

    def _fail(self, spec: VisualSpec, renderer: Renderer, stage: str, problems: list[str]) -> None:
        detail = "; ".join(problems)
        self._diagnostics.append(
            f"visual '{spec.visual_id}' failed at {stage} with '{renderer.name}': {detail}"
        )


def _string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise RenderError(f"{field_name} must be a non-empty list")
    return [str(item) for item in value]


def default_registry() -> RendererRegistry:
    # Local import: motion_canvas imports this module for the Renderer
    # protocol, so importing it at module load would be circular.
    from content_studio.motion_canvas import MotionCanvasRenderer

    registry = RendererRegistry()
    registry.register(TableRenderer())
    registry.register(FigureRenderer())
    registry.register(CustomSvgRenderer())
    registry.register(VegaLiteRenderer())
    registry.register(MermaidRenderer())
    registry.register(GraphvizRenderer())
    registry.register(MotionCanvasRenderer())
    return registry
