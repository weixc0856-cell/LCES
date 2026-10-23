"""Motion Canvas renderer adapter (P1, Linux only).

The adapter implements the existing :class:`~content_studio.renderers.Renderer`
hooks. It is deliberately **not** part of :func:`default_registry`: P1 talks to
it through an explicit registry and the ``lces render-scene`` command, so a
prototype cannot slip into the production build path before the P1 gates pass.

Boundaries:

* Python validates the contracts and the timeline, owns the build directory,
  enforces versions, cancellation, and timeouts.
* A pinned Node project under ``motion/`` produces the frame sequence; its
  driver is the only component that talks to the editor UI.
* Frames are written to a build-specific directory. Nothing here publishes;
  encoding and the atomic move to ``build/media/`` are P1.3.

Failure codes come from ``config/error_codes.json`` (see ``errors.py``); the
Node driver loads the same file, so a failure cannot be classified differently
on the two sides.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from content_studio.encode import build_encode_command, encode_frames, encode_report
from content_studio.errors import (
    ERROR_CODES,
    ERROR_CODES_PATH,
    RenderCancelled,
    RenderError,
)
from content_studio.frame_manifest import (
    build_frame_manifest,
    verify_frame_manifest,
    write_frame_manifest,
)
from content_studio.media import ffmpeg_path, ffmpeg_version
from content_studio.models import SceneContract, SceneSet, VideoContract, VisualSpec
from content_studio.motion_templates import (
    SUPPORTED_SCENE_TYPES,
    data_problems,
    scene_source,
)
from content_studio.paths import repository_root, symlink_components
from content_studio.renderers import (
    RenderContext,
    Renderer,
    RendererRegistry,
    RenderResult,
    ResourceEstimate,
)
from content_studio.timeline import TimelinePlan, plan_from_scenes
from content_studio.utils import sha256_file, write_json
from content_studio.video_qa import verify_video_against_manifest

NODE_VERSION = "24.22.1"
MOTION_CANVAS_VERSION = "3.17.2"
PLAYWRIGHT_VERSION = "1.64.0"
MIN_FFMPEG = (6, 0)
SUPPORTED_PLATFORMS = frozenset({"linux"})

DEFAULT_MAX_RENDER_MS = 600_000
P1_MAX_DURATION_MS = 600_000
MAX_WIDTH = 7680
MAX_HEIGHT = 4320

BUILD_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
# A standalone render may not write into these: they hold inputs,
# internal research, or the release tree.
PROTECTED_PROJECT_DIRS = frozenset({"input", "internal", "content", "release"})
HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
LOCKFILE_NAME = "package-lock.json"


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    expected: str
    actual: str
    ok: bool = True
    hint: str = ""
    # Failure code for this specific dependency; the generic default is used
    # when the check is only "tool missing or wrong version".
    code: str = "environment_unavailable"

    def message(self) -> str:
        actual = self.actual or "missing"
        suffix = f"; {self.hint}" if self.hint else ""
        return f"{self.name}: expected {self.expected}, found {actual}{suffix}"


def motion_project_dir() -> Path:
    return repository_root() / "motion"


def _resolved_executable(command: str) -> str | None:
    """An absolute, regular, executable file; symlinks are judged by target."""

    path = Path(command).expanduser()
    if not path.is_absolute():
        return None
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        return None
    return str(resolved)


def node_binary() -> str | None:
    """Controlled executable path: ``LCES_NODE_BIN`` or ``node`` on PATH.

    An override must be an absolute path to an executable file. Returning
    ``None`` is a hard environment failure; the adapter never falls back to
    ``node`` on PATH when an invalid override was supplied.
    """

    override = os.environ.get("LCES_NODE_BIN", "").strip()
    if override:
        return _resolved_executable(override)
    found = shutil.which("node")
    return _resolved_executable(found) if found else None


def _run_probe(command: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        command, capture_output=True, text=True, timeout=20, check=False, cwd=cwd
    )
    return (completed.stdout or completed.stderr or "").strip()


def _invalid(message: str) -> RenderError:
    return RenderError(message, code="invalid_input", stage="input")


def _require_no_symlink_components(path: Path, root: Path, *, what: str) -> None:
    links = symlink_components(path, root)
    if links:
        raise _invalid(f"{what} contains a symlink: {links[0]}")


def _bound_output_dir(output_dir: Path, project_root: Path | None) -> Path:
    """A build output directory inside the project, with no link components.

    ``lces render-scene --out`` used to accept any path, so a mistyped or
    hostile value could write frames and a video into the host tree. The
    production path always passes the project root; direct registry calls
    without one still get the symlink and file-type checks that need no root.
    """

    candidate = output_dir.expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    if project_root is not None:
        try:
            relative = candidate.resolve().relative_to(project_root)
        except ValueError as exc:
            raise _invalid(f"output directory escapes the project directory: {output_dir}") from exc
        if not relative.parts:
            raise _invalid("output directory must be a build directory, not the project root")
        if relative.parts[0] in PROTECTED_PROJECT_DIRS:
            raise _invalid(f"output directory must not be under {relative.parts[0]}/")
        _require_no_symlink_components(candidate, project_root, what="output directory")
    elif candidate.is_symlink():
        raise _invalid("output directory must not be a symlink")
    final = candidate.resolve()
    if final.exists() and not final.is_dir():
        raise _invalid(f"output directory is not a directory: {output_dir}")
    return final


def _prepare_driver_dirs(build_root: Path) -> tuple[Path, Path]:
    """Per-build HOME and TMP so the editor cannot write the host profile."""

    home = build_root / "home"
    temporary = build_root / "tmp"
    for path in (
        home / ".config",
        home / ".cache",
        home / ".local" / "share",
        home / ".local" / "state",
        temporary,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return home, temporary


def playwright_browsers_path() -> str | None:
    """Host browser location to keep reading after HOME is redirected.

    Browsers are read-only inputs; the driver must still find the Chromium
    that Playwright installed into the host profile or an explicit
    ``PLAYWRIGHT_BROWSERS_PATH``.
    """

    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "").strip()
    if configured:
        return configured
    home = Path.home()
    for candidate in (
        home / ".cache" / "ms-playwright",
        home / "Library" / "Caches" / "ms-playwright",
        home / "AppData" / "Local" / "ms-playwright",
    ):
        if candidate.is_dir():
            return str(candidate)
    return None


def _package_version(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    version = payload.get("version")
    return version if isinstance(version, str) else ""


def dependency_problems(project: Path) -> list[str]:
    """Compare the installed tree with the pinned lockfile.

    ``npm ci`` is the only admitted install path. ``npm install`` can silently
    upgrade a direct dependency (or rewrite the tree) while ``package.json``
    still looks correct, which would make a render irreproducible. Only the
    declared direct dependencies are compared here; ``npm ci`` removes
    transitive packages that are not in the lockfile, and the installed
    versions of direct dependencies are enough to detect a rewritten tree.
    """

    try:
        declared = json.loads((project / "package.json").read_text(encoding="utf-8"))
        locked = json.loads((project / LOCKFILE_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"cannot read package.json/{LOCKFILE_NAME} in motion/: {exc.__class__.__name__}"]
    packages = locked.get("packages")
    if not isinstance(packages, dict):
        return [f"{LOCKFILE_NAME} has no 'packages' map; regenerate it with npm"]
    root = packages.get("")
    if not isinstance(root, dict):
        return [f"{LOCKFILE_NAME} has no root package entry; regenerate it with npm"]

    problems: list[str] = []
    for section in ("dependencies", "devDependencies"):
        wanted = declared.get(section) or {}
        pinned = root.get(section) or {}
        if not isinstance(wanted, dict):
            problems.append(f"package.json {section} is not an object")
            continue
        if wanted != pinned:
            problems.append(
                f"package.json {section} does not match {LOCKFILE_NAME}; "
                "run npm install and commit the lockfile"
            )
        for name in sorted(wanted):
            entry = packages.get(f"node_modules/{name}")
            version = entry.get("version") if isinstance(entry, dict) else None
            if not isinstance(version, str):
                problems.append(f"{name} is not pinned in {LOCKFILE_NAME}")
                continue
            installed = _package_version(project / "node_modules" / name / "package.json")
            if installed != version:
                problems.append(
                    f"{name}: installed {installed or 'missing'}, lockfile pins {version}"
                )
    return problems


def _version_tuple(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for piece in version.split("."):
        if not piece.isdigit():
            break
        parts.append(int(piece))
    return tuple(parts)


def _chromium_problem(node: str | None, project: Path) -> str:
    if node is None:
        return "node is missing, so the Chromium build cannot be resolved"
    if not (project / "node_modules" / "playwright").is_dir():
        return "Playwright is not installed in motion/; run `npm ci` there"
    try:
        output = _run_probe(
            [
                node,
                "-e",
                "const {chromium} = require('playwright');"
                "process.stdout.write(chromium.executablePath());",
            ],
            cwd=project,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"cannot resolve Chromium: {exc.__class__.__name__}"
    if not output or not Path(output).is_file():
        return "Chromium is not installed; run `npx playwright install chromium` in motion/"
    return ""


def environment_report() -> list[DependencyStatus]:
    """Every dependency the adapter needs, with the version it actually found."""

    project = motion_project_dir()
    node = node_binary()
    node_version = ""
    npm_version = ""
    if node is not None:
        try:
            node_version = _run_probe([node, "--version"]).lstrip("v")
            npm = shutil.which("npm")
            if npm is not None:
                npm_version = _run_probe([npm, "--version"])
        except (OSError, subprocess.TimeoutExpired):
            node_version = ""

    motion_version = _package_version(
        project / "node_modules" / "@motion-canvas" / "core" / "package.json"
    )
    playwright_version = _package_version(project / "node_modules" / "playwright" / "package.json")
    ffmpeg_version_value = ffmpeg_version()
    chromium = _chromium_problem(node, project)

    platform_ok = sys.platform in SUPPORTED_PLATFORMS
    dependency_issues = dependency_problems(project)
    return [
        DependencyStatus(
            name="platform",
            expected="linux",
            actual=sys.platform,
            ok=platform_ok,
            hint="P1 is Linux-only; Windows support requires a new P0 and re-admission",
            code="unsupported_platform",
        ),
        DependencyStatus(
            name="node",
            expected=NODE_VERSION,
            actual=node_version,
            ok=node_version == NODE_VERSION,
            hint=(
                "LCES_NODE_BIN must be an absolute executable file"
                if os.environ.get("LCES_NODE_BIN", "").strip()
                else "install Node 24.22.1 and set LCES_NODE_BIN if it is not on PATH"
            ),
        ),
        DependencyStatus(
            name="npm",
            expected="11.x (bundled with Node 24.22.1)",
            actual=npm_version,
            ok=npm_version.split(".")[0] == "11",
            hint="use the npm shipped with Node 24.22.1",
        ),
        DependencyStatus(
            name="motion-canvas",
            expected=MOTION_CANVAS_VERSION,
            actual=motion_version,
            ok=motion_version == MOTION_CANVAS_VERSION,
            hint="run `npm ci` in motion/; do not use `npm install`",
        ),
        DependencyStatus(
            name="playwright",
            expected=PLAYWRIGHT_VERSION,
            actual=playwright_version,
            ok=playwright_version == PLAYWRIGHT_VERSION,
            hint="run `npm ci` in motion/",
        ),
        DependencyStatus(
            name="chromium",
            expected="installed Playwright browser",
            actual="" if chromium else "installed",
            ok=not chromium,
            hint=chromium,
        ),
        DependencyStatus(
            name="dependencies",
            expected=f"{LOCKFILE_NAME} tree from npm ci",
            actual="consistent" if not dependency_issues else f"{len(dependency_issues)} issue(s)",
            ok=not dependency_issues,
            hint="; ".join(dependency_issues[:3]) if dependency_issues else "",
            code="dependency_mismatch",
        ),
        DependencyStatus(
            name="ffmpeg",
            expected=f">= {MIN_FFMPEG[0]}.{MIN_FFMPEG[1]}",
            actual=ffmpeg_version_value,
            ok=bool(ffmpeg_version_value)
            and _version_tuple(ffmpeg_version_value)[:2] >= MIN_FFMPEG,
            hint="install FFmpeg 6 or newer; the exact build is recorded per render",
        ),
    ]


def motion_status() -> tuple[bool, str]:
    """``doctor`` summary; fixed-version checks are the adapter's job."""

    report = environment_report()
    problems = [item for item in report if not item.ok]
    if problems:
        return False, "; ".join(item.message() for item in problems)
    detail = {item.name: item.actual for item in report}
    return True, (
        f"node {detail['node']}, Motion Canvas {detail['motion-canvas']}, "
        f"Chromium + Playwright {detail['playwright']}, FFmpeg {detail['ffmpeg']}"
    )


