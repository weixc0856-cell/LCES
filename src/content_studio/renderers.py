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
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from xml.etree import ElementTree

from content_studio.errors import ConfigurationError, RenderError, UnsupportedVisualType
from content_studio.models import VisualSpec

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
    """Where a renderer may read assets from and write side artifacts to."""

    project_dir: Path | None = None
    output_dir: Path | None = None


@dataclass
class RenderOutput:
    html: str
    renderer: str
    renderer_version: str
    artifacts: tuple[Path, ...] = field(default_factory=tuple)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.html.encode("utf-8")).hexdigest()


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
    def render(self, spec: VisualSpec, context: RenderContext) -> str:
        """Return the rendered artifact; raise RenderError on failure."""

    @abstractmethod
    def validate(self, spec: VisualSpec, html: str) -> list[str]:
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

    def validate(self, spec: VisualSpec, html: str) -> list[str]:
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

    def validate(self, spec: VisualSpec, html: str) -> list[str]:
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

    def validate(self, spec: VisualSpec, html: str) -> list[str]:
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

    def validate(self, spec: VisualSpec, html: str) -> list[str]:
        problems: list[str] = []
        if not isinstance(spec.data.get("vega_lite"), dict):
            problems.append(f"visual '{spec.visual_id}': vega_lite spec is missing")
        if not str(spec.data.get("alt") or ""):
            problems.append(f"visual '{spec.visual_id}': alt text is required")
        if "<svg" not in html:
            problems.append(f"visual '{spec.visual_id}': renderer produced no SVG element")
        return problems


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
    """Drop an XML declaration or doctype; it is invalid once inlined."""

    stripped = svg.lstrip()
    while stripped.startswith("<?") or stripped.startswith("<!DOCTYPE"):
        end = stripped.find(">")
        if end == -1:
            break
        stripped = stripped[end + 1 :].lstrip()
    return stripped


def _figure(svg: str, alt: str, caption: str, *, css_class: str) -> str:
    root_tag = svg.split(">", 1)[0]
    attributes: list[str] = []
    if "role=" not in root_tag:
        attributes.append(f'role="img" aria-label="{escape(alt)}"')
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
            raise RenderError(f"renderer '{renderer.name}' is not ready: " + "; ".join(environment))

        input_problems = renderer.validate_input(spec)
        if input_problems:
            self._fail(spec, renderer, "input", input_problems)
            raise RenderError("; ".join(input_problems))

        render_context = context or RenderContext()
        try:
            html = renderer.render(spec, render_context)
        except RenderError as exc:
            self._fail(spec, renderer, "render", [str(exc)])
            raise

        problems = renderer.validate(spec, html)
        if problems:
            self._fail(spec, renderer, "output", problems)
            raise RenderError("; ".join(problems))

        artifacts = renderer.collect_outputs(spec, render_context)
        return RenderOutput(
            html=html,
            renderer=renderer.name,
            renderer_version=renderer.version,
            artifacts=tuple(artifacts),
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
    registry = RendererRegistry()
    registry.register(TableRenderer())
    registry.register(FigureRenderer())
    registry.register(CustomSvgRenderer())
    registry.register(VegaLiteRenderer())
    return registry
