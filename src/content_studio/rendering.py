"""HTML rendering from public-only models.

The renderer only receives ``PublicContent`` / ``ReadingEdition``. Speaker
scripts are never accepted here, by construction.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from content_studio.models import PublicContent, ReadingEdition
from content_studio.visuals import render_content_visuals, write_render_manifest


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
    charts = project_dir / "content" / "charts"
    if charts.is_dir():
        shutil.copytree(charts, output_dir / "charts", dirs_exist_ok=True)


def build_public_html(
    content: PublicContent,
    template_dir: Path,
    output_path: Path,
    *,
    project_dir: Path | None = None,
    use_registry: bool = True,
) -> Path:
    data = content.model_dump(mode="json")
    if use_registry:
        rendered = render_content_visuals(
            content, project_dir=project_dir, output_dir=output_path.parent
        )
        # The template receives a view model with rendered fragments attached;
        # the content model itself is never mutated.
        by_position = {(item.slide_id, item.block_index): item.html for item in rendered}
        for slide_data, slide in zip(data["slides"], content.slides, strict=True):
            for index, block_data in enumerate(slide_data["body"]):
                html = by_position.get((slide.slide_id, index))
                if html is not None:
                    block_data["visual_html"] = html
        if project_dir is not None:
            write_render_manifest(project_dir, rendered)

    rendered_html = _environment(template_dir).get_template("course.html.j2").render(content=data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered_html, encoding="utf-8")
    if project_dir is not None:
        _copy_charts(project_dir, output_path.parent)
    return output_path


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
        .render(edition=edition.model_dump(mode="json"))
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    if project_dir is not None:
        _copy_charts(project_dir, output_path.parent)
    return output_path