class MotionCanvasRenderer(Renderer):
    name = "motion_canvas.renderer"
    version = "0.1.0"
    visual_types = frozenset({"animation"})

    def __init__(
        self, *, max_render_ms: int = DEFAULT_MAX_RENDER_MS, decode_frames: bool = True
    ) -> None:
        self.max_render_ms = max_render_ms
        self.decode_frames = decode_frames
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._process: subprocess.Popen[bytes] | None = None
        self._process_group: int | None = None
        self._diagnostics: list[str] = []
        self._last: dict[str, Any] = {}
        self._environment_code = "environment_unavailable"

    # -- environment -----------------------------------------------------

    def check_environment(self) -> list[str]:
        problems = [item for item in environment_report() if not item.ok]
        self._environment_code = next(
            (item.code for item in problems if item.code), "environment_unavailable"
        )
        return [item.message() for item in problems]

    def environment_error_code(self) -> str:
        if sys.platform not in SUPPORTED_PLATFORMS:
            return "unsupported_platform"
        return self._environment_code

    def estimate_resources(self, spec: VisualSpec) -> ResourceEstimate:
        try:
            _scenes, _video, plan = self._parse(spec)
        except RenderError:
            return ResourceEstimate(notes="invalid input; nothing will be rendered")
        return ResourceEstimate(
            cpu_seconds=round(plan.total_frames * 0.02, 1),
            memory_mb=768,
            notes="P0 measured ~4.7 s and ~302 MB for 300 frames at 1080p30",
        )

    # -- input -----------------------------------------------------------

    def validate_input(self, spec: VisualSpec) -> list[str]:
        try:
            scenes, video, plan = self._parse(spec)
        except RenderError as exc:
            return [str(exc)]
        problems: list[str] = []
        if len(scenes.scenes) != 1:
            problems.append("P1 supports exactly one scene per build")
        for scene in scenes.scenes:
            problems.extend(_scene_problems(scene, video.width, video.height))
        if video.renderer and video.renderer != self.name:
            problems.append(f"video.renderer '{video.renderer}' does not match '{self.name}'")
        if video.renderer_version and video.renderer_version != self.version:
            problems.append(
                f"video.renderer_version '{video.renderer_version}' does not match '{self.version}'"
            )
        if video.narration_ref or video.audio_refs:
            problems.append("P1 renders silent video; narration, audio and subtitles are P3")
        for index in range(1, len(scenes.scenes)):
            left = scenes.scenes[index - 1].transition_out
            right = scenes.scenes[index].transition_in
            if left != "cut" and right != "cut":
                problems.append(f"scene boundary {index}: both sides declare a non-cut transition")
        if plan.total_frames > 0 and not plan.within_tolerance:
            problems.append(
                "timeline deviates from the contract by more than one frame "
                f"({float(plan.expected_seconds):.6f}s vs "
                f"{float(plan.contract_seconds):.6f}s)"
            )
        return problems

    def _parse(self, spec: VisualSpec) -> tuple[SceneSet, VideoContract, TimelinePlan]:
        if spec.visual_type != "animation":
            raise _invalid(f"visual_type '{spec.visual_type}' is not an animation")
        data = spec.data or {}
        raw_scenes = data.get("scene_set")
        raw_video = data.get("video")
        if not isinstance(raw_scenes, dict) or not isinstance(raw_video, dict):
            raise _invalid("data must contain 'scene_set' and 'video' objects")
        try:
            scenes = SceneSet.model_validate(raw_scenes)
        except ValueError as exc:
            raise _invalid(f"scene_set is invalid: {exc}") from exc
        try:
            video = VideoContract.model_validate(raw_video)
        except ValueError as exc:
            raise _invalid(f"video contract is invalid: {exc}") from exc
        if video.scene_ids != scenes.scene_ids:
            raise _invalid(
                "video.scene_ids must list the scene set in timeline order: "
                f"{scenes.scene_ids} != {video.scene_ids}"
            )
        if video.width > MAX_WIDTH or video.height > MAX_HEIGHT:
            raise _invalid(f"canvas {video.width}x{video.height} exceeds the P1 limit")
        if sum(scene.duration_ms for scene in scenes.scenes) > P1_MAX_DURATION_MS:
            raise _invalid(f"P1 builds are limited to {P1_MAX_DURATION_MS} ms")
        try:
            plan = plan_from_scenes(scenes.scenes, fps_num=video.fps_num, fps_den=video.fps_den)
        except RenderError as exc:
            raise _invalid(str(exc)) from exc
        return scenes, video, plan

    # -- render ----------------------------------------------------------

    def render(self, spec: VisualSpec, context: RenderContext) -> RenderResult:
        if context.output_dir is None:
            raise _invalid("Motion Canvas needs an output directory")
        scenes, video, plan = self._parse(spec)
        project_root = context.project_dir.resolve() if context.project_dir is not None else None
        publish_root = project_root if context.publish else None
        if publish_root is not None and video.output_path != "build/media/course.mp4":
            raise _invalid(
                "P2.1 publishes to build/media/course.mp4; "
                f"video.output_path is '{video.output_path}'"
            )
        if publish_root is not None:
            base_dir = publish_root / "build"
            _require_no_symlink_components(base_dir, publish_root, what="build directory")
            # QA evidence is written below internal/qa; a linked directory
            # would redirect it outside the project before the build commits.
            _require_no_symlink_components(
                publish_root / "internal" / "qa",
                publish_root,
                what="internal/qa",
            )
        else:
            base_dir = _bound_output_dir(context.output_dir, project_root)
        build_id = _build_id()
        build_root = base_dir / "motion" / build_id
        if project_root is not None:
            _require_no_symlink_components(build_root, project_root, what="build directory")
        if build_root.exists():
            raise _invalid(f"build directory already exists: {build_root.name}")
        project = motion_project_dir()
        if not (project / "node_modules").is_dir():
            raise RenderError(
                "motion/node_modules is missing; run `npm ci` in motion/",
                code="environment_unavailable",
                stage="environment",
            )
        dependency_issues = dependency_problems(project)
        if dependency_issues:
            raise RenderError(
                "installed dependencies do not match the pinned lockfile: "
                + "; ".join(dependency_issues[:3])
                + "; run `npm ci` in motion/",
                code="dependency_mismatch",
                stage="environment",
            )
        node = node_binary()
        if node is None:
            override = os.environ.get("LCES_NODE_BIN", "").strip()
            target = "LCES_NODE_BIN" if override else "node"
            raise RenderError(
                f"{target} is not an absolute executable file",
                code="environment_unavailable",
                stage="environment",
            )

        with self._lock:
            if self._process is not None:
                raise RenderError(
                    "this renderer already has an active build; one build at a time",
                    code="render_failed",
                    stage="render",
                )
            self._cancel.clear()

        self._diagnostics = [f"build {build_id}: preparing"]
        self._last = {"build_id": build_id, "visual_id": spec.visual_id}
        try:
            work = _materialise_project(project, build_root, scenes.scenes[0], plan, video)
            home_dir, tmp_dir = _prepare_driver_dirs(build_root)
            frames_dir = build_root / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            if frames_dir.is_symlink():
                raise _invalid("frame directory must not be a symlink")
            env = _driver_env(
                output_dir=frames_dir,
                expected_frames=plan.total_frames,
                build_id=build_id,
                max_render_ms=self.max_render_ms,
                home_dir=home_dir,
                tmp_dir=tmp_dir,
            )
            log_path = build_root / "driver.log"
            command = [node, "driver.mjs"]
            self._diagnostics.append(f"build {build_id}: driver {command[-1]}")
            forced, returncode = self._execute_driver(
                command,
                cwd=work,
                env=env,
                log_path=log_path,
                timeout_s=self.max_render_ms / 1000,
            )
            if forced == "cancelled" or self._cancel.is_set():
                # The driver can win the race and write a ``render_failed``
                # report when its process group is killed before this loop
                # observes the cancel flag. The caller's cancel is still the
                # cause, so the terminal state is ``cancelled`` either way.
                raise RenderCancelled(f"build {build_id} was cancelled")
            if forced == "render_timeout":
                raise RenderError(
                    f"build {build_id} exceeded {self.max_render_ms} ms",
                    code="render_timeout",
                    stage="render",
                )

            report_path = frames_dir / "report.json"
            report = _load_report(report_path, build_id)
            if report.get("error_code"):
                reported = str(report["error_code"])
                code = reported if reported in ERROR_CODES else "render_failed"
                raise RenderError(
                    f"driver reported {reported}: {report.get('terminal', 'failed')}"
                    f"{_log_tail(log_path)}",
                    code=code,
                    stage=ERROR_CODES[code].stage,
                )
            if returncode != 0:
                raise RenderError(
                    f"driver exited with {returncode}{_log_tail(log_path)}",
                    code="render_failed",
                    stage="render",
                )
            if report.get("terminal") != "completed" or not report.get("finished"):
                raise RenderError(
                    f"driver did not reach completed: {report.get('terminal')}",
                    code="render_failed",
                    stage="render",
                )
            if int(report.get("frames", -1)) != plan.total_frames:
                raise RenderError(
                    f"expected {plan.total_frames} frames, driver reported {report.get('frames')}",
                    code="frame_mismatch",
                    stage="output",
                )
            manifest = build_frame_manifest(
                build_id=build_id,
                asset_id=spec.visual_id,
                plan=plan,
                scene_ids=scenes.scene_ids,
                frames_dir=frames_dir,
                build_root=build_root,
                width=video.width,
                height=video.height,
            )
            manifest_path = write_frame_manifest(manifest, build_root / "frame_manifest.json")
            # The manifest is evidence, not proof: re-hash and re-decode the
            # files it lists before the build is called complete.
            problems = verify_frame_manifest(
                manifest,
                build_root=build_root,
                frames_dir=frames_dir,
                plan=plan,
                decode_frames=self.decode_frames,
            )
            if problems:
                raise RenderError("; ".join(problems), code="qa_failed", stage="qa")

            if self._cancel.is_set():
                raise RenderCancelled(f"build {build_id} was cancelled")

            # Encode into a sibling staging directory, verify, then replace
            # atomically. Nothing touches the published path until every check
            # has passed, so a failed build cannot damage an older video.
            if publish_root is not None:
                media_dir = publish_root / "build" / "media"
                final_video = publish_root / video.output_path
                _require_no_symlink_components(media_dir, publish_root, what="media directory")
            else:
                media_dir = base_dir / "media"
                final_video = media_dir / "course.mp4"
                if project_root is not None:
                    _require_no_symlink_components(media_dir, project_root, what="media directory")
            staging_dir = media_dir / f".staging-{build_id}"
            staging_dir.mkdir(parents=True, exist_ok=True)
            staged_video = staging_dir / "course.mp4"
            encode_frames(manifest, build_root=build_root, output=staged_video)
            video_problems = verify_video_against_manifest(staged_video, manifest)
            if video_problems:
                raise RenderError("; ".join(video_problems), code="qa_failed", stage="qa")
            os.replace(staged_video, final_video)
            try:
                staging_dir.rmdir()
            except OSError:
                pass
            qa_paths: tuple[Path, ...] = ()
            if project_root is not None:
                qa_dir = project_root / "internal" / "qa"
                qa_dir.mkdir(parents=True, exist_ok=True)
                qa_manifest = write_json(qa_dir / "frame_manifest.json", manifest)
                qa_report = write_json(
                    qa_dir / "encode_report.json",
                    encode_report(
                        manifest,
                        output=final_video,
                        command=build_encode_command(
                            manifest,
                            build_root=build_root,
                            output=staged_video,
                            ffmpeg_bin=ffmpeg_path() or "ffmpeg",
                        ),
                        manifest_sha256=sha256_file(manifest_path),
                    ),
                )
                qa_paths = (qa_manifest, qa_report)

            self._diagnostics.append(f"build {build_id}: completed")
            self._last = {
                "build_id": build_id,
                "visual_id": spec.visual_id,
                "frames": plan.total_frames,
                "report": report_path,
                "manifest": manifest_path,
                "video": final_video,
            }
            return RenderResult(
                status="completed",
                html="",
                build_id=build_id,
                artifacts=(report_path, manifest_path, final_video, *qa_paths),
                manifest=manifest_path,
            )
        except BaseException as exc:
            self._diagnostics.append(f"build {build_id}: {exc.__class__.__name__}: {exc}")
            raise
        finally:
            with self._lock:
                self._process = None
                self._process_group = None

    def _execute_driver(
        self,
        command: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        log_path: Path,
        timeout_s: float,
    ) -> tuple[str, int]:
        """Run the driver; return ``(forced, returncode)``.

        ``forced`` is ``""``, ``"cancelled"``, or ``"render_timeout"``. The
        whole process group is terminated, so Vite and Chromium cannot keep
        writing frames after the caller gave up.
        """

        deadline = time.monotonic() + timeout_s
        with log_path.open("wb") as log:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            with self._lock:
                self._process = process
                self._process_group = pgid = _process_group(process)
            forced = ""
            while True:
                code = process.poll()
                if code is not None:
                    if self._cancel.is_set():
                        forced = "cancelled"
                    if not _stop_driver(process, pgid):
                        raise RenderError(
                            f"driver process group {pgid} did not exit after the driver stopped",
                            code="render_failed",
                            stage="render",
                        )
                    self._diagnostics.append(
                        f"build {env.get('BUILD_ID', '?')}: process group {pgid} cleaned"
                    )
                    return forced, code
                if self._cancel.is_set():
                    forced = "cancelled"
                elif time.monotonic() > deadline:
                    forced = "render_timeout"
                if forced:
                    if not _stop_driver(process, pgid):
                        raise RenderError(
                            f"driver process group {pgid} did not exit after {forced}",
                            code="render_failed",
                            stage="render",
                        )
                    self._diagnostics.append(
                        f"build {env.get('BUILD_ID', '?')}: "
                        f"process group {pgid} cleaned after {forced}"
                    )
                    return forced, process.returncode if process.returncode is not None else -1
                time.sleep(0.1)

    def cancel(self) -> None:
        """Idempotent: set the flag and terminate the current process group."""

        self._cancel.set()
        with self._lock:
            process = self._process
            pgid = self._process_group
        if process is not None:
            _stop_driver(process, pgid)

    def collect_outputs(self, spec: VisualSpec, context: RenderContext) -> list[Path]:
        artifacts: list[Path] = []
        for key in ("report", "manifest", "video"):
            path = self._last.get(key)
            if isinstance(path, Path) and path.is_file():
                artifacts.append(path)
        return artifacts

    def validate(
        self, spec: VisualSpec, html: str, context: RenderContext | None = None
    ) -> list[str]:
        """Re-check the recorded build; rendering already verified the frames."""

        if not self._last or self._last.get("visual_id") != spec.visual_id:
            return []
        try:
            _scenes, _video, plan = self._parse(spec)
        except RenderError as exc:
            return [str(exc)]
        if self._last.get("frames") != plan.total_frames:
            return [
                f"build {self._last.get('build_id')}: recorded frames "
                f"{self._last.get('frames')} != {plan.total_frames}"
            ]
        return []

    def get_diagnostics(self) -> list[str]:
        return list(self._diagnostics)


