"""Approval and release assembly (PRD Gate 4).

The release directory is rebuilt from an explicit staging area. The working
directory is never zipped, and the archive is created only from the staged
release tree.
"""

from __future__ import annotations

import platform
import re
import shutil
import zipfile
from pathlib import Path

from content_studio import __version__
from content_studio.content import load_public_content, load_reading_edition
from content_studio.errors import ConfigurationError, ValidationFailure
from content_studio.models import (
    ApprovalRecord,
    ManifestFile,
    ProjectConfig,
    QAReport,
    ReleaseManifest,
)
from content_studio.paths import BUILD_MARKER
from content_studio.storage import TaskStore
from content_studio.utils import sha256_file, write_json, write_text
from content_studio.validation import run_release_checks

VERSION_PATTERN = re.compile(r"^v[0-9]{1,3}$")

MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".json": "application/json",
    ".md": "text/markdown; charset=utf-8",
    ".mp4": "video/mp4",
    ".srt": "application/x-subrip",
    ".vtt": "text/vtt",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".css": "text/css",
    ".js": "text/javascript",
}


def _approval_path(project_dir: Path, version: str) -> Path:
    return project_dir / "internal" / "qa" / f"approval-{version}.json"


def approve(
    project_dir: Path,
    config: ProjectConfig,
    version: str,
    approved_by: str,
    *,
    notes: str = "",
    store: TaskStore | None = None,
) -> ApprovalRecord:
    if not VERSION_PATTERN.fullmatch(version):
        raise ConfigurationError("release version must look like v1, v2, ...")
    if not approved_by.strip():
        raise ConfigurationError("approved_by must not be empty")
    record = ApprovalRecord(
        project_id=config.project_id,
        version=version,
        approved_by=approved_by.strip(),
        scope="release",
        notes=notes,
    )
    write_json(_approval_path(project_dir, version), record)
    if store is not None:
        store.save_approval(record)
    return record


def load_approval(project_dir: Path, version: str) -> ApprovalRecord | None:
    path = _approval_path(project_dir, version)
    if not path.exists():
        return None
    return ApprovalRecord.model_validate_json(path.read_text(encoding="utf-8"))


def load_qa_report(project_dir: Path) -> QAReport | None:
    path = project_dir / "internal" / "qa" / "qa_report.json"
    if not path.exists():
        return None
    return QAReport.model_validate_json(path.read_text(encoding="utf-8"))


def _description(project_dir: Path, config: ProjectConfig) -> str:
    public = load_public_content(project_dir)
    reading = load_reading_edition(project_dir)
    lines = [f"# {public.title if public else config.title}", ""]
    if public and public.subtitle:
        lines += [public.subtitle, ""]
    if reading:
        lines += ["## 摘要", "", reading.abstract, ""]
    lines += ["## 章节", ""]
    if public:
        lines += [f"- {slide.title}" for slide in public.slides]
    if reading and reading.references:
        lines += ["", "## 来源", ""] + [f"- {item}" for item in reading.references]
    lines.append("")
    return "\n".join(lines)


