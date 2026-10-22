"""HTML rendering from public-only models.

The renderer only receives ``PublicContent`` / ``ReadingEdition``. Speaker
scripts are never accepted here, by construction.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from content_studio.models import PublicContent, ReadingEdition


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
) -> Path:
    rendered = (
        _environment(template_dir)
        .get_template("course.html.j2")
        .render(content=content.model_dump(mode="json"))
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
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
