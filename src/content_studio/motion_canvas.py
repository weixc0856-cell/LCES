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
import zlib
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from content_studio.errors import (
    ERROR_CODES,
    ERROR_CODES_PATH,
    RenderCancelled,
    RenderError,
)
from content_studio.models import SceneContract, SceneSet, VideoContract, VisualSpec
from content_studio.paths import repository_root
from content_studio.renderers import (
    RenderContext,
    Renderer,
    RendererRegistry,
    RenderResult,
    ResourceEstimate,
)
from content_studio.timeline import TimelinePlan, plan_from_scenes
from content_studio.utils import write_json

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
HEX_COLOUR = re.compile(r"^#[0-9a-fA-F]{6}$")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_FRAME_NAME = re.compile(r"^\d{6}\.png$")


@dataclass(frozen=True)
class DependencyStatus:
    name: str
    expected: str
    actual: str
    ok: bool = True
    hint: str = ""

    def message(self) -> str:
        actual = self.actual or "missing"
        suffix = f"; {self.hint}" if self.hint else ""
        return f"{self.name}: expected {self.expected}, found {actual}{suffix}"


def motion_project_dir() -> Path:
    return repository_root() / "motion"


def node_binary() -> str | None:
    """Controlled executable path: ``LCES_NODE_BIN`` or ``node`` on PATH."""

    override = os.environ.get("LCES_NODE_BIN", "").strip()
    if override:
        return override if Path(override).is_file() else None
    return shutil.which("node")


def _run_probe(command: list[str], *, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        command, capture_output=True, text=True, timeout=20, check=False, cwd=cwd
    )
    return (completed.stdout or completed.stderr or "").strip()


