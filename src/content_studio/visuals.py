"""Turn content blocks into visual specs and render them (Phase 2).

Content stays in :class:`PublicContent`; this module derives the visual
contract, renders it through the registry, and writes a manifest so every
rendered fragment can be traced back to its spec and renderer version.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from content_studio.models import (
    FigureBlock,
    PublicBlock,
    PublicContent,
    PublicSlide,
    TableBlock,
    VisualSpec,
)
from content_studio.renderers import RenderContext, RendererRegistry, default_registry
from content_studio.utils import write_json


@dataclass(frozen=True)
class RenderedVisual:
    slide_id: str
    block_index: int
    spec: VisualSpec
    html: str
    renderer: str
    renderer_version: str
    output_sha256: str


def visual_id(slide_id: str, block_index: int) -> str:
    return f"{slide_id}-block-{block_index:02d}"


def specs_for_slide(slide: PublicSlide) -> list[VisualSpec]:
    specs: list[VisualSpec] = []
    for index, block in enumerate(slide.body):
        spec = _spec_for_block(slide.slide_id, index, block)
        if spec is not None:
            specs.append(spec)
    return specs


def _spec_for_block(slide_id: str, index: int, block: PublicBlock) -> VisualSpec | None:
    identifier = visual_id(slide_id, index)
    if isinstance(block, TableBlock):
        return VisualSpec(
            visual_id=identifier,
            visual_type="table",
            title=block.caption,
            data={
                "caption": block.caption,
                "columns": list(block.columns),
                "rows": [list(row) for row in block.rows],
            },
        )
    if isinstance(block, FigureBlock):
        return VisualSpec(
            visual_id=identifier,
            visual_type="figure_image",
            title=block.caption,
            data={"path": block.path, "alt": block.alt, "caption": block.caption},
        )
    return None


def render_content_visuals(
    content: PublicContent,
    *,
    project_dir: Path | None = None,
    output_dir: Path | None = None,
    registry: RendererRegistry | None = None,
) -> list[RenderedVisual]:
    registry = registry or default_registry()
    context = RenderContext(project_dir=project_dir, output_dir=output_dir)
    rendered: list[RenderedVisual] = []
    for slide in content.slides:
        for index, block in enumerate(slide.body):
            spec = _spec_for_block(slide.slide_id, index, block)
            if spec is None:
                continue
            output = registry.render(spec, context)
            rendered.append(
                RenderedVisual(
                    slide_id=slide.slide_id,
                    block_index=index,
                    spec=spec,
                    html=output.html,
                    renderer=output.renderer,
                    renderer_version=output.renderer_version,
                    output_sha256=output.sha256,
                )
            )
    return rendered


def write_render_manifest(project_dir: Path, rendered: list[RenderedVisual]) -> Path:
    """Persist specs and renderer provenance under ``internal/qa``."""

    qa_dir = project_dir / "internal" / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        qa_dir / "visual_specs.json", [item.spec.model_dump(mode="json") for item in rendered]
    )
    entries = [
        {
            "visual_id": item.spec.visual_id,
            "visual_type": item.spec.visual_type,
            "schema_version": item.spec.schema_version,
            "slide_id": item.slide_id,
            "block_index": item.block_index,
            "renderer": item.renderer,
            "renderer_version": item.renderer_version,
            "output_sha256": item.output_sha256,
        }
        for item in rendered
    ]
    path = qa_dir / "render_manifest.json"
    write_json(path, entries)
    return path
