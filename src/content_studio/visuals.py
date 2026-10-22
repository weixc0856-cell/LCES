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

from content_studio.errors import RenderError
from content_studio.models import (
    AnimationBlock,
    AssetCheck,
    ChartBlock,
    DiagramBlock,
    FigureBlock,
    FrameManifest,
    GraphBlock,
    PublicBlock,
    PublicContent,
    PublicSlide,
    SceneSet,
    TableBlock,
    VideoContract,
    VisualAsset,
    VisualSpec,
)
from content_studio.motion_canvas import MotionCanvasRenderer
from content_studio.paths import symlink_components
from content_studio.renderers import RenderContext, RendererRegistry, default_registry
from content_studio.utils import is_within, sha256_file, write_json_atomic
from content_studio.video_qa import verify_video_against_manifest


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
    build_id: str = ""


def visual_id(slide_id: str, block_index: int) -> str:
    return f"{slide_id}-block-{block_index:02d}"


def specs_for_slide(
    slide: PublicSlide, *, project_dir: Path | None = None, project_id: str = ""
) -> list[VisualSpec]:
    specs: list[VisualSpec] = []
    for index, block in enumerate(slide.body):
        spec = _spec_for_block(
            slide.slide_id,
            index,
            block,
            project_dir=project_dir,
            project_id=project_id,
        )
        if spec is not None:
            specs.append(spec)
    return specs


def _spec_for_block(
    slide_id: str,
    index: int,
    block: PublicBlock,
    *,
    project_dir: Path | None = None,
    project_id: str = "",
) -> VisualSpec | None:
    identifier = visual_id(slide_id, index)
    if isinstance(block, AnimationBlock):
        return _animation_spec(identifier, block, project_dir=project_dir, project_id=project_id)
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