def _package_version(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    version = payload.get("version")
    return version if isinstance(version, str) else ""


def _ffmpeg_version(binary: str | None) -> str:
    if binary is None:
        return ""
    try:
        output = _run_probe([binary, "-version"])
    except (OSError, subprocess.TimeoutExpired):
        return ""
    match = re.search(r"ffmpeg version (\d+\.\d+(?:\.\d+)?)", output)
    return match.group(1) if match else ""


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
    ffmpeg = shutil.which("ffmpeg")
    ffmpeg_version = _ffmpeg_version(ffmpeg)
    chromium = _chromium_problem(node, project)

    platform_ok = sys.platform in SUPPORTED_PLATFORMS
    return [
        DependencyStatus(
            name="platform",
            expected="linux",
            actual=sys.platform,
            ok=platform_ok,
            hint="P1 is Linux-only; Windows support requires a new P0 and re-admission",
        ),
        DependencyStatus(
            name="node",
            expected=NODE_VERSION,
            actual=node_version,
            ok=node_version == NODE_VERSION,
            hint="install Node 24.22.1 and set LCES_NODE_BIN if it is not on PATH",
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
            name="ffmpeg",
            expected=f">= {MIN_FFMPEG[0]}.{MIN_FFMPEG[1]}",
            actual=ffmpeg_version,
            ok=bool(ffmpeg_version) and _version_tuple(ffmpeg_version)[:2] >= MIN_FFMPEG,
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

    def __init__(self, *, max_render_ms: int = DEFAULT_MAX_RENDER_MS) -> None:
        self.max_render_ms = max_render_ms
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._process: subprocess.Popen[bytes] | None = None
        self._diagnostics: list[str] = []
        self._last: dict[str, Any] = {}

    # -- environment -----------------------------------------------------

    def check_environment(self) -> list[str]:
        return [item.message() for item in environment_report() if not item.ok]

    def environment_error_code(self) -> str:
        if sys.platform not in SUPPORTED_PLATFORMS:
            return "unsupported_platform"
        return "environment_unavailable"

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
            problems.extend(_scene_problems(scene))
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
        build_id = _build_id()
        build_root = context.output_dir / "motion" / build_id
        if build_root.exists():
            raise _invalid(f"build directory already exists: {build_root.name}")
        project = motion_project_dir()
        if not (project / "node_modules").is_dir():
            raise RenderError(
                "motion/node_modules is missing; run `npm ci` in motion/",
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
            frames_dir = build_root / "frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            env = _driver_env(
                output_dir=frames_dir,
                expected_frames=plan.total_frames,
                build_id=build_id,
                max_render_ms=self.max_render_ms,
            )
            log_path = build_root / "driver.log"
            command = [node_binary() or "node", "driver.mjs"]
            self._diagnostics.append(f"build {build_id}: driver {command[-1]}")
            forced, returncode = self._execute_driver(
                command,
                cwd=work,
                env=env,
                log_path=log_path,
                timeout_s=self.max_render_ms / 1000,
            )
            if forced == "cancelled":
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
            problems = _frame_problems(frames_dir, plan.total_frames, video.width, video.height)
            if problems:
                raise RenderError("; ".join(problems), code="output_corrupt", stage="output")

            self._diagnostics.append(f"build {build_id}: completed")
            self._last = {
                "build_id": build_id,
                "visual_id": spec.visual_id,
                "frames": plan.total_frames,
                "report": report_path,
            }
            return RenderResult(
                status="completed",
                html="",
                build_id=build_id,
                artifacts=(report_path,),
            )
        except BaseException as exc:
            self._diagnostics.append(f"build {build_id}: {exc.__class__.__name__}: {exc}")
            raise
        finally:
            with self._lock:
                self._process = None

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
            forced = ""
            while True:
                code = process.poll()
                if code is not None:
                    return forced, code
                if self._cancel.is_set():
                    forced = "cancelled"
                elif time.monotonic() > deadline:
                    forced = "render_timeout"
                if forced:
                    _terminate(process)
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        pass
                    return forced, process.returncode if process.returncode is not None else -1
                time.sleep(0.1)

    def cancel(self) -> None:
        """Idempotent: set the flag and terminate the current process group."""

        self._cancel.set()
        with self._lock:
            process = self._process
        if process is not None:
            _terminate(process)

    def collect_outputs(self, spec: VisualSpec, context: RenderContext) -> list[Path]:
        report = self._last.get("report")
        return [report] if isinstance(report, Path) and report.is_file() else []

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


def _invalid(message: str) -> RenderError:
    return RenderError(message, code="invalid_input", stage="input")


def _build_id() -> str:
    override = os.environ.get("LCES_BUILD_ID", "").strip()
    if override:
        if not BUILD_ID_PATTERN.fullmatch(override):
            raise _invalid("LCES_BUILD_ID must be lowercase letters, digits, or hyphens")
        return override
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    return f"build-{stamp}-{secrets.token_hex(3)}"


def _scene_problems(scene: SceneContract) -> list[str]:
    problems: list[str] = []
    if scene.scene_type != "title":
        problems.append(f"P1 supports scene_type 'title', not '{scene.scene_type}'")
    if scene.fallback_policy != "fail":
        problems.append("P1 requires fallback_policy 'fail'")
    if scene.transition_in not in {"cut", "fade"} or scene.transition_out not in {
        "cut",
        "fade",
    }:
        problems.append("P1 supports only cut/fade transitions")
    if scene.source_asset_refs:
        problems.append("P1 title scenes accept no source_asset_refs")
    data = scene.data
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        problems.append(f"scene '{scene.scene_id}': data.title must be a non-empty string")
    elif len(title) > 200:
        problems.append(f"scene '{scene.scene_id}': data.title exceeds 200 characters")
    subtitle = data.get("subtitle", "")
    if not isinstance(subtitle, str) or len(subtitle) > 200:
        problems.append(f"scene '{scene.scene_id}': data.subtitle must be a string <= 200")
    for key in ("accent_color", "background_color"):
        value = data.get(key)
        if value is not None and (not isinstance(value, str) or not HEX_COLOUR.fullmatch(value)):
            problems.append(f"scene '{scene.scene_id}': data.{key} must be #rrggbb")
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
    """Deterministic template output; never model-authored TypeScript."""

    data = scene.data
    title = _ts_string(str(data.get("title", "")))
    subtitle = _ts_string(str(data.get("subtitle", "")))
    accent = _ts_string(str(data.get("accent_color", "#4cc9f0")))
    background = _ts_string(str(data.get("background_color", "#0b1220")))
    duration = float(Fraction(plan.total_frames * plan.fps_den, plan.fps_num))
    return f"""// Generated by content_studio.motion_canvas from SceneContract.data.
// Scene: {scene.scene_id} | {plan.total_frames} frames @ {plan.fps_num}/{plan.fps_den} fps
// Do not edit by hand.
import {{Layout, Rect, Txt, makeScene2D}} from '@motion-canvas/2d';
import {{all, createRef, easeOutCubic, waitFor}} from '@motion-canvas/core';

const TITLE = {title};
const SUBTITLE = {subtitle};
const ACCENT = {accent};
const BACKGROUND = {background};
const DURATION = {duration!r};

export default makeScene2D(function* (view) {{
  const title = createRef<Txt>();
  const subtitle = createRef<Txt>();
  view.fill(BACKGROUND);
  view.add(
    <Layout>
      <Rect width={{{width}}} height={{{height}}} fill={{BACKGROUND}} />
      <Rect y={{-170}} width={{560}} height={{8}} fill={{ACCENT}} />
      <Txt ref={{title}} y={{-20}} opacity={{0}} fontSize={{96}}
        fill={{'#f7fbff'}} text={{TITLE}} />
      <Txt ref={{subtitle}} y={{110}} opacity={{0}} fontSize={{42}}
        fill={{'#9fb3c8'}} text={{SUBTITLE}} />
    </Layout>,
  );
  yield* all(title().opacity(1, 0.8, easeOutCubic), title().y(-70, 0.8, easeOutCubic));
  yield* subtitle().opacity(1, 0.6, easeOutCubic);
  yield* waitFor(Math.max(0, DURATION - 1.4));
}});
"""


def _ts_string(value: str) -> str:
    # JSON string literals are valid TypeScript; ensure_ascii also escapes
    # U+2028/U+2029, which some JS parsers treat as line breaks.
    return json.dumps(value, ensure_ascii=True)


def _driver_env(
    *, output_dir: Path, expected_frames: int, build_id: str, max_render_ms: int
) -> dict[str, str]:
    allow = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TMP", "TEMP")
    env = {name: os.environ[name] for name in allow if name in os.environ}
    playwright = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if playwright:
        env["PLAYWRIGHT_BROWSERS_PATH"] = playwright
    env.update(
        {
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


def _signal_group(process: subprocess.Popen[bytes], *, hard: bool) -> None:
    """Signal the whole process group where the platform supports it.

    Vite and Chromium are children of the driver; signalling only the driver
    would leave them writing frames after the caller gave up.
    """

    killpg = getattr(os, "killpg", None)
    getpgid = getattr(os, "getpgid", None)
    if killpg is not None and getpgid is not None:
        # The Windows signal stub that mypy checks against has no SIGKILL;
        # this branch only runs on Linux, where it exists.
        sig = signal.SIGKILL if hard else signal.SIGTERM  # type: ignore[attr-defined]
        try:
            killpg(getpgid(process.pid), sig)
        except (ProcessLookupError, PermissionError):
            pass
        return
    if hard:
        process.kill()
    else:
        process.terminate()


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    _signal_group(process, hard=False)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _signal_group(process, hard=True)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def _frame_problems(frames_dir: Path, expected: int, width: int, height: int) -> list[str]:
    # The image-sequence exporter writes into a project subdirectory, the same
    # way the driver counts frames recursively. A top-level listing would
    # report zero frames and fail a good build.
    frames = sorted(
        path for path in frames_dir.rglob("*.png") if _FRAME_NAME.match(path.name)
    )
    if len(frames) != expected:
        return [f"expected {expected} frames, found {len(frames)} in the build directory"]
    problems: list[str] = []
    for path in frames:
        issue = _png_problem(path, width, height)
        if issue:
            problems.append(issue)
        if len(problems) >= 5:
            problems.append("further frame problems suppressed")
            break
    return problems


def _png_problem(path: Path, width: int, height: int) -> str:
    data = path.read_bytes()
    if not data.startswith(PNG_SIGNATURE):
        return f"{path.name}: not a PNG"
    offset = 8
    seen_header = False
    seen_end = False
    actual_width = actual_height = 0
    while offset + 12 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "big")
        chunk_type = data[offset + 4 : offset + 8]
        end = offset + 12 + length
        if end > len(data):
            return f"{path.name}: truncated at {chunk_type.decode('latin1', 'replace')}"
        expected_crc = int.from_bytes(data[end - 4 : end], "big")
        actual_crc = zlib.crc32(data[offset + 4 : end - 4]) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            return f"{path.name}: CRC mismatch in {chunk_type.decode('latin1', 'replace')}"
        if not seen_header and chunk_type != b"IHDR":
            return f"{path.name}: does not start with IHDR"
        if chunk_type == b"IHDR":
            seen_header = True
            actual_width = int.from_bytes(data[offset + 8 : offset + 12], "big")
            actual_height = int.from_bytes(data[offset + 12 : offset + 16], "big")
        if chunk_type == b"IEND":
            seen_end = True
            break
        offset = end
    if not seen_header or not seen_end:
        return f"{path.name}: missing IHDR or IEND"
    if (actual_width, actual_height) != (width, height):
        return f"{path.name}: {actual_width}x{actual_height} does not match {width}x{height}"
    return ""
