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
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from content_studio.errors import ConfigurationError, RenderError, UnsupportedVisualType
from content_studio.models import VisualSpec


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


class Renderer(ABC):
    name: str = ""
    version: str = "1.0.0"
    visual_types: frozenset[str] = frozenset()

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


class RendererRegistry:
    """Dispatch a spec to the renderer registered for its ``visual_type``."""

    def __init__(self) -> None:
        self._by_type: dict[str, Renderer] = {}

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

    def resolve(self, visual_type: str) -> Renderer:
        try:
            return self._by_type[visual_type]
        except KeyError as exc:
            known = ", ".join(self.known_types()) or "none"
            raise UnsupportedVisualType(
                f"no renderer registered for visual_type '{visual_type}' (known: {known})"
            ) from exc

    def render(self, spec: VisualSpec, context: RenderContext | None = None) -> RenderOutput:
        renderer = self.resolve(spec.visual_type)
        if spec.renderer and spec.renderer != renderer.name:
            raise UnsupportedVisualType(
                f"visual '{spec.visual_id}' requests renderer '{spec.renderer}', "
                f"but visual_type '{spec.visual_type}' resolves to '{renderer.name}'"
            )
        html = renderer.render(spec, context or RenderContext())
        problems = renderer.validate(spec, html)
        if problems:
            raise RenderError("; ".join(problems))
        return RenderOutput(html=html, renderer=renderer.name, renderer_version=renderer.version)


def _string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise RenderError(f"{field_name} must be a non-empty list")
    return [str(item) for item in value]


def default_registry() -> RendererRegistry:
    registry = RendererRegistry()
    registry.register(TableRenderer())
    registry.register(FigureRenderer())
    return registry
