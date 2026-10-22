"""Motion Canvas adapter: platform gate, input contract, and failure mapping.

These tests never run the real editor. A stub driver writes frames and a
report into the build directory, so the Python side is exercised on any host.
The real render lives in ``test_motion_canvas_e2e.py`` and is Linux-only.
"""

from __future__ import annotations

import json
import zlib
from pathlib import Path

import pytest

from content_studio import motion_canvas as mc
from content_studio.errors import RenderCancelled, RenderError
from content_studio.frame_manifest import png_problems
from content_studio.models import VisualSpec
from content_studio.renderers import RenderContext, default_registry


def _spec(
    *,
    duration_ms: int = 1000,
    scene_type: str = "title",
    width: int = 320,
    height: int = 180,
    fps_num: int = 30,
    fps_den: int = 1,
    scene_data: dict | None = None,
    transition_in: str = "cut",
    transition_out: str = "cut",
    scene_ids: list[str] | None = None,
) -> VisualSpec:
    scene = {
        "scene_id": "scene-001",
        "scene_type": scene_type,
        "duration_ms": duration_ms,
        "transition_in": transition_in,
        "transition_out": transition_out,
        "data": scene_data if scene_data is not None else {"title": "Hello"},
    }
    video = {
        "project_id": "demo",
        "video_id": "course-v1",
        "content_version": "v1",
        "width": width,
        "height": height,
        "fps_num": fps_num,
        "fps_den": fps_den,
        "scene_ids": scene_ids or ["scene-001"],
        "output_path": "build/media/course.mp4",
        "renderer": mc.MotionCanvasRenderer.name,
        "renderer_version": mc.MotionCanvasRenderer.version,
    }
    return VisualSpec(
        visual_id="course-v1",
        visual_type="animation",
        renderer=mc.MotionCanvasRenderer.name,
        data={"scene_set": {"scenes": [scene]}, "video": video},
    )


def _chunk(kind: bytes, payload: bytes) -> bytes:
    crc = zlib.crc32(kind + payload) & 0xFFFFFFFF
    return len(payload).to_bytes(4, "big") + kind + payload + crc.to_bytes(4, "big")


def _png(width: int = 320, height: int = 180) -> bytes:
    header = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    return bytes.fromhex("89504e470d0a1a0a") + _chunk(b"IHDR", header) + _chunk(b"IEND", b"")


class _StubRenderer(mc.MotionCanvasRenderer):
    """Replace only the subprocess; everything else is the real adapter."""

    def __init__(
        self,
        *,
        report: dict | None = None,
        frames: int | None = None,
        png: bytes | None = None,
        returncode: int = 0,
        forced: str = "",
        write_report: bool = True,
    ) -> None:
        super().__init__(max_render_ms=1000, decode_frames=False)
        self.report = report
        self.write_report = write_report
        self.frames = frames
        self.png = png
        self.returncode = returncode
        self.forced = forced
        self.seen: dict | None = None

    def _execute_driver(self, command, *, cwd, env, log_path, timeout_s):
        self.seen = {"command": command, "cwd": cwd, "env": env, "timeout_s": timeout_s}
        log_path.write_text("stub driver\n", encoding="utf-8")
        output = Path(env["OUTPUT_DIR"])
        expected = int(env["EXPECTED_FRAMES"])
        count = self.frames if self.frames is not None else expected
        image = self.png if self.png is not None else _png()
        for index in range(count):
            (output / f"{index:06d}.png").write_bytes(image)
        if self.write_report:
            payload = {
                "schema_version": "1.0",
                "mode": "render",
                "build_id": env["BUILD_ID"],
                "expected_frames": expected,
                "frames": count,
                "finished": True,
                "cancelled": False,
                "timed_out": False,
                "terminal": "completed",
                "error_code": "",
                **(self.report or {}),
            }
            (output / "report.json").write_text(json.dumps(payload), encoding="utf-8")
        return self.forced, self.returncode


