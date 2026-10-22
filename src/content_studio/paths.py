"""Project layout and path-safety helpers."""

from __future__ import annotations

import re
from pathlib import Path

from content_studio.errors import ConfigurationError

PROJECT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")

# Present while a public build is committing. `lces release` refuses it.
BUILD_MARKER = ".build-in-progress"

# Created by `lces init-project`. Permissions differ per directory: only
# `release/` may leave the machine.
PROJECT_SUBDIRS = (
    "input",
    "internal",
    "internal/qa",
    "internal/drafts",
    "internal/sources",
    "content",
    "content/charts",
    "content/scenes",
    "build",
    "build/slides",
    "build/artifacts",
    "release",
)

PUBLIC_BUILD_ALLOWLIST = frozenset(
    {
        "slides/index.html",
        "reading_edition.html",
        "media/course.mp4",
        "media/course.srt",
        "media/course.vtt",
        "metadata/description.md",
        "release_manifest.json",
    }
)


def safe_project_id(project_id: str) -> str:
    if not PROJECT_ID_PATTERN.fullmatch(project_id):
        raise ConfigurationError(
            "project_id must be 2-63 characters: lowercase letters, digits, or hyphens"
        )
    return project_id


def project_root(projects_root: Path, project_id: str) -> Path:
    return projects_root / safe_project_id(project_id)


def ensure_project_layout(root: Path) -> Path:
    for relative in PROJECT_SUBDIRS:
        (root / relative).mkdir(parents=True, exist_ok=True)
    return root


def require_project_dir(path: Path) -> Path:
    """Validate that *path* looks like an LCES project directory."""

    root = path.resolve()
    if not root.is_dir():
        raise ConfigurationError(f"project directory does not exist: {path}")
    if not (root / "project.yaml").is_file():
        raise ConfigurationError(f"missing project.yaml in {path}")
    return root


def repository_root() -> Path:
    """Project/checkout root (works for editable and source checkouts)."""

    return Path(__file__).resolve().parents[2]


def template_dir(kind: str = "public_html") -> Path:
    return repository_root() / "templates" / kind


def require_inside(path: Path, root: Path, *, what: str = "path") -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ConfigurationError(f"{what} must stay inside the project directory: {path}") from exc
    return resolved