def _animation_spec(
    identifier: str,
    block: AnimationBlock,
    *,
    project_dir: Path | None,
    project_id: str,
) -> VisualSpec:
    if project_dir is None:
        raise RenderError(
            f"visual '{identifier}': animation blocks need a project directory",
            code="invalid_input",
            stage="input",
        )
    project_root = project_dir.resolve()
    scenes_root = (project_root / "content" / "scenes").resolve()
    scene_ref = project_root / block.scene_file
    links = symlink_components(scene_ref, project_root)
    if links:
        raise RenderError(
            f"visual '{identifier}': scene file path contains a symlink: "
            f"{links[0].relative_to(project_root).as_posix()}",
            code="invalid_input",
            stage="input",
        )
    scene_path = scene_ref.resolve()
    if not is_within(scene_path, scenes_root):
        raise RenderError(
            f"visual '{identifier}': scene file escapes content/scenes: {block.scene_file}",
            code="invalid_input",
            stage="input",
        )
    if not scene_path.is_file():
        raise RenderError(
            f"visual '{identifier}': scene file not found: {block.scene_file}",
            code="invalid_input",
            stage="input",
        )
    if scene_path.stat().st_size > 1_000_000:
        raise RenderError(
            f"visual '{identifier}': scene file exceeds 1 MB: {block.scene_file}",
            code="invalid_input",
            stage="input",
        )
    try:
        payload = json.loads(scene_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RenderError(
            f"visual '{identifier}': scene file is not readable JSON: {block.scene_file}",
            code="invalid_input",
            stage="input",
        ) from exc
    raw_scenes = payload.get("scene_set") if isinstance(payload, dict) else None
    raw_video = payload.get("video") if isinstance(payload, dict) else None
    if not isinstance(raw_scenes, dict) or not isinstance(raw_video, dict):
        raise RenderError(
            f"visual '{identifier}': scene file needs 'scene_set' and 'video' objects",
            code="invalid_input",
            stage="input",
        )
    try:
        scene_set = SceneSet.model_validate(raw_scenes)
        video = VideoContract.model_validate(raw_video)
    except ValueError as exc:
        raise RenderError(
            f"visual '{identifier}': scene file is invalid: {exc}",
            code="invalid_input",
            stage="input",
        ) from exc
    if video.output_path != "build/media/course.mp4":
        raise RenderError(
            f"visual '{identifier}': P2.1 publishes to build/media/course.mp4, "
            f"not '{video.output_path}'",
            code="invalid_input",
            stage="input",
        )
    if project_id and video.project_id != project_id:
        raise RenderError(
            f"visual '{identifier}': video.project_id '{video.project_id}' "
            f"does not match project '{project_id}'",
            code="invalid_input",
            stage="input",
        )
    if video.scene_ids != scene_set.scene_ids:
        raise RenderError(
            f"visual '{identifier}': video.scene_ids must match the scene order",
            code="invalid_input",
            stage="input",
        )
    return VisualSpec(
        visual_id=identifier,
        visual_type="animation",
        title=block.caption,
        renderer=MotionCanvasRenderer.name,
        data={
            "scene_set": scene_set.model_dump(mode="json"),
            "video": video.model_dump(mode="json"),
            "source_path": block.scene_file,
            "source_sha256": sha256_file(scene_path),
        },
    )


def render_content_visuals(
    content: PublicContent,
    *,
    project_dir: Path | None = None,
    output_dir: Path | None = None,
    registry: RendererRegistry | None = None,
    publish: bool = False,
) -> list[RenderedVisual]:
    registry = registry or default_registry()
    context = RenderContext(project_dir=project_dir, output_dir=output_dir, publish=publish)
    positioned: list[tuple[str, int, VisualSpec]] = []
    for slide in content.slides:
        for index, block in enumerate(slide.body):
            spec = _spec_for_block(
                slide.slide_id,
                index,
                block,
                project_dir=project_dir,
                project_id=content.project_id,
            )
            if spec is not None:
                positioned.append((slide.slide_id, index, spec))
    if sum(spec.visual_type == "animation" for _slide, _index, spec in positioned) > 1:
        raise RenderError(
            "P2.1 supports at most one animation block per build",
            code="invalid_input",
            stage="input",
        )
    rendered: list[RenderedVisual] = []
    for slide_id, index, spec in positioned:
        output = registry.render(spec, context)
        rendered.append(
            RenderedVisual(
                slide_id=slide_id,
                block_index=index,
                spec=spec,
                html=output.html,
                renderer=output.renderer,
                renderer_version=output.renderer_version,
                output_sha256=output.sha256,
                artifacts=output.artifacts,
                build_id=output.build_id,
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
    links = symlink_components(qa_dir, project_dir)
    if links:
        raise RenderError(
            f"internal/qa contains a symlink: {links[0]}",
            code="invalid_input",
            stage="input",
        )
    qa_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(
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
            "build_id": item.build_id,
        }
        for item in rendered
    ]
    path = qa_dir / "render_manifest.json"
    write_json_atomic(path, entries)
    # Assets are written last: they reference the video and the QA evidence,
    # and are the record a later release consumes.
    write_json_atomic(
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
    "animation": "animation",
}


def _asset_contracts(
    project_dir: Path, rendered: list[RenderedVisual], page_path: Path | None
) -> list[VisualAsset]:
    content_path = project_dir / "content" / "public_content.json"
    source_hash = sha256_file(content_path) if content_path.is_file() else ""
    page_hash = sha256_file(page_path) if page_path is not None and page_path.is_file() else ""
    page_relative = _relative(page_path, project_dir) if page_path is not None else None

    required_animation = {
        "build/media/course.mp4",
        "internal/qa/frame_manifest.json",
        "internal/qa/encode_report.json",
    }
    assets: list[VisualAsset] = []
    for item in rendered:
        animation = item.spec.visual_type == "animation"
        if animation:
            source = str(item.spec.data.get("source_path") or "")
            if not source.startswith("content/scenes/"):
                raise RenderError(
                    f"visual '{item.spec.visual_id}': animation source must be a "
                    "content/scenes/*.json file",
                    code="qa_failed",
                    stage="qa",
                )
            item_source_hash = sha256_file(project_dir / source)
        else:
            source = "content/public_content.json"
            item_source_hash = source_hash

        output_paths: list[str] = []
        output_hashes: dict[str, str] = {}
        for artifact in item.artifacts:
            relative = _relative(artifact, project_dir)
            if relative is None:
                if animation:
                    # A video build must stay inside the workspace: a dropped
                    # path would make the asset contract point at the page.
                    raise RenderError(
                        f"visual '{item.spec.visual_id}': artifact {artifact} "
                        "is outside the project workspace",
                        code="qa_failed",
                        stage="qa",
                    )
                continue
            if animation and not (
                relative.startswith("internal/qa/") or relative == "build/media/course.mp4"
            ):
                # Frame sequences and driver logs remain in build/motion/ and
                # are reachable through build_id + the manifest, not the asset
                # contract.
                continue
            output_paths.append(relative)
            output_hashes[relative] = sha256_file(artifact)
        if not output_paths and page_relative is not None:
            output_paths.append(page_relative)
            output_hashes[page_relative] = page_hash
        if animation:
            missing = required_animation - set(output_paths)
            if missing:
                raise RenderError(
                    f"visual '{item.spec.visual_id}': animation artifact missing {sorted(missing)}",
                    code="qa_failed",
                    stage="qa",
                )

        spec_payload = item.spec.model_dump(mode="json")
        assets.append(
            VisualAsset(
                asset_id=item.spec.visual_id,
                asset_type=_ASSET_TYPES.get(item.spec.visual_type, "svg"),  # type: ignore[arg-type]
                source=source,
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
                source_hash=item_source_hash,
                build_id=item.build_id,
            )
        )
    return assets


def verify_build_assets(project_dir: Path) -> list[str]:
    """Re-read the committed asset record; any mismatch makes the build fail.

    The record is written last, but a process can still die between the video
    replace and the manifest write. The build marker blocks release in that
    window; this function catches anything that did commit.
    """

    qa_dir = project_dir / "internal" / "qa"
    links = symlink_components(qa_dir, project_dir)
    if links:
        return [f"internal/qa contains a symlink: {links[0]}"]
    assets_path = qa_dir / "visual_assets.json"
    if not assets_path.is_file():
        return ["internal/qa/visual_assets.json is missing"]
    try:
        payload = json.loads(assets_path.read_text(encoding="utf-8"))
    except ValueError:
        return ["internal/qa/visual_assets.json is not valid JSON"]
    if not isinstance(payload, list):
        return ["internal/qa/visual_assets.json is not a list"]

    problems: list[str] = []
    for entry in payload:
        if not isinstance(entry, dict):
            problems.append("visual_assets.json contains a non-object entry")
            continue
        asset_id = str(entry.get("asset_id") or "?")
        paths = entry.get("output_paths") or []
        hashes = entry.get("output_hashes") or {}
        if not isinstance(paths, list) or not isinstance(hashes, dict):
            problems.append(f"{asset_id}: output paths/hashes are malformed")
            continue
        for relative in paths:
            if not isinstance(relative, str):
                problems.append(f"{asset_id}: non-string output path")
                continue
            path = project_dir / relative
            if not path.is_file():
                problems.append(f"{asset_id}: missing output {relative}")
                continue
            if sha256_file(path) != hashes.get(relative):
                problems.append(f"{asset_id}: hash mismatch for {relative}")
        if entry.get("asset_type") != "animation":
            continue
        build_id = str(entry.get("build_id") or "")
        if not build_id:
            problems.append(f"{asset_id}: animation asset has no build_id")
        video = project_dir / "build" / "media" / "course.mp4"
        manifest_path = project_dir / "internal" / "qa" / "frame_manifest.json"
        report_path = project_dir / "internal" / "qa" / "encode_report.json"
        for label, path in (
            ("video", video),
            ("frame manifest", manifest_path),
            ("encode report", report_path),
        ):
            if not path.is_file():
                problems.append(f"{asset_id}: {label} missing")
        if not problems and manifest_path.is_file():
            try:
                manifest = FrameManifest.model_validate_json(
                    manifest_path.read_text(encoding="utf-8")
                )
            except ValueError as exc:
                problems.append(f"{asset_id}: frame manifest is invalid: {exc}")
            else:
                if manifest.build_id != build_id:
                    problems.append(
                        f"{asset_id}: manifest build_id {manifest.build_id} != {build_id}"
                    )
                problems.extend(verify_video_against_manifest(video, manifest))
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except ValueError:
                problems.append(f"{asset_id}: encode report is not valid JSON")
            else:
                if report.get("video_sha256") != sha256_file(video):
                    problems.append(f"{asset_id}: video hash does not match encode report")
    return problems[:10]


def _relative(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