@pytest.fixture(autouse=True)
def fake_encoding(monkeypatch):
    """Keep unit tests off FFmpeg; publish tests override this per case."""

    def fake_encode(manifest, *, build_root, output, **kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake-mp4")
        return output

    monkeypatch.setattr(mc, "encode_frames", fake_encode)
    monkeypatch.setattr(mc, "verify_video_against_manifest", lambda video, manifest: [])


@pytest.fixture
def build_root(tmp_path, monkeypatch) -> Path:
    template = tmp_path / "motion-template"
    (template / "src" / "scenes").mkdir(parents=True)
    (template / "node_modules" / "@motion-canvas" / "core").mkdir(parents=True)
    (template / "src" / "project.meta").write_text("{}", encoding="utf-8")
    # A minimal, consistent package tree so the lockfile gate sees an
    # ``npm ci`` result; individual tests break it on purpose.
    declared = {"dependencies": {"@motion-canvas/core": "3.17.2"}, "devDependencies": {}}
    (template / "package.json").write_text(json.dumps(declared), encoding="utf-8")
    (template / "package-lock.json").write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "": declared,
                    "node_modules/@motion-canvas/core": {"version": "3.17.2"},
                },
            }
        ),
        encoding="utf-8",
    )
    (template / "node_modules" / "@motion-canvas" / "core" / "package.json").write_text(
        json.dumps({"version": "3.17.2"}), encoding="utf-8"
    )

    def fake_materialise(template_path, build, scene, plan, video):
        work = build / "project"
        (work / "src" / "scenes").mkdir(parents=True)
        (work / "src" / "project.meta").write_text(
            json.dumps({"range": [0, plan.range_seconds()]}), encoding="utf-8"
        )
        (work / "src" / "scenes" / "generated.tsx").write_text(
            mc._scene_source(scene, plan, width=video.width, height=video.height),
            encoding="utf-8",
        )
        return work

    monkeypatch.setattr(mc, "motion_project_dir", lambda: template)
    monkeypatch.setattr(mc, "node_binary", lambda: "node-stub")
    monkeypatch.setattr(mc, "_materialise_project", fake_materialise)
    return tmp_path / "build"


# -- environment ---------------------------------------------------------


def test_platform_gate_uses_unsupported_platform(monkeypatch):
    monkeypatch.setattr(mc.sys, "platform", "win32")
    renderer = mc.MotionCanvasRenderer()
    assert renderer.environment_error_code() == "unsupported_platform"


def test_registry_refuses_a_non_linux_host(monkeypatch):
    monkeypatch.setattr(mc.sys, "platform", "win32")
    monkeypatch.setattr(
        mc,
        "environment_report",
        lambda: [
            mc.DependencyStatus("platform", "linux", "win32", False, "Linux only"),
        ],
    )
    with pytest.raises(RenderError) as caught:
        mc.motion_canvas_registry().render(_spec())
    assert caught.value.code == "unsupported_platform"
    assert caught.value.terminal == "failed"


def test_environment_failures_map_to_environment_unavailable(monkeypatch):
    monkeypatch.setattr(mc.sys, "platform", "linux")
    monkeypatch.setattr(
        mc,
        "environment_report",
        lambda: [
            mc.DependencyStatus("node", "24.22.1", "22.22.2", False, "install 24.22.1"),
        ],
    )
    with pytest.raises(RenderError) as caught:
        mc.motion_canvas_registry().render(_spec())
    assert caught.value.code == "environment_unavailable"


def test_node_override_must_exist(monkeypatch):
    monkeypatch.setenv("LCES_NODE_BIN", "/nonexistent/node")
    assert mc.node_binary() is None


def test_dependency_problems_accept_a_clean_tree(build_root):
    assert mc.dependency_problems(mc.motion_project_dir()) == []