def motion_canvas_registry() -> RendererRegistry:
    """Explicit registry for P1; ``default_registry`` stays untouched."""

    registry = RendererRegistry()
    registry.register(MotionCanvasRenderer())
    return registry


def _build_id() -> str:
    override = os.environ.get("LCES_BUILD_ID", "").strip()
    if override:
        if not BUILD_ID_PATTERN.fullmatch(override):
            raise _invalid("LCES_BUILD_ID must be lowercase letters, digits, or hyphens")
        return override
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return f"build-{stamp}-{secrets.token_hex(3)}"


def _scene_problems(scene: SceneContract, width: int, height: int) -> list[str]:
    problems: list[str] = []
    if scene.scene_type not in SUPPORTED_SCENE_TYPES:
        problems.append(
            f"unsupported scene_type '{scene.scene_type}'; "
            f"P2 supports {sorted(SUPPORTED_SCENE_TYPES)}"
        )
        return problems
    if scene.fallback_policy != "fail":
        problems.append("P2 requires fallback_policy 'fail'")
    if scene.transition_in not in {"cut", "fade"} or scene.transition_out not in {
        "cut",
        "fade",
    }:
        problems.append("P2 supports only cut/fade transitions")
    if scene.source_asset_refs:
        problems.append("P2 scenes accept no source_asset_refs")
    for problem in data_problems(scene.scene_type, scene.data, width, height):
        problems.append(f"scene '{scene.scene_id}': {problem}")
    return problems


