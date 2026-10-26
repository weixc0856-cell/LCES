"""P2.3-B: filesystem and output-directory boundaries (N01-N05, N07-N11).

The negative matrix in this module defines what each case must reject. This module
covers the cases that need no real render; the two Node-side cases run in
``motion/output-dir.test.mjs``.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner

from content_studio import motion_canvas as mc
from content_studio.cli import app
from content_studio.errors import RenderError, ValidationFailure
from content_studio.frame_manifest import build_frame_manifest
from content_studio.models import AnimationBlock, ProjectConfig
from content_studio.paths import ensure_project_layout
from content_studio.release import approve, build_release, verify_release
from content_studio.rendering import _copy_charts
from content_studio.utils import write_text_atomic
from content_studio.validation import run_release_checks, run_validation
from content_studio.visuals import _animation_spec, verify_build_assets, write_render_manifest
from test_frame_manifest import _build, _plan, _png
from test_motion_canvas import _spec, _StubRenderer
from test_motion_canvas import build_root as build_root  # noqa: F401 - fixture
from test_motion_canvas_e2e import host_home_canary
from test_release import _ready_project

POSIX = os.name == "posix"
requires_symlinks = pytest.mark.skipif(
    not POSIX, reason="creating symlinks requires privileges on Windows"
)


def _symlink(target: Path, link: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except (OSError, NotImplementedError):  # pragma: no cover - host policy
        pytest.skip("this host does not allow symlink creation")


def _scene_block() -> AnimationBlock:
    return AnimationBlock(scene_file="content/scenes/course.json", alt="场景")


def _canary(tmp_path: Path) -> Path:
    secret = tmp_path / "outside" / "secret.json"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text('{"secret": "do-not-read"}', encoding="utf-8")
    return secret


# -- N01/N02: scene file path -------------------------------------------


def test_scene_file_must_not_escape_content_scenes(tmp_path):
    project = ensure_project_layout(tmp_path / "project")
    _canary(tmp_path)
    with pytest.raises(RenderError) as caught:
        _animation_spec(
            "visual",
            AnimationBlock(scene_file="content/scenes/x.json", alt="a"),
            project_dir=project,
            project_id="p",
        )
    assert caught.value.code == "invalid_input"


@requires_symlinks
def test_symlinked_scene_file_is_rejected_without_reading_it(tmp_path):
    project = ensure_project_layout(tmp_path / "project")
    secret = _canary(tmp_path)
    _symlink(secret, project / "content" / "scenes" / "course.json")

    with pytest.raises(RenderError) as caught:
        _animation_spec("visual", _scene_block(), project_dir=project, project_id="p")

    assert caught.value.code == "invalid_input"
    assert "symlink" in str(caught.value)
    assert "do-not-read" not in str(caught.value)


@requires_symlinks
def test_symlinked_scene_directory_is_rejected(tmp_path):
    project = ensure_project_layout(tmp_path / "project")
    external = tmp_path / "external-scenes"
    external.mkdir()
    (external / "course.json").write_text("{}", encoding="utf-8")
    (project / "content" / "scenes").rmdir()
    _symlink(external, project / "content" / "scenes", directory=True)

    with pytest.raises(RenderError) as caught:
        _animation_spec("visual", _scene_block(), project_dir=project, project_id="p")

    assert caught.value.code == "invalid_input"
    assert "symlink" in str(caught.value)


# -- N04/N07: output directory ------------------------------------------


@requires_symlinks
def test_output_directory_symlink_is_rejected(tmp_path):
    project = ensure_project_layout(tmp_path / "project")
    outside = tmp_path / "outside"
    outside.mkdir()
    out = project / "build" / "render"
    _symlink(outside, out, directory=True)

    renderer = _StubRenderer()
    with pytest.raises(RenderError) as caught:
        renderer.render(_spec(), mc.RenderContext(project_dir=project, output_dir=out))

    assert caught.value.code == "invalid_input"
    assert not any(outside.iterdir())


def test_output_directory_must_stay_inside_the_project(tmp_path):
    project = ensure_project_layout(tmp_path / "project")
    outside = tmp_path / "outside"

    renderer = _StubRenderer()
    with pytest.raises(RenderError) as caught:
        renderer.render(_spec(), mc.RenderContext(project_dir=project, output_dir=outside))

    assert caught.value.code == "invalid_input"
    assert not outside.exists()


def test_output_directory_must_not_be_a_protected_directory(tmp_path):
    for name in ("input", "internal", "content", "release"):
        project = ensure_project_layout(tmp_path / name / "project")
        renderer = _StubRenderer()
        with pytest.raises(RenderError) as caught:
            renderer.render(
                _spec(), mc.RenderContext(project_dir=project, output_dir=project / name)
            )
        assert caught.value.code == "invalid_input"
        assert not (project / name / "motion").exists()


def test_output_directory_must_not_be_the_project_root(tmp_path):
    project = ensure_project_layout(tmp_path / "project")
    renderer = _StubRenderer()
    with pytest.raises(RenderError) as caught:
        renderer.render(_spec(), mc.RenderContext(project_dir=project, output_dir=project))
    assert caught.value.code == "invalid_input"


def test_render_scene_rejects_out_outside_the_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # The output boundary is checked before any environment probe; neutralise
    # the probe so this case behaves the same on every host.
    monkeypatch.setattr(mc.MotionCanvasRenderer, "check_environment", lambda self: [])
    project = ensure_project_layout(tmp_path / "project")
    (project / "project.yaml").write_text("project_id: demo\ntitle: 示例\n", encoding="utf-8")
    spec = tmp_path / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "scene_set": {
                    "scenes": [
                        {
                            "scene_id": "scene-001",
                            "scene_type": "title",
                            "duration_ms": 1000,
                            "data": {"title": "N04"},
                        }
                    ]
                },
                "video": {
                    "project_id": "demo",
                    "video_id": "course-v1",
                    "content_version": "v1",
                    "width": 640,
                    "height": 360,
                    "fps_num": 30,
                    "fps_den": 1,
                    "scene_ids": ["scene-001"],
                    "output_path": "build/media/course.mp4",
                    "renderer": mc.MotionCanvasRenderer.name,
                    "renderer_version": mc.MotionCanvasRenderer.version,
                },
            }
        ),
        encoding="utf-8",
    )
    outside = tmp_path / "outside"

    result = CliRunner().invoke(
        app, ["render-scene", str(project), str(spec), "--out", str(outside)]
    )

    assert result.exit_code == 13, result.output
    assert "escapes the project" in result.output
    assert not outside.exists()


def test_build_id_cannot_carry_a_path(tmp_path, monkeypatch):
    project = ensure_project_layout(tmp_path / "project")
    renderer = _StubRenderer()
    for value in ("../escape", "Build-x", "a/b", ".."):
        monkeypatch.setenv("LCES_BUILD_ID", value)
        with pytest.raises(RenderError) as caught:
            renderer.render(
                _spec(),
                mc.RenderContext(project_dir=project, output_dir=project / "build"),
            )
        assert caught.value.code == "invalid_input"
    assert not (project / "build" / "motion").exists()


# -- N09: HOME/XDG/TMP isolation ----------------------------------------


def test_driver_environment_isolates_home_and_temp(tmp_path):
    home = tmp_path / "home"
    temporary = tmp_path / "tmp"
    home.mkdir()
    temporary.mkdir()

    env = mc._driver_env(
        output_dir=tmp_path / "frames",
        expected_frames=30,
        build_id="build-20261023-000000-abcdef",
        max_render_ms=1000,
        home_dir=home,
        tmp_dir=temporary,
    )

    assert env["HOME"] == str(home)
    assert env["XDG_CONFIG_HOME"].startswith(str(home))
    assert env["XDG_CACHE_HOME"].startswith(str(home))
    assert env["XDG_DATA_HOME"].startswith(str(home))
    assert env["XDG_STATE_HOME"].startswith(str(home))
    assert env["TMPDIR"] == env["TMP"] == env["TEMP"] == str(temporary)
    assert "USERPROFILE" not in env
    assert env.get("HOME") != os.environ.get("HOME")


def test_render_creates_the_build_home_and_tmp(tmp_path, monkeypatch, build_root):
    seen: dict[str, str] = {}

    def fake_encode(manifest, *, build_root, output, **kwargs):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"fake-mp4")
        return output

    monkeypatch.setattr(mc, "encode_frames", fake_encode)
    monkeypatch.setattr(mc, "verify_video_against_manifest", lambda video, manifest: [])

    def capture(command, *, cwd, env, log_path, timeout_s):
        seen.update(env)
        return _StubRenderer._execute_driver(
            _StubRenderer(), command, cwd=cwd, env=env, log_path=log_path, timeout_s=timeout_s
        )

    renderer = _StubRenderer()
    monkeypatch.setattr(renderer, "_execute_driver", capture)
    renderer.render(_spec(), mc.RenderContext(output_dir=build_root))

    build = next((build_root / "motion").iterdir())
    assert seen["HOME"] == str(build / "home")
    assert seen["TMPDIR"] == str(build / "tmp")
    assert (build / "home").is_dir()
    assert (build / "tmp").is_dir()


# -- N10: frame manifest ------------------------------------------------


@requires_symlinks
def test_symlinked_frame_is_rejected_when_building_the_manifest(tmp_path):
    plan = _plan()
    build_root = tmp_path / "build"
    frames_dir = build_root / "frames"
    frames_dir.mkdir(parents=True)
    external = tmp_path / "outside.png"
    external.write_bytes(_png())
    last = plan.total_frames - 1
    for index in range(last):
        (frames_dir / f"{index:06d}.png").write_bytes(_png())
    _symlink(external, frames_dir / f"{last:06d}.png")

    with pytest.raises(RenderError) as caught:
        build_frame_manifest(
            build_id="build-test-001",
            asset_id="course-v1",
            plan=plan,
            scene_ids=["scene-001", "scene-002"],
            frames_dir=frames_dir,
            build_root=build_root,
            width=320,
            height=180,
        )

    assert caught.value.code == "qa_failed"
    assert external.read_bytes() == _png()


@requires_symlinks
def test_verify_rejects_a_frame_replaced_by_a_symlink(tmp_path):
    build_root, frames_dir, plan, manifest = _build(tmp_path)
    index = manifest.frames[0].index
    target = frames_dir / f"{index:06d}.png"
    copy = tmp_path / "outside.png"
    copy.write_bytes(target.read_bytes())
    target.unlink()
    _symlink(copy, target)

    problems = mc.verify_frame_manifest(
        manifest, build_root=build_root, frames_dir=frames_dir, plan=plan, decode_frames=False
    )

    assert any("symlink" in problem for problem in problems)


# -- N11: charts and release -------------------------------------------


@requires_symlinks
def test_chart_symlink_is_rejected_before_copying(tmp_path):
    project = ensure_project_layout(tmp_path / "project")
    secret = _canary(tmp_path)
    _symlink(secret, project / "content" / "charts" / "leak.svg")
    output = project / "build" / "slides"

    with pytest.raises(RenderError) as caught:
        _copy_charts(project, output)

    assert caught.value.code == "invalid_input"
    assert not (output / "charts").exists()


@requires_symlinks
def test_release_staging_rejects_a_chart_symlink(tmp_path):
    root, config = _ready_project(tmp_path)
    secret = _canary(tmp_path)
    charts = root / "build" / "slides" / "charts"
    charts.mkdir(parents=True)
    _symlink(secret, charts / "leak.svg")
    approve(root, config, "v1", "reviewer")

    with pytest.raises(ValidationFailure) as caught:
        build_release(root, config, "v1")

    assert "symlink" in str(caught.value)
    assert not (root / "release" / "v1").exists()


@requires_symlinks
def test_release_refuses_a_symlinked_build_directory(tmp_path):
    root, config = _ready_project(tmp_path)
    approve(root, config, "v1", "reviewer")
    outside = tmp_path / "outside-build"
    outside.mkdir()
    (outside / "slides").mkdir()
    (outside / "slides" / "index.html").write_text("<html></html>", encoding="utf-8")
    shutil.rmtree(root / "build")
    _symlink(outside, root / "build", directory=True)

    with pytest.raises(ValidationFailure) as caught:
        build_release(root, config, "v1")

    assert "symlink" in str(caught.value)


@requires_symlinks
def test_gate4_rejects_a_symlink_in_the_release_tree(tmp_path):
    release = tmp_path / "release"
    (release / "slides").mkdir(parents=True)
    (release / "slides" / "index.html").write_text("<html></html>", encoding="utf-8")
    secret = _canary(tmp_path)
    _symlink(secret, release / "slides" / "leak.md")

    checks = run_release_checks(
        release, manifest=None, approval_required=False, approval_present=False
    )

    assert any(item.check_id == "no_symlinks" and item.status == "fail" for item in checks)
    assert secret.is_file()


# -- temp files ---------------------------------------------------------


@requires_symlinks
def test_atomic_write_does_not_follow_a_precreated_temp_symlink(tmp_path):
    target = tmp_path / "target.txt"
    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")

    # The old implementation wrote ``.target.txt.tmp`` directly.
    _symlink(victim, tmp_path / ".target.txt.tmp")

    write_text_atomic(target, "new")

    assert target.read_text(encoding="utf-8").strip() == "new"
    assert victim.read_text(encoding="utf-8") == "keep"
    # The planted link is left alone; the writer never used its name.
    assert (tmp_path / ".target.txt.tmp").is_symlink()


# -- intermediate directory links: release -----------------------------


@requires_symlinks
def test_release_rejects_a_symlinked_build_slides(tmp_path):
    root, config = _ready_project(tmp_path)
    approve(root, config, "v1", "reviewer")
    outside = tmp_path / "outside-slides"
    outside.mkdir()
    (outside / "index.html").write_text("<html>EXTERNAL</html>", encoding="utf-8")
    shutil.rmtree(root / "build" / "slides")
    _symlink(outside, root / "build" / "slides", directory=True)

    with pytest.raises(ValidationFailure) as caught:
        build_release(root, config, "v1")

    assert "symlink" in str(caught.value)
    assert not (root / "release" / "v1").exists()
    assert not list((root / "build").glob("release-staging-*"))
    assert (outside / "index.html").read_text(encoding="utf-8") == "<html>EXTERNAL</html>"


@requires_symlinks
def test_release_rejects_a_symlinked_build_artifacts(tmp_path):
    root, config = _ready_project(tmp_path)
    approve(root, config, "v1", "reviewer")
    outside = tmp_path / "outside-artifacts"
    outside.mkdir()
    shutil.rmtree(root / "build" / "artifacts")
    _symlink(outside, root / "build" / "artifacts", directory=True)

    with pytest.raises(ValidationFailure) as caught:
        build_release(root, config, "v1")

    assert "symlink" in str(caught.value)
    assert list(outside.iterdir()) == []
    assert not (root / "release" / "v1").exists()


@requires_symlinks
def test_release_rejects_a_symlinked_release_directory(tmp_path):
    root, config = _ready_project(tmp_path)
    approve(root, config, "v1", "reviewer")
    outside = tmp_path / "outside-release"
    outside.mkdir()
    shutil.rmtree(root / "release")
    _symlink(outside, root / "release", directory=True)

    with pytest.raises(ValidationFailure) as caught:
        build_release(root, config, "v1")

    assert "symlink" in str(caught.value)
    assert list(outside.iterdir()) == []
    assert list((root / "build" / "artifacts").glob("*.zip")) == []


@requires_symlinks
def test_release_rejects_a_symlinked_internal_qa(tmp_path):
    root, config = _ready_project(tmp_path)
    approve(root, config, "v1", "reviewer")
    outside = tmp_path / "outside-qa"
    shutil.move(str(root / "internal" / "qa"), str(outside))
    _symlink(outside, root / "internal" / "qa", directory=True)
    before = sorted(path.name for path in outside.rglob("*"))

    with pytest.raises(ValidationFailure) as caught:
        build_release(root, config, "v1")

    assert "symlink" in str(caught.value)
    assert sorted(path.name for path in outside.rglob("*")) == before
    assert not (root / "release" / "v1").exists()


@requires_symlinks
def test_motion_refuses_a_symlinked_internal_qa(tmp_path, build_root):
    project = ensure_project_layout(tmp_path / "project")
    outside = tmp_path / "outside-qa"
    outside.mkdir()
    (project / "internal" / "qa").rmdir()
    _symlink(outside, project / "internal" / "qa", directory=True)

    renderer = _StubRenderer()
    with pytest.raises(RenderError) as caught:
        renderer.render(
            _spec(),
            mc.RenderContext(project_dir=project, output_dir=project / "build", publish=True),
        )

    assert caught.value.code == "invalid_input"
    assert list(outside.iterdir()) == []
    assert not (project / "build" / "motion").exists()


@requires_symlinks
def test_validation_refuses_a_symlinked_internal_qa(tmp_path):
    project = ensure_project_layout(tmp_path / "project")
    outside = tmp_path / "outside-qa"
    outside.mkdir()
    (project / "internal" / "qa").rmdir()
    _symlink(outside, project / "internal" / "qa", directory=True)

    with pytest.raises(ValidationFailure) as caught:
        run_validation(project, ProjectConfig(project_id="demo", title="示例"), tmp_path)

    assert "symlink" in str(caught.value)
    assert list(outside.iterdir()) == []


@requires_symlinks
def test_build_assets_refuse_a_symlinked_internal_qa(tmp_path):
    project = ensure_project_layout(tmp_path / "project")
    outside = tmp_path / "outside-qa"
    outside.mkdir()
    (project / "internal" / "qa").rmdir()
    _symlink(outside, project / "internal" / "qa", directory=True)

    with pytest.raises(RenderError) as caught:
        write_render_manifest(project, [])
    assert caught.value.code == "invalid_input"

    problems = verify_build_assets(project)
    assert any("symlink" in problem for problem in problems)
    assert list(outside.iterdir()) == []


# -- write_text_atomic --------------------------------------------------


@requires_symlinks
def test_atomic_write_replaces_a_target_symlink_instead_of_following_it(tmp_path):
    victim = tmp_path / "victim.txt"
    victim.write_text("keep", encoding="utf-8")
    target = tmp_path / "target.txt"
    _symlink(victim, target)

    write_text_atomic(target, "new")

    assert victim.read_text(encoding="utf-8") == "keep"
    assert not target.is_symlink()
    assert target.read_text(encoding="utf-8").strip() == "new"


def test_atomic_write_cleans_the_temp_file_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "target.txt"
    target.write_text("old", encoding="utf-8")

    def fail_replace(source, destination):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError):
        write_text_atomic(target, "new")

    assert target.read_text(encoding="utf-8").strip() == "old"
    assert list(tmp_path.glob(".target.txt.*.tmp")) == []


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode semantics")
def test_atomic_write_preserves_the_existing_mode(tmp_path):
    target = tmp_path / "target.txt"
    target.write_text("old", encoding="utf-8")
    target.chmod(0o640)

    write_text_atomic(target, "new")

    assert stat.S_IMODE(target.stat().st_mode) == 0o640


# -- E2E HOME canary: browser pin branches ------------------------------


def test_home_canary_keeps_an_explicit_browser_path(tmp_path, monkeypatch):
    original_browsers = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    with monkeypatch.context() as scoped:
        scoped.setenv("PLAYWRIGHT_BROWSERS_PATH", "/opt/browsers")
        with host_home_canary(tmp_path, scoped) as canary:
            assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "/opt/browsers"
            assert os.environ["HOME"] == str(canary)
        assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "/opt/browsers"
    assert os.environ.get("PLAYWRIGHT_BROWSERS_PATH") == original_browsers


def test_home_canary_pins_the_resolved_default_browser_path(tmp_path, monkeypatch):
    original_browsers = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    original_home = os.environ.get("HOME")
    with monkeypatch.context() as scoped:
        scoped.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
        scoped.setattr(mc, "playwright_browsers_path", lambda: "/opt/host-browsers")
        with host_home_canary(tmp_path, scoped) as canary:
            assert os.environ["PLAYWRIGHT_BROWSERS_PATH"] == "/opt/host-browsers"
            assert os.environ["HOME"] == str(canary)
    assert os.environ.get("PLAYWRIGHT_BROWSERS_PATH") == original_browsers
    assert os.environ.get("HOME") == original_home


def test_home_canary_fails_when_the_browser_path_cannot_be_resolved(tmp_path, monkeypatch):
    original_home = os.environ.get("HOME")
    with monkeypatch.context() as scoped:
        scoped.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
        scoped.setattr(mc, "playwright_browsers_path", lambda: None)
        with pytest.raises(pytest.fail.Exception):
            with host_home_canary(tmp_path, scoped):
                pass
        assert os.environ.get("HOME") == original_home


@requires_symlinks
def test_release_check_refuses_a_symlinked_release_directory(tmp_path):
    project = ensure_project_layout(tmp_path / "project")
    outside = tmp_path / "outside-release"
    outside.mkdir()
    (outside / "release_manifest.json").write_text("{not-json", encoding="utf-8")
    shutil.rmtree(project / "release")
    _symlink(outside, project / "release", directory=True)

    with pytest.raises(ValidationFailure) as caught:
        verify_release(project, "v1")

    assert "symlink" in str(caught.value)
    assert (outside / "release_manifest.json").read_text(encoding="utf-8") == "{not-json"


@requires_symlinks
def test_gate4_refuses_a_symlinked_release_root_before_reading(tmp_path):
    project = ensure_project_layout(tmp_path / "project")
    outside = tmp_path / "outside-release"
    (outside / "slides").mkdir(parents=True)
    (outside / "slides" / "index.html").write_text("TODO 内部草稿", encoding="utf-8")
    shutil.rmtree(project / "release")
    _symlink(outside, project / "release", directory=True)

    checks = run_release_checks(
        project / "release" / "v1",
        manifest=None,
        approval_required=False,
        approval_present=False,
        project_dir=project,
    )

    assert [item.check_id for item in checks] == ["no_symlinks"]
    assert checks[0].status == "fail"