def test_dependency_problems_detect_a_rewritten_tree(build_root):
    installed = mc.motion_project_dir() / "node_modules" / "@motion-canvas" / "core"
    (installed / "package.json").write_text(json.dumps({"version": "3.17.1"}), encoding="utf-8")
    problems = mc.dependency_problems(mc.motion_project_dir())
    assert any("@motion-canvas/core" in problem and "3.17.1" in problem for problem in problems)


def test_dependency_problems_detect_an_unpinned_dependency(build_root):
    template = mc.motion_project_dir()
    package = json.loads((template / "package.json").read_text(encoding="utf-8"))
    package["dependencies"]["left-pad"] = "1.3.0"
    (template / "package.json").write_text(json.dumps(package), encoding="utf-8")
    (template / "package-lock.json").write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "": package,
                    "node_modules/@motion-canvas/core": {"version": "3.17.2"},
                },
            }
        ),
        encoding="utf-8",
    )
    problems = mc.dependency_problems(template)
    assert any("left-pad" in problem and "not pinned" in problem for problem in problems)


def test_registry_maps_dependency_mismatch(monkeypatch):
    monkeypatch.setattr(mc.sys, "platform", "linux")
    monkeypatch.setattr(
        mc,
        "environment_report",
        lambda: [
            mc.DependencyStatus(
                "dependencies",
                "package-lock.json tree",
                "1 issue",
                False,
                "run npm ci",
                code="dependency_mismatch",
            )
        ],
    )
    with pytest.raises(RenderError) as caught:
        mc.motion_canvas_registry().render(_spec())
    assert caught.value.code == "dependency_mismatch"
    assert caught.value.stage == "environment"


def test_animation_is_in_the_default_registry():
    registry = default_registry()
    assert "animation" in registry.known_types()
    assert registry.resolve("animation").name == mc.MotionCanvasRenderer.name


# -- input ---------------------------------------------------------------


def test_valid_spec_has_no_problems():
    assert mc.MotionCanvasRenderer().validate_input(_spec()) == []


def test_unknown_scene_type_is_rejected():
    problems = mc.MotionCanvasRenderer().validate_input(_spec(scene_type="flow"))
    assert any("scene_type 'title'" in problem for problem in problems)


def test_scene_ids_must_match_the_video_contract():
    problems = mc.MotionCanvasRenderer().validate_input(_spec(scene_ids=["scene-other"]))
    assert any("scene_ids" in problem for problem in problems)


def test_zero_frame_duration_is_rejected():
    problems = mc.MotionCanvasRenderer().validate_input(_spec(duration_ms=10))
    assert any("0 frames" in problem for problem in problems)


def test_zoom_transition_is_rejected():
    problems = mc.MotionCanvasRenderer().validate_input(_spec(transition_in="zoom"))
    assert any("cut/fade" in problem for problem in problems)


def test_missing_title_is_rejected():
    problems = mc.MotionCanvasRenderer().validate_input(_spec(scene_data={"subtitle": "x"}))
    assert any("data.title" in problem for problem in problems)


def test_bad_colour_is_rejected():
    problems = mc.MotionCanvasRenderer().validate_input(
        _spec(scene_data={"title": "Hi", "accent_color": "cyan"})
    )
    assert any("accent_color" in problem for problem in problems)


def test_scene_payload_cannot_carry_assets_in_p1():
    spec = _spec(scene_data={"title": "Hi"})
    spec.data["scene_set"]["scenes"][0]["source_asset_refs"] = ["content/other.svg"]
    problems = mc.MotionCanvasRenderer().validate_input(spec)
    assert any("source_asset_refs" in problem for problem in problems)


# -- render --------------------------------------------------------------


def _render(
    renderer: mc.MotionCanvasRenderer,
    root: Path,
    spec: VisualSpec | None = None,
    project: Path | None = None,
):
    spec = spec or _spec()
    return renderer.render(
        spec,
        RenderContext(project_dir=project, output_dir=root, publish=project is not None),
    )