def _materialise_project(
    template: Path,
    build_root: Path,
    scene: SceneContract,
    plan: TimelinePlan,
    video: VideoContract,
) -> Path:
    """Copy the pinned Node project and write this build's scene and meta."""

    work = build_root / "project"
    shutil.copytree(
        template,
        work,
        ignore=shutil.ignore_patterns("node_modules", "output", "*.log", ".vite"),
    )
    (work / "node_modules").symlink_to(template / "node_modules", target_is_directory=True)
    write_json(
        work / "src" / "project.meta",
        {
            "version": 0,
            "shared": {
                "background": None,
                "range": [0, plan.range_seconds()],
                "size": {"x": video.width, "y": video.height},
                "audioOffset": 0,
            },
            "preview": {"fps": plan.fps_num / plan.fps_den, "resolutionScale": 1},
            "rendering": {
                "fps": plan.fps_num / plan.fps_den,
                "resolutionScale": 1,
                "colorSpace": "srgb",
                "exporter": {
                    "name": "@motion-canvas/core/image-sequence",
                    "options": {
                        "fileType": "image/png",
                        "quality": 100,
                        "groupByScene": False,
                    },
                },
            },
        },
    )
    (work / "src" / "scenes" / "generated.tsx").write_text(
        _scene_source(scene, plan, width=video.width, height=video.height),
        encoding="utf-8",
        newline="\n",
    )
    return work