def _media_type(path: Path) -> str:
    return MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _manifest_files(staging: Path) -> list[ManifestFile]:
    entries: list[ManifestFile] = []
    for path in sorted(staging.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(staging).as_posix()
        if relative == "release_manifest.json":
            continue
        entries.append(
            ManifestFile(
                path=relative,
                sha256=sha256_file(path),
                size_bytes=path.stat().st_size,
                media_type=_media_type(path),
            )
        )
    return entries


def _stage(project_dir: Path, config: ProjectConfig, staging: Path) -> None:
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    html = project_dir / "build" / "slides" / "index.html"
    if not html.is_file():
        raise ValidationFailure("public HTML is missing; run `lces build` first")
    (staging / "slides").mkdir(parents=True)
    shutil.copy2(html, staging / "slides" / "index.html")
    charts = project_dir / "build" / "slides" / "charts"
    if charts.is_dir():
        shutil.copytree(charts, staging / "slides" / "charts")

    reading = project_dir / "build" / "reading_edition.html"
    if reading.is_file():
        shutil.copy2(reading, staging / "reading_edition.html")

    write_text(staging / "metadata" / "description.md", _description(project_dir, config))

    media = project_dir / "build" / "media"
    if media.is_dir():
        for name in ("course.mp4", "course.srt", "course.vtt"):
            source = media / name
            if source.is_file():
                (staging / "media").mkdir(exist_ok=True)
                shutil.copy2(source, staging / "media" / name)


def _write_archive(release_root: Path, destination: Path, project_id: str) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(release_root.rglob("*")):
            if path.is_file():
                relative = path.relative_to(release_root).as_posix()
                archive.write(path, arcname=f"{project_id}/{relative}")
    return destination


def build_release(
    project_dir: Path,
    config: ProjectConfig,
    version: str,
    *,
    store: TaskStore | None = None,
    force: bool = False,
) -> ReleaseManifest:
    if not VERSION_PATTERN.fullmatch(version):
        raise ConfigurationError("release version must look like v1, v2, ...")
    project_dir = project_dir.resolve()
    marker = project_dir / "build" / BUILD_MARKER
    if marker.is_file():
        raise ValidationFailure(
            "build is incomplete: build/.build-in-progress exists; run `lces build` again"
        )
    release_root = project_dir / "release" / version
    if release_root.exists() and not force:
        raise ConfigurationError(
            f"{release_root} already exists; pass --force to rebuild the same version"
        )

    qa = load_qa_report(project_dir)
    if qa is None:
        raise ValidationFailure("QA report missing; run `lces validate` first")
    if qa.blocking_failures:
        details = "; ".join(f"{item.check_id}: {item.message}" for item in qa.blocking_failures)
        raise ValidationFailure(f"QA has blocking failures, release refused: {details}")

    approval = load_approval(project_dir, version)
    if config.release_requires_human_approval and approval is None:
        raise ValidationFailure(
            f"human approval for {version} is missing; run `lces approve` after review"
        )

    staging = project_dir / "build" / f"release-staging-{version}"
    _stage(project_dir, config, staging)

    files = _manifest_files(staging)
    content_hash = ""
    public_path = project_dir / "content" / "public_content.json"
    if public_path.is_file():
        content_hash = sha256_file(public_path)

    manifest = ReleaseManifest(
        project_id=config.project_id,
        version=version,
        package_version=__version__,
        python_version=platform.python_version(),
        provider=qa.provider,
        model=qa.model,
        content_sha256=content_hash,
        gates=qa.gate_status(),
        human_approval=approval,
        files=files,
    )
    write_json(staging / "release_manifest.json", manifest)

    checks = run_release_checks(
        staging,
        manifest=manifest,
        approval_required=config.release_requires_human_approval,
        approval_present=approval is not None,
        project_dir=project_dir,
    )
    failures = [item for item in checks if item.status == "fail" and item.blocking]
    if failures:
        shutil.rmtree(staging)
        details = "; ".join(f"{item.check_id}: {item.message}" for item in failures)
        raise ValidationFailure(f"release gate failed: {details}")

    gate4 = (
        "fail"
        if failures
        else ("partial" if any(item.status == "not_run" for item in checks) else "pass")
    )
    manifest = manifest.model_copy(update={"gates": {**manifest.gates, "gate_4_release": gate4}})
    write_json(staging / "release_manifest.json", manifest)

    if release_root.exists():
        shutil.rmtree(release_root)
    release_root.parent.mkdir(parents=True, exist_ok=True)
    staging.rename(release_root)

    # A public copy of the manifest makes the delivered package self-describing.
    write_json(release_root / "release_manifest.json", manifest)

    archive = _write_archive(
        release_root,
        project_dir / "build" / "artifacts" / f"{config.project_id}-{version}.zip",
        config.project_id,
    )

    if store is not None:
        for item in manifest.files:
            store.register_asset(config.project_id, "release", item.path, item.sha256)
        store.register_asset(config.project_id, "archive", str(archive), sha256_file(archive))

    return manifest


def verify_release(
    project_dir: Path, version: str = "v1"
) -> tuple[ReleaseManifest | None, list[str]]:
    release_root = project_dir / "release" / version
    manifest_path = release_root / "release_manifest.json"
    if not manifest_path.is_file():
        return None, [f"manifest missing: {manifest_path}"]
    manifest = ReleaseManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    approval = load_approval(project_dir, version)
    checks = run_release_checks(
        release_root,
        manifest=manifest,
        approval_required=True,
        approval_present=approval is not None,
        project_dir=project_dir,
    )
    errors = [f"{item.check_id}: {item.message}" for item in checks if item.status == "fail"]
    return manifest, errors


__all__ = [
    "approve",
    "build_release",
    "load_approval",
    "load_qa_report",
    "verify_release",
]
