"""HTML rendering from public-only models.

The renderer only receives ``PublicContent`` / ``ReadingEdition``. Speaker
scripts are never accepted here, by construction.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from content_studio.errors import RenderError
from content_studio.latex_render import LatexRenderError, render_latex
from content_studio.models import (
    AnimationBlock,
    ChartBlock,
    FormulaBlock,
    PublicContent,
    ReadingEdition,
    SvgBlock,
)
from content_studio.paths import BUILD_MARKER, require_inside, symlinks_in_tree
from content_studio.renderers import RendererRegistry, inline_svg_figure
from content_studio.scenes import (
    build_scene_inputs,
    derive_deck_scenes,
    scene_payload,
    write_generated_plan,
    write_scene_contracts,
)
from content_studio.units import write_materialized_course
from content_studio.utils import utc_now_iso, write_json_atomic, write_text_atomic
from content_studio.visuals import (
    RenderedVisual,
    render_content_visuals,
    verify_build_assets,
    write_render_manifest,
)


def _environment(template_dir: Path) -> Environment:
    if not template_dir.is_dir():
        raise FileNotFoundError(f"template directory not found: {template_dir}")
    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        # Only HTML templates are rendered here; always escape. select_autoescape
        # would disable escaping because the filenames end in .j2.
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _copy_charts(project_dir: Path, output_dir: Path) -> None:
    """Copy authored charts, refusing to follow links out of the project.

    ``copytree`` follows symlinks by default, so one link in ``content/charts``
    would pull a file from anywhere on the host into the build and, from there,
    into the release staging tree.
    """

    charts = project_dir / "content" / "charts"
    if not charts.is_dir():
        return
    links = symlinks_in_tree(charts)
    if charts.is_symlink() or links:
        culprit = Path("content/charts") if charts.is_symlink() else links[0]
        raise RenderError(
            f"content/charts contains a symlink: {culprit.as_posix()}",
            code="invalid_input",
            stage="input",
        )
    destination = output_dir / "charts"
    if destination.is_symlink():
        raise RenderError(
            f"build chart directory is a symlink: {destination}",
            code="invalid_input",
            stage="input",
        )
    shutil.copytree(charts, destination, dirs_exist_ok=True)


def _reject_registry_only_blocks(content: PublicContent) -> None:
    """The legacy template path cannot produce rendered visuals; say so."""

    for slide in content.slides:
        for block in slide.body:
            if isinstance(block, (ChartBlock, AnimationBlock)):
                raise RenderError(
                    f"slide {slide.slide_id}: {block.type} blocks require the renderer registry"
                )


def _prepare_blocks(
    blocks: list[object],
    data: list[dict[str, object]],
    *,
    project_dir: Path | None,
    page_label: str,
) -> None:
    """Attach build-time HTML for blocks the template cannot render itself.

    Formulas are converted from the stored LaTeX subset here, not in the
    browser: the page must never depend on a CDN or a client-side math engine,
    and an unsupported formula must stop the build instead of leaking raw
    source. Authored SVG files are sanitised and inlined the same way.
    """

    for block, block_data in zip(blocks, data, strict=True):
        if isinstance(block, FormulaBlock):
            try:
                block_data["formula_html"] = render_latex(block.latex)
            except LatexRenderError as exc:
                raise RenderError(
                    f"{page_label}: formula could not be rendered: {exc}",
                    code="invalid_input",
                    stage="render",
                ) from exc
        elif isinstance(block, SvgBlock):
            if project_dir is None:
                raise RenderError(
                    f"{page_label}: svg block requires a project directory to read {block.path}",
                    code="invalid_input",
                    stage="input",
                )
            figure_path = require_inside(
                project_dir / block.path, project_dir, what=f"{page_label} svg path"
            )
            if not figure_path.is_file():
                raise RenderError(
                    f"{page_label}: svg file not found: {block.path}",
                    code="invalid_input",
                    stage="input",
                )
            block_data["svg_html"] = inline_svg_figure(
                figure_path.read_text(encoding="utf-8"), block.alt, block.caption
            )


def _video_src(project_dir: Path | None, page_path: Path, spec_visual: RenderedVisual) -> str:
    output_path = str(spec_visual.spec.data.get("video", {}).get("output_path") or "")
    if project_dir is None or not output_path:
        return "media/course.mp4"
    target = (project_dir / output_path).resolve()
    return os.path.relpath(target, page_path.parent.resolve()).replace(os.sep, "/")


def build_public_html(
    content: PublicContent,
    template_dir: Path,
    output_path: Path,
    *,
    project_dir: Path | None = None,
    use_registry: bool = True,
    registry: RendererRegistry | None = None,
) -> Path:
    data = content.model_dump(mode="json")
    # The deck and the scene contract must be derived from the same model.
    # A broken plan or an unresolvable evidence reference stops the build here,
    # before any HTML is written.
    scene_inputs = build_scene_inputs(project_dir, content) if project_dir is not None else None
    deck_scenes = (
        scene_inputs.scenes
        if scene_inputs is not None
        else derive_deck_scenes(content, project_dir=None)
    )
    data["scenes"] = scene_payload(deck_scenes)
    rendered: list[RenderedVisual] = []
    if not use_registry:
        _reject_registry_only_blocks(content)
    marker = project_dir / "build" / BUILD_MARKER if project_dir is not None else None
    if marker is not None and use_registry:
        # From here until the final asset check, build/ is not releasable.
        write_json_atomic(marker, {"started_at": utc_now_iso()})
    if use_registry:
        rendered = render_content_visuals(
            content,
            project_dir=project_dir,
            output_dir=output_path.parent,
            registry=registry,
            publish=True,
        )
        # The template receives a view model with rendered fragments attached;
        # the content model itself is never mutated.
        if project_dir is not None and not any(
            item.spec.visual_type == "animation" for item in rendered
        ):
            # A previous animation build may have left a video that the new
            # content does not reference. Release copies media by name, so a
            # stale course.mp4 must not survive a successful non-animation
            # build (the marker alone would not stop it once this build commits).
            stale_video = project_dir / "build" / "media" / "course.mp4"
            if stale_video.is_file():
                stale_video.unlink()
        by_position = {(item.slide_id, item.block_index): item for item in rendered}
        for slide_data, slide in zip(data["slides"], content.slides, strict=True):
            for index, block_data in enumerate(slide_data["body"]):
                item = by_position.get((slide.slide_id, index))
                if item is None:
                    continue
                if item.html:
                    block_data["visual_html"] = item.html
                if item.spec.visual_type == "animation":
                    block_data["video_rendered"] = True
                    block_data["video_src"] = _video_src(project_dir, output_path, item)

    for slide_data, slide in zip(data["slides"], content.slides, strict=True):
        _prepare_blocks(
            list(slide.body),
            slide_data["body"],
            project_dir=project_dir,
            page_label=f"slide {slide.slide_id}",
        )

    rendered_html = _environment(template_dir).get_template("course.html.j2").render(content=data)
    write_text_atomic(output_path, rendered_html)
    if project_dir is not None:
        _copy_charts(project_dir, output_path.parent)
        if use_registry:
            # Written after the page exists so inline assets can hash it.
            write_render_manifest(project_dir, rendered, page_path=output_path)
            problems = verify_build_assets(project_dir)
            if problems:
                raise RenderError(
                    "build asset consistency failed: " + "; ".join(problems),
                    code="qa_failed",
                    stage="qa",
                )
            if marker is not None:
                marker.unlink()
        write_scene_contracts(project_dir, deck_scenes)
        if scene_inputs is not None:
            write_materialized_course(project_dir, scene_inputs.master)
            write_generated_plan(project_dir, scene_inputs.generated_plan)
    return output_path


def _reading_data(edition: ReadingEdition, *, project_dir: Path | None) -> dict[str, object]:
    data = edition.model_dump(mode="json")
    for section_data, section in zip(data["sections"], edition.sections, strict=True):
        _prepare_blocks(
            list(section.body),
            section_data["body"],
            project_dir=project_dir,
            page_label=f"reading section {section.slide_id}",
        )
    return data


def build_reading_html(
    edition: ReadingEdition,
    template_dir: Path,
    output_path: Path,
    *,
    project_dir: Path | None = None,
) -> Path:
    rendered = (
        _environment(template_dir)
        .get_template("reading.html.j2")
        .render(edition=_reading_data(edition, project_dir=project_dir))
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    if project_dir is not None:
        _copy_charts(project_dir, output_path.parent)
    return output_path