def _scene_source(scene: SceneContract, plan: TimelinePlan, *, width: int, height: int) -> str:
    """Delegate to the fixed P2.2 templates; data never becomes code."""

    return scene_source(scene, plan, width=width, height=height)


def _driver_env(
    *,
    output_dir: Path,
    expected_frames: int,
    build_id: str,
    max_render_ms: int,
    home_dir: Path,
    tmp_dir: Path,
) -> dict[str, str]:
    """A whitelisted environment with the host profile pointed at the build.

    HOME, XDG_*, TMPDIR and TMP all move into ``build/motion/<id>/``. The
    editor writes configuration on first use, and those writes must not leak
    into the user's profile or another build. ``PLAYWRIGHT_BROWSERS_PATH``
    stays a host read: browsers are installed once and shared.
    """

    allow = ("PATH", "LANG", "LC_ALL")
    env = {name: os.environ[name] for name in allow if name in os.environ}
    playwright = playwright_browsers_path()
    if playwright:
        env["PLAYWRIGHT_BROWSERS_PATH"] = playwright
    env.update(
        {
            "HOME": str(home_dir),
            "XDG_CONFIG_HOME": str(home_dir / ".config"),
            "XDG_CACHE_HOME": str(home_dir / ".cache"),
            "XDG_DATA_HOME": str(home_dir / ".local" / "share"),
            "XDG_STATE_HOME": str(home_dir / ".local" / "state"),
            "TMPDIR": str(tmp_dir),
            "TMP": str(tmp_dir),
            "TEMP": str(tmp_dir),
            "OUTPUT_DIR": str(output_dir),
            "EXPECTED_FRAMES": str(expected_frames),
            "EXPECTED_EDITOR_VERSION": MOTION_CANVAS_VERSION,
            "BUILD_ID": build_id,
            "MAX_RENDER_MS": str(max_render_ms),
            "LCES_ERROR_CODES_PATH": str(ERROR_CODES_PATH),
            "MC_OUTPUT_DIR": str(output_dir),
            "MC_NODE_MODULES": str(motion_project_dir() / "node_modules"),
        }
    )
    return env


