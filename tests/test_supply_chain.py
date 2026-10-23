"""P2.3-C: every pinned input is recorded, and the pin reaches the build."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from content_studio import encode
from content_studio.cli import app
from content_studio.errors import ConfigurationError
from content_studio.models import FrameEntry, FrameManifest, SceneFrameSpan
from content_studio.motion_canvas import (
    MOTION_CANVAS_VERSION,
    NODE_VERSION,
    PLAYWRIGHT_VERSION,
    motion_project_dir,
    render_provenance,
)
from content_studio.paths import repository_root
from content_studio.supply_chain import (
    NPM_PACKAGE_PATH,
    RECORD_PATH,
    audit_supply_chain,
    load_record,
)
from content_studio.utils import sha256_file

DEPENDENCIES = {
    "@motion-canvas/core": MOTION_CANVAS_VERSION,
    "@motion-canvas/2d": MOTION_CANVAS_VERSION,
    "playwright": PLAYWRIGHT_VERSION,
}
DEV_DEPENDENCIES = {"@motion-canvas/ui": MOTION_CANVAS_VERSION, "vite": "4.5.14"}


def _real_record() -> dict:
    return json.loads((repository_root() / RECORD_PATH).read_text(encoding="utf-8"))


def _write_repo(
    root: Path,
    *,
    record: dict | None = None,
    dockerfile: str | None = None,
    workflow: str | None = None,
    package: dict | None = None,
    lock: dict | None = None,
    pyproject: str | None = None,
    uv_lock: str | None = None,
) -> Path:
    """A minimal repository that satisfies every supply-chain check."""

    payload = copy.deepcopy(record if record is not None else _real_record())
    node = payload["components"]["node_distribution"]
    image = payload["components"]["base_image"]
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "motion").mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (root / RECORD_PATH).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    dockerfile = dockerfile or (
        f"FROM {image['reference']}@{image['digest']}\n"
        f"ARG NODE_VERSION={node['version']}\n"
        f"ARG NODE_SHA256={node['sha256']}\n"
        'RUN curl -fsSLo /tmp/node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/'
        'node-v${NODE_VERSION}-linux-x64.tar.xz" \\\n'
        ' && echo "${NODE_SHA256}  /tmp/node.tar.xz" | sha256sum -c - \\\n'
        ' && test "$(node --version)" = "v${NODE_VERSION}"\n'
    )
    (root / "motion" / "offline.Dockerfile").write_text(dockerfile, encoding="utf-8")

    package = package or {
        "engines": {"node": NODE_VERSION},
        "dependencies": dict(DEPENDENCIES),
        "devDependencies": dict(DEV_DEPENDENCIES),
    }
    (root / NPM_PACKAGE_PATH).write_text(json.dumps(package), encoding="utf-8")

    lock = lock or _lockfile()
    (root / "motion" / "package-lock.json").write_text(json.dumps(lock), encoding="utf-8")

    pinned = payload["components"]["github_actions"]["actions"]
    workflow = workflow or (
        "on: [push]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"      - uses: actions/checkout@{pinned['actions/checkout']['sha']}\n"
        f"      - uses: astral-sh/setup-uv@{pinned['astral-sh/setup-uv']['sha']}\n"
        "      - run: uv sync --locked\n"
    )
    (root / ".github" / "workflows" / "ci.yml").write_text(workflow, encoding="utf-8")

    (root / "pyproject.toml").write_text(
        pyproject
        or '[project]\nname = "fixture"\nversion = "0.1.0"\ndependencies = ["typer>=0.12,<1.0"]\n',
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        uv_lock or _uv_lock(),
        encoding="utf-8",
    )
    return root


def _lockfile(host: str = "registry.npmjs.org", drop_integrity: str | None = None) -> dict:
    packages: dict[str, dict] = {
        "": {"dependencies": dict(DEPENDENCIES), "devDependencies": dict(DEV_DEPENDENCIES)}
    }
    for name, version in {**DEPENDENCIES, **DEV_DEPENDENCIES}.items():
        entry = {
            "version": version,
            "resolved": f"https://{host}/{name}/-/{name.split('/')[-1]}-{version}.tgz",
            "integrity": "sha512-" + "A" * 86 + "==",
        }
        if drop_integrity == name:
            entry.pop("integrity")
        packages[f"node_modules/{name}"] = entry
    return {"lockfileVersion": 3, "packages": packages}


def _uv_lock(registry: str = "https://pypi.org/simple") -> str:
    return chr(10).join(
        [
            "version = 1",
            "",
            "[[package]]",
            'name = "typer"',
            'version = "0.12.0"',
            f'source = {{ registry = "{registry}" }}',
            "",
        ]
    )


def _status(report, check_id: str) -> str:
    return next(finding.status for finding in report.findings if finding.check_id == check_id)


def _failed(report, check_id: str) -> bool:
    return _status(report, check_id) == "fail"


def _detail(report, check_id: str) -> str:
    return next(finding.detail for finding in report.findings if finding.check_id == check_id)


# -- the repository itself -------------------------------------------------


def test_the_checked_in_repository_passes():
    report = audit_supply_chain(repository_root())
    assert report.ok, [finding.line() for finding in report.failures()]
    assert {finding.check_id for finding in report.findings} == {
        "SC-01-base-image-digest",
        "SC-02-node-archive-checksum",
        "SC-03-npm-lockfile-integrity",
        "SC-04-npm-lock-matches-package-json",
        "SC-05-github-actions-pinned",
        "SC-06-version-constants",
        "SC-07-python-lockfile",
    }


def test_record_rejects_a_malformed_digest(tmp_path):
    payload = _real_record()
    payload["components"]["base_image"]["digest"] = "sha256:nothex"
    _write_repo(tmp_path, record=payload)
    with pytest.raises(ConfigurationError, match="invalid"):
        load_record(tmp_path)


# -- SC-01 / SC-02: image and archive pins ---------------------------------


def test_unpinned_base_image_fails(tmp_path):
    payload = _real_record()
    image = payload["components"]["base_image"]
    _write_repo(tmp_path, record=payload, dockerfile=f"FROM {image['reference']}\n")
    report = audit_supply_chain(tmp_path)
    assert _failed(report, "SC-01-base-image-digest")
    assert "not pinned by digest" in _detail(report, "SC-01-base-image-digest")


def test_base_image_digest_mismatch_fails(tmp_path):
    dockerfile = f"FROM example.test/base@sha256:{'a' * 64}\n"
    _write_repo(tmp_path, dockerfile=dockerfile)
    report = audit_supply_chain(tmp_path)
    assert _failed(report, "SC-01-base-image-digest")


def test_node_checksum_mismatch_fails(tmp_path):
    # N13: the Dockerfile carries a different hash than the record.
    payload = _real_record()
    node = payload["components"]["node_distribution"]
    dockerfile = (
        f"FROM {payload['components']['base_image']['reference']}"
        f"@{payload['components']['base_image']['digest']}\n"
        f"ARG NODE_VERSION={node['version']}\n"
        f"ARG NODE_SHA256={'b' * 64}\n"
        'RUN curl -fsSLo /tmp/node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/'
        'node-v${NODE_VERSION}-linux-x64.tar.xz" \\\n'
        ' && echo "${NODE_SHA256}  /tmp/node.tar.xz" | sha256sum -c -\n'
    )
    _write_repo(tmp_path, record=payload, dockerfile=dockerfile)
    report = audit_supply_chain(tmp_path)
    assert _failed(report, "SC-02-node-archive-checksum")
    assert "NODE_SHA256" in _detail(report, "SC-02-node-archive-checksum")


def test_node_archive_without_verification_fails(tmp_path):
    payload = _real_record()
    node = payload["components"]["node_distribution"]
    dockerfile = (
        f"FROM {payload['components']['base_image']['reference']}"
        f"@{payload['components']['base_image']['digest']}\n"
        f"ARG NODE_VERSION={node['version']}\n"
        f"ARG NODE_SHA256={node['sha256']}\n"
        'RUN curl -fsSLo /tmp/node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/'
        'node-v${NODE_VERSION}-linux-x64.tar.xz"\n'
    )
    _write_repo(tmp_path, record=payload, dockerfile=dockerfile)
    report = audit_supply_chain(tmp_path)
    assert _failed(report, "SC-02-node-archive-checksum")
    assert "sha256sum -c" in _detail(report, "SC-02-node-archive-checksum")


# -- SC-03 / SC-04: npm lockfile -------------------------------------------


def test_lockfile_from_a_mirror_fails(tmp_path):
    _write_repo(tmp_path, lock=_lockfile(host="registry.npmmirror.com"))
    report = audit_supply_chain(tmp_path)
    assert _failed(report, "SC-03-npm-lockfile-integrity")
    assert "registry.npmmirror.com" in _detail(report, "SC-03-npm-lockfile-integrity")


def test_lockfile_entry_without_integrity_fails(tmp_path):
    _write_repo(tmp_path, lock=_lockfile(drop_integrity="playwright"))
    report = audit_supply_chain(tmp_path)
    assert _failed(report, "SC-03-npm-lockfile-integrity")
    assert "lack sha512 integrity" in _detail(report, "SC-03-npm-lockfile-integrity")


def test_lockfile_version_drift_fails(tmp_path):
    # N12 at the static level: package.json says one version, the lock another.
    package = {
        "engines": {"node": NODE_VERSION},
        "dependencies": {**DEPENDENCIES, "playwright": "1.63.0"},
        "devDependencies": dict(DEV_DEPENDENCIES),
    }
    _write_repo(tmp_path, package=package)
    report = audit_supply_chain(tmp_path)
    assert _failed(report, "SC-04-npm-lock-matches-package-json")


def test_unpinned_dependency_range_fails(tmp_path):
    package = {
        "engines": {"node": NODE_VERSION},
        "dependencies": {**DEPENDENCIES, "playwright": "^1.64.0"},
        "devDependencies": dict(DEV_DEPENDENCIES),
    }
    _write_repo(tmp_path, package=package)
    report = audit_supply_chain(tmp_path)
    assert _failed(report, "SC-04-npm-lock-matches-package-json")
    assert "exact version" in _detail(report, "SC-04-npm-lock-matches-package-json")


# -- SC-05: GitHub Actions -------------------------------------------------


def test_action_tag_instead_of_commit_sha_fails(tmp_path):
    # N14: a mutable tag is not a pin, even when the recorded SHA exists.
    workflow = (
        "on: [push]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - run: uv sync --locked\n"
    )
    _write_repo(tmp_path, workflow=workflow)
    report = audit_supply_chain(tmp_path)
    assert _failed(report, "SC-05-github-actions-pinned")
    assert "not a commit SHA" in _detail(report, "SC-05-github-actions-pinned")


def test_unrecorded_action_fails(tmp_path):
    pinned = _real_record()["components"]["github_actions"]["actions"]
    workflow = (
        "on: [push]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"      - uses: actions/checkout@{pinned['actions/checkout']['sha']}\n"
        f"      - uses: example/action@{'c' * 40}\n"
        "      - run: uv sync --locked\n"
    )
    _write_repo(tmp_path, workflow=workflow)
    report = audit_supply_chain(tmp_path)
    assert _failed(report, "SC-05-github-actions-pinned")
    assert "not recorded" in _detail(report, "SC-05-github-actions-pinned")


def test_dynamic_action_reference_fails(tmp_path):
    workflow = chr(10).join(
        [
            "on: [push]",
            "jobs:",
            "  test:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - uses: ${{ inputs.action }}@v4",
            "      - run: uv sync --locked",
        ]
    )
    _write_repo(tmp_path, workflow=workflow)
    report = audit_supply_chain(tmp_path)
    assert _failed(report, "SC-05-github-actions-pinned")
    assert "expression" in _detail(report, "SC-05-github-actions-pinned")


# -- SC-06 / SC-07: constants and Python lock ------------------------------


def test_node_version_drift_between_adapter_and_record_fails(tmp_path):
    payload = _real_record()
    payload["components"]["node_distribution"]["version"] = "24.21.0"
    payload["components"]["node_distribution"]["url"] = (
        "https://nodejs.org/dist/v24.21.0/node-v24.21.0-linux-x64.tar.xz"
    )
    _write_repo(tmp_path, record=payload)
    report = audit_supply_chain(tmp_path)
    assert _failed(report, "SC-06-version-constants")


def test_python_lock_missing_a_direct_dependency_fails(tmp_path):
    _write_repo(
        tmp_path,
        pyproject='[project]\nname = "fixture"\nversion = "0.1.0"\n'
        'dependencies = ["typer>=0.12,<1.0", "httpx>=0.27,<1.0"]\n',
    )
    report = audit_supply_chain(tmp_path)
    assert _failed(report, "SC-07-python-lockfile")
    assert "httpx" in _detail(report, "SC-07-python-lockfile")


def test_python_lock_from_another_index_fails(tmp_path):
    _write_repo(tmp_path, uv_lock=_uv_lock("https://mirror.example/simple"))
    report = audit_supply_chain(tmp_path)
    assert _failed(report, "SC-07-python-lockfile")
    assert "mirror.example" in _detail(report, "SC-07-python-lockfile")


def test_ci_must_install_with_the_lockfile(tmp_path):
    pinned = _real_record()["components"]["github_actions"]["actions"]
    workflow = (
        "on: [push]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        f"      - uses: actions/checkout@{pinned['actions/checkout']['sha']}\n"
        "      - run: uv sync\n"
    )
    _write_repo(tmp_path, workflow=workflow)
    report = audit_supply_chain(tmp_path)
    assert _failed(report, "SC-07-python-lockfile")
    assert "--locked" in _detail(report, "SC-07-python-lockfile")


# -- CLI -------------------------------------------------------------------


def test_cli_reports_success(tmp_path):
    _write_repo(tmp_path)
    result = CliRunner().invoke(app, ["supply-chain-check", "--root", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "供应链审计通过" in result.output


def test_cli_exits_nonzero_on_a_failure(tmp_path):
    _write_repo(tmp_path, lock=_lockfile(host="registry.npmmirror.com"))
    result = CliRunner().invoke(app, ["supply-chain-check", "--root", str(tmp_path)])
    assert result.exit_code == 1
    assert "供应链审计失败" in result.output


# -- provenance ------------------------------------------------------------


def _manifest(total: int = 3) -> FrameManifest:
    return FrameManifest(
        build_id="build-test-001",
        asset_id="course-v1",
        fps_num=30,
        fps_den=1,
        width=320,
        height=180,
        total_frames=total,
        scenes=[SceneFrameSpan(scene_id="scene-001", start_frame=0, end_frame=total)],
        frames=[
            FrameEntry(
                index=index,
                path=f"frames/project/{index:06d}.png",
                sha256="a" * 64,
                width=320,
                height=180,
            )
            for index in range(total)
        ],
    )


def test_encode_report_records_provenance(tmp_path):
    video = tmp_path / "course.mp4"
    video.write_bytes(b"placeholder")
    report = encode.encode_report(
        _manifest(),
        output=video,
        command=["ffmpeg"],
        manifest_sha256="f" * 64,
        provenance={"node_version": NODE_VERSION},
    )
    assert report["schema_version"] == "1.1"
    assert report["provenance"] == {"node_version": NODE_VERSION}
    without = encode.encode_report(
        _manifest(), output=video, command=["ffmpeg"], manifest_sha256="f" * 64
    )
    assert without["schema_version"] == "1.0"
    assert "provenance" not in without


def test_render_provenance_hashes_the_consumed_inputs():
    project = motion_project_dir()
    provenance = render_provenance(project, shutil.which("node") or "node")
    assert provenance["package_lock_sha256"] == sha256_file(project / "package-lock.json")
    assert provenance["package_json_sha256"] == sha256_file(project / "package.json")
    assert provenance["lces_version"]
    assert provenance["python_version"]
    # Evidence uploads must not leak the runner's filesystem layout.
    dumped = json.dumps(provenance)
    assert str(project) not in dumped
    assert str(project.parent) not in dumped