def test_render_returns_build_id_and_report(build_root):
    renderer = _StubRenderer()
    result = _render(renderer, build_root)
    assert result.status == "completed"
    assert mc.BUILD_ID_PATTERN.fullmatch(result.build_id)
    assert result.artifacts and result.artifacts[0].name == "report.json"
    assert result.manifest is not None and result.manifest.is_file()
    assert renderer.seen is not None
    assert renderer.seen["env"]["EXPECTED_FRAMES"] == "30"
    assert renderer.seen["command"][1] == "driver.mjs"
    # The exporter and the frame counter must agree on one absolute directory,
    # and Vite must be allowed to read the pinned node_modules.
    assert renderer.seen["env"]["MC_OUTPUT_DIR"] == renderer.seen["env"]["OUTPUT_DIR"]
    assert renderer.seen["env"]["MC_NODE_MODULES"].endswith("node_modules")
    # The driver env is a whitelist: no API keys leak into the Node process.
    leaked = [name for name in renderer.seen["env"] if "KEY" in name.upper()]
    assert leaked == []


def test_frame_shortfall_is_a_frame_mismatch(build_root):
    renderer = _StubRenderer(report={"frames": 29})
    with pytest.raises(RenderError) as caught:
        _render(renderer, build_root)
    assert caught.value.code == "frame_mismatch"


def test_missing_frames_are_a_frame_mismatch(build_root):
    renderer = _StubRenderer(frames=29, report={"frames": 30})
    with pytest.raises(RenderError) as caught:
        _render(renderer, build_root)
    assert caught.value.code == "frame_mismatch"


def test_truncated_png_is_output_corrupt(build_root):
    renderer = _StubRenderer(png=_png()[:20])
    with pytest.raises(RenderError) as caught:
        _render(renderer, build_root)
    assert caught.value.code == "output_corrupt"


def test_driver_error_code_is_preserved(build_root):
    renderer = _StubRenderer(
        report={"error_code": "driver_protocol_mismatch", "terminal": "failed", "finished": False}
    )
    with pytest.raises(RenderError) as caught:
        _render(renderer, build_root)
    assert caught.value.code == "driver_protocol_mismatch"


def test_unknown_driver_code_falls_back_to_render_failed(build_root):
    renderer = _StubRenderer(report={"error_code": "made_up"})
    with pytest.raises(RenderError) as caught:
        _render(renderer, build_root)
    assert caught.value.code == "render_failed"


def test_missing_report_is_output_missing(build_root):
    renderer = _StubRenderer(write_report=False)
    with pytest.raises(RenderError) as caught:
        _render(renderer, build_root)
    assert caught.value.code == "output_missing"


def test_non_zero_exit_is_render_failed(build_root):
    renderer = _StubRenderer(returncode=5)
    with pytest.raises(RenderError) as caught:
        _render(renderer, build_root)
    assert caught.value.code == "render_failed"


def test_cancellation_has_its_own_terminal_state(build_root):
    renderer = _StubRenderer(forced="cancelled", returncode=130)
    with pytest.raises(RenderCancelled) as caught:
        _render(renderer, build_root)
    assert caught.value.terminal == "cancelled"


class _CancelOnExitStub(_StubRenderer):
    """The driver dies from the cancel signal before writing a clean report."""

    def _execute_driver(self, command, *, cwd, env, log_path, timeout_s):
        self._cancel.set()
        self.report = {"error_code": "render_failed", "terminal": "failed", "finished": False}
        return super()._execute_driver(
            command, cwd=cwd, env=env, log_path=log_path, timeout_s=timeout_s
        )


def test_cancel_wins_over_the_drivers_failure_report(build_root):
    """A killed driver must not turn the caller's cancel into ``render_failed``."""

    with pytest.raises(RenderCancelled):
        _render(_CancelOnExitStub(), build_root)


def test_timeout_maps_to_render_timeout(build_root):
    renderer = _StubRenderer(forced="render_timeout")
    with pytest.raises(RenderError) as caught:
        _render(renderer, build_root)
    assert caught.value.code == "render_timeout"