def _log_tail(path: Path, limit: int = 1200) -> str:
    """Keep the end of the driver log in the failure, not only on disk."""

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    tail = text.strip()[-limit:]
    return f"; driver log: {tail}" if tail else ""


def _load_report(path: Path, build_id: str) -> dict[str, Any]:
    if not path.is_file():
        raise RenderError(
            f"build {build_id}: driver wrote no report",
            code="output_missing",
            stage="output",
        )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise RenderError(
            f"build {build_id}: report.json is not readable",
            code="output_corrupt",
            stage="output",
        ) from exc
    if not isinstance(payload, dict):
        raise RenderError(
            f"build {build_id}: report.json is not an object",
            code="output_corrupt",
            stage="output",
        )
    return payload


def _process_group(process: subprocess.Popen[bytes]) -> int | None:
    getpgid = getattr(os, "getpgid", None)
    if getpgid is None:
        return None
    try:
        return int(getpgid(process.pid))
    except ProcessLookupError:
        return None


def _group_alive(pgid: int | None) -> bool:
    """True when the group has a live (non-zombie) member.

    ``killpg(pgid, 0)`` also succeeds for zombies. In containers whose PID 1
    does not reap orphans, a finished Vite/esbuild process can stay a zombie
    forever; treating it as alive would turn every successful render into a
    cleanup failure. On Linux, inspect ``/proc/<pid>/stat`` and ignore ``Z``.
    """

    if pgid is None:
        return False
    proc = Path("/proc")
    if proc.is_dir():
        try:
            for entry in proc.iterdir():
                if not entry.name.isdigit():
                    continue
                try:
                    text = (entry / "stat").read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                close = text.rfind(")")
                if close < 0:
                    continue
                fields = text[close + 2 :].split()
                if len(fields) < 3:
                    continue
                if fields[0] in {"Z", "X", "x"}:
                    continue
                try:
                    group = int(fields[2])
                except ValueError:
                    continue
                if group == pgid:
                    return True
            return False
        except OSError:
            pass
    killpg = getattr(os, "killpg", None)
    if killpg is None:
        return False
    try:
        killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _signal_pgid(pgid: int | None, *, hard: bool) -> None:
    if pgid is None:
        return
    killpg = getattr(os, "killpg", None)
    if killpg is None:
        return
    # The Windows signal stub that mypy checks against has no SIGKILL; this
    # branch only runs on Linux, where it exists.
    sig = signal.SIGKILL if hard else signal.SIGTERM  # type: ignore[attr-defined]
    try:
        killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _signal_group(process: subprocess.Popen[bytes], *, hard: bool) -> None:
    """Signal the whole process group where the platform supports it.

    Vite and Chromium are children of the driver; signalling only the driver
    would leave them writing frames after the caller gave up.
    """

    pgid = _process_group(process)
    if pgid is not None:
        _signal_pgid(pgid, hard=hard)
        return
    if hard:
        process.kill()
    else:
        process.terminate()


def _wait_group_gone(pgid: int | None, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _group_alive(pgid):
            return True
        time.sleep(0.05)
    return not _group_alive(pgid)


def _stop_driver(process: subprocess.Popen[bytes], pgid: int | None) -> bool:
    """Terminate the driver group and prove it has no live members.

    Returns ``False`` when the group outlives the SIGTERM/SIGKILL grace. A
    dead driver process is not enough: Vite and Chromium may still be alive.
    """

    if process.poll() is None:
        if pgid is not None:
            _signal_pgid(pgid, hard=False)
        else:
            _signal_group(process, hard=False)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if pgid is not None:
                _signal_pgid(pgid, hard=True)
            else:
                _signal_group(process, hard=True)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
    if pgid is not None:
        if _wait_group_gone(pgid, 2.0):
            return True
        _signal_pgid(pgid, hard=True)
        return _wait_group_gone(pgid, 2.0)
    return process.poll() is not None
