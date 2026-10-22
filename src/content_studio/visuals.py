"""Turn content blocks into visual specs and render them (Phase 2).

Content stays in :class:`PublicContent`; this module derives the visual
contract, renders it through the registry, and writes a manifest so every
rendered fragment can be traced back to its spec and renderer version.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from content_studio.models import (
    AssetCheck,
    ChartBlock,
    DiagramBlock,
    FigureBlock,
    GraphBlock,
    PublicBlock,
    PublicContent,
    PublicSlide,
    TableBlock,
    VisualAsset,
    VisualSpec,
)
from content_studio.renderers import RenderContext, RendererRegistry, default_registry
from content_studio.utils import sha256_file, write_json


@dataclass(frozen=True)
class RenderedVisual:
    slide_id: str
    block_index: int
    spec: VisualSpec
    html: str
    renderer: str
    renderer_version: str
    output_sha256: str
    artifacts: tuple[Path, ...] = ()


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
    if isinstance(block, ChartBlock):
        return VisualSpec(
            visual_id=identifier,
            visual_type="data_chart",
            title=block.caption,
            data={
                "vega_lite": block.spec,
                "alt": block.alt,
                "caption": block.caption,
            },
        )
    if isinstance(block, DiagramBlock):
        return VisualSpec(
            visual_id=identifier,
            visual_type="diagram",
            title=block.caption,
            data={
                "mermaid": block.mermaid,
                "alt": block.alt,
                "caption": block.caption,
            },
        )
    if isinstance(block, GraphBlock):
        return VisualSpec(
            visual_id=identifier,
            visual_type="graph",
            title=block.caption,
            data={"dot": block.dot, "alt": block.alt, "caption": block.caption},
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
                    artifacts=output.artifacts,
                )
            )
    return rendered


def write_render_manifest(
    project_dir: Path,
    rendered: list[RenderedVisual],
    *,
    page_path: Path | None = None,
) -> Path:
    """Persist specs, renderer provenance, and the visual asset contracts."""

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
    write_json(
        qa_dir / "visual_assets.json",
        [
            asset.model_dump(mode="json")
            for asset in _asset_contracts(project_dir, rendered, page_path)
        ],
    )
    return path


_ASSET_TYPES = {
    "table": "table",
    "figure_image": "image",
    "custom_svg": "svg",
    "data_chart": "chart",
    "diagram": "diagram",
    "graph": "diagram",
}


def _asset_contracts(
    project_dir: Path, rendered: list[RenderedVisual], page_path: Path | None
) -> list[VisualAsset]:
    content_path = project_dir / "content" / "public_content.json"
    source_hash = sha256_file(content_path) if content_path.is_file() else ""
    page_hash = sha256_file(page_path) if page_path is not None and page_path.is_file() else ""
    page_relative = _relative(page_path, project_dir) if page_path is not None else None

    assets: list[VisualAsset] = []
    for item in rendered:
        output_paths: list[str] = []
        output_hashes: dict[str, str] = {}
        for artifact in item.artifacts:
            relative = _relative(artifact, project_dir)
            if relative is None:
                continue
            output_paths.append(relative)
            output_hashes[relative] = sha256_file(artifact)
        if not output_paths and page_relative is not None:
            output_paths.append(page_relative)
            output_hashes[page_relative] = page_hash

        spec_payload = item.spec.model_dump(mode="json")
        assets.append(
            VisualAsset(
                asset_id=item.spec.visual_id,
                asset_type=_ASSET_TYPES.get(item.spec.visual_type, "svg"),  # type: ignore[arg-type]
                source="content/public_content.json",
                renderer=item.renderer,
                renderer_version=item.renderer_version,
                parameters={
                    "visual_type": item.spec.visual_type,
                    "spec": spec_payload,
                    "spec_sha256": _sha256_text(json.dumps(spec_payload, sort_keys=True)),
                },
                output_paths=output_paths,
                output_hashes=output_hashes,
                status="rendered",
                qa_results=[
                    AssetCheck(
                        check_id="renderer_validation",
                        status="pass",
                        message="",
                    )
                ],
                source_hash=source_hash,
            )
        )
    return assets


def _relative(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