def test_cancel_is_idempotent():
    renderer = mc.MotionCanvasRenderer()
    renderer.cancel()
    renderer.cancel()
    assert renderer._cancel.is_set()


def test_one_build_at_a_time(build_root):
    renderer = _StubRenderer()
    renderer._process = object()  # type: ignore[assignment]
    with pytest.raises(RenderError, match="one build at a time"):
        _render(renderer, build_root)
    renderer._process = None


def test_build_directory_is_inside_the_project(build_root):
    renderer = _StubRenderer()
    result = _render(renderer, build_root)
    report = result.artifacts[0].resolve()
    assert build_root.resolve() in report.parents


def test_dependency_mismatch_blocks_before_any_output(build_root):
    installed = mc.motion_project_dir() / "node_modules" / "@motion-canvas" / "core"
    (installed / "package.json").write_text(json.dumps({"version": "3.17.1"}), encoding="utf-8")
    with pytest.raises(RenderError) as caught:
        _render(_StubRenderer(), build_root)
    assert caught.value.code == "dependency_mismatch"
    assert not build_root.exists()


@pytest.mark.parametrize(
    ("stub", "expected_code"),
    [
        ({"frames": 29, "report": {"frames": 30}}, "frame_mismatch"),
        ({"png": _png()[:20]}, "output_corrupt"),
        ({"write_report": False}, "output_missing"),
        ({"returncode": 5}, "render_failed"),
        ({"forced": "render_timeout"}, "render_timeout"),
        ({"forced": "cancelled", "returncode": 130}, "cancelled"),
    ],
)
def test_every_failure_publishes_nothing(build_root, tmp_path, stub, expected_code):
    """Fault matrix: one terminal state, no published video, no QA evidence.

    The old video is a sentinel: a failed build must not replace it, and a
    failed build must not leave the manifest/encode evidence that Gate 4
    would read as a successful publication.
    """

    project = tmp_path / "project"
    media = project / "build" / "media"
    media.mkdir(parents=True)
    sentinel = media / "course.mp4"
    sentinel.write_bytes(b"old-video")
    (project / "content").mkdir(parents=True)

    with pytest.raises(RenderError) as caught:
        _render(_StubRenderer(**stub), build_root, project=project)

    assert caught.value.code == expected_code
    assert caught.value.terminal in {"failed", "cancelled"}
    assert sentinel.read_bytes() == b"old-video"
    assert sorted(path.name for path in media.glob("*.mp4")) == ["course.mp4"]
    assert not (project / "internal" / "qa" / "frame_manifest.json").exists()
    assert not (project / "internal" / "qa" / "encode_report.json").exists()


# -- generated scene -----------------------------------------------------


def test_scene_source_escapes_template_data():
    spec = _spec(scene_data={"title": 'He said "</script>"', "subtitle": "line\nbreak"})
    renderer = mc.MotionCanvasRenderer()
    scenes, video, plan = renderer._parse(spec)
    source = mc._scene_source(scenes.scenes[0], plan, width=video.width, height=video.height)
    assert '"He said \\"</script>\\""' in source
    assert "line\\nbreak" in source
    assert source.count("export default makeScene2D") == 1


def test_scene_source_uses_the_contract_canvas():
    renderer = mc.MotionCanvasRenderer()
    scenes, video, plan = renderer._parse(_spec(width=640, height=360))
    source = mc._scene_source(scenes.scenes[0], plan, width=640, height=360)
    assert "width={640} height={360}" in source
    assert "DURATION = 1.0" in source


# -- frame checks --------------------------------------------------------


def test_png_crc_mismatch_is_detected(tmp_path):
    broken = bytearray(_png())
    broken[-1] ^= 0xFF
    path = tmp_path / "000000.png"
    path.write_bytes(bytes(broken))
    assert any("CRC mismatch" in problem for problem in png_problems(path, 320, 180))


def test_png_dimension_mismatch_is_detected(tmp_path):
    path = tmp_path / "000000.png"
    path.write_bytes(_png(640, 360))
    assert any("does not match" in problem for problem in png_problems(path, 320, 180))


def test_animation_asset_contract_records_video_manifest_and_build_id(tmp_path):
    from content_studio.visuals import RenderedVisual, _asset_contracts

    project = tmp_path / "project"
    (project / "content" / "scenes").mkdir(parents=True)
    (project / "build" / "media").mkdir(parents=True)
    (project / "internal" / "qa").mkdir(parents=True)
    scene = project / "content" / "scenes" / "course.json"
    scene.write_text("{}", encoding="utf-8")
    video = project / "build" / "media" / "course.mp4"
    video.write_bytes(b"video")
    manifest = project / "internal" / "qa" / "frame_manifest.json"
    manifest.write_text("{}", encoding="utf-8")
    report = project / "internal" / "qa" / "encode_report.json"
    report.write_text("{}", encoding="utf-8")
    spec = VisualSpec(
        visual_id="slide-001-block-01",
        visual_type="animation",
        data={"source_path": "content/scenes/course.json"},
    )
    rendered = RenderedVisual(
        slide_id="slide-001",
        block_index=1,
        spec=spec,
        html="",
        renderer="motion_canvas.renderer",
        renderer_version="0.1.0",
        output_sha256="",
        artifacts=(video, manifest, report, project / "build" / "ephemeral.log"),
        build_id="build-001",
    )
    assets = _asset_contracts(project, [rendered], None)
    assert assets[0].asset_type == "animation"
    assert assets[0].source == "content/scenes/course.json"
    assert assets[0].build_id == "build-001"
    assert set(assets[0].output_hashes) == {
        "build/media/course.mp4",
        "internal/qa/frame_manifest.json",
        "internal/qa/encode_report.json",
    }


def test_publish_writes_the_video_and_qa_evidence(build_root, tmp_path):
    project = tmp_path / "project"
    media = project / "build" / "media"
    media.mkdir(parents=True)
    (media / "course.mp4").write_bytes(b"old-video")
    (project / "content").mkdir(parents=True)

    result = _render(_StubRenderer(), build_root, project=project)

    assert (media / "course.mp4").read_bytes() == b"fake-mp4"
    assert (project / "internal" / "qa" / "frame_manifest.json").is_file()
    assert (project / "internal" / "qa" / "encode_report.json").is_file()
    assert media / "course.mp4" in result.artifacts


def test_encode_failure_keeps_the_old_video(build_root, tmp_path, monkeypatch):
    project = tmp_path / "project"
    media = project / "build" / "media"
    media.mkdir(parents=True)
    sentinel = media / "course.mp4"
    sentinel.write_bytes(b"old-video")
    (project / "content").mkdir(parents=True)

    def fail(*args, **kwargs):
        raise RenderError("ffmpeg exploded", code="encode_failed", stage="encode")

    monkeypatch.setattr(mc, "encode_frames", fail)
    with pytest.raises(RenderError) as caught:
        _render(_StubRenderer(), build_root, project=project)
    assert caught.value.code == "encode_failed"
    assert sentinel.read_bytes() == b"old-video"
    assert not (project / "internal" / "qa" / "frame_manifest.json").exists()


def test_video_mismatch_keeps_the_old_video(build_root, tmp_path, monkeypatch):
    project = tmp_path / "project"
    media = project / "build" / "media"
    media.mkdir(parents=True)
    sentinel = media / "course.mp4"
    sentinel.write_bytes(b"old-video")
    (project / "content").mkdir(parents=True)

    monkeypatch.setattr(
        mc, "verify_video_against_manifest", lambda video, manifest: ["frames differ"]
    )
    with pytest.raises(RenderError) as caught:
        _render(_StubRenderer(), build_root, project=project)
    assert caught.value.code == "qa_failed"
    assert sentinel.read_bytes() == b"old-video"
    assert not (project / "internal" / "qa" / "frame_manifest.json").exists()
