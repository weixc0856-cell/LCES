"""Supply-chain record and audit (P2.3-C).

P2.3-C asks three separate questions about every build input:

1. **Is it pinned?** A tag, a version range or a moving image reference is not
   a pin. Each component records ``reproducibility`` so the promise is explicit.
2. **Where did it come from?** ``trust`` names the channel (upstream release,
   official registry, distro package, ...), not a feeling about the vendor.
3. **Does the pin actually reach the build?** A record that no file consumes is
   documentation, not a control. Every check here reads the consumer: the
   offline Dockerfile, the lockfiles, the CI workflows.

The audit is static. It proves consistency between the record and the files
that pin the inputs; it cannot prove that an upstream release was honest.
"""

from __future__ import annotations

import json
import re
import tomllib
from collections.abc import Iterator
from pathlib import Path
from typing import Annotated, Literal, Union
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from content_studio.errors import ConfigurationError
from content_studio.motion_canvas import (
    MIN_FFMPEG,
    MOTION_CANVAS_VERSION,
    NODE_VERSION,
    PLAYWRIGHT_VERSION,
)
from content_studio.paths import repository_root

RECORD_PATH = Path("config") / "supply-chain.json"
DOCKERFILE_PATH = Path("motion") / "offline.Dockerfile"
NPM_LOCKFILE_PATH = Path("motion") / "package-lock.json"
NPM_PACKAGE_PATH = Path("motion") / "package.json"
CI_WORKFLOW_PATH = Path(".github") / "workflows" / "ci.yml"
WORKFLOWS_DIR = Path(".github") / "workflows"
UV_LOCK_PATH = Path("uv.lock")
PYPROJECT_PATH = Path("pyproject.toml")

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_REQUIREMENT = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")
_EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+[0-9A-Za-z.+-]*$")

TrustTier = Literal[
    "official-release",
    "official-registry",
    "upstream-publisher",
    "upstream-installer",
    "distro-package",
]
Reproducibility = Literal[
    "digest-pinned",
    "checksum-pinned",
    "lockfile-pinned",
    "version-pinned",
    "version-floor",
]
Status = Literal["pass", "fail"]


class _Component(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    trust: TrustTier
    reproducibility: Reproducibility
    notes: str = ""


def _check_date(value: str) -> str:
    if not _DATE.fullmatch(value):
        raise ValueError("recorded_at must be an ISO date (YYYY-MM-DD)")
    return value


class ImageRecord(_Component):
    kind: Literal["container-image"]
    reference: str
    digest: str
    recorded_at: str

    @field_validator("digest")
    @classmethod
    def _field_digest(cls, value: str) -> str:
        if not _DIGEST.fullmatch(value):
            raise ValueError("digest must be sha256:<64 lowercase hex characters>")
        return value

    @field_validator("recorded_at")
    @classmethod
    def _field_date(cls, value: str) -> str:
        return _check_date(value)


class ArchiveRecord(_Component):
    kind: Literal["binary-archive"]
    version: str
    platform: str
    url: str
    sha256: str
    checksum_source: str
    recorded_at: str

    @field_validator("sha256")
    @classmethod
    def _field_sha256(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return value

    @field_validator("url", "checksum_source")
    @classmethod
    def _field_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("must be an absolute https URL")
        return value

    @field_validator("recorded_at")
    @classmethod
    def _field_date(cls, value: str) -> str:
        return _check_date(value)


class RegistryRecord(_Component):
    kind: Literal["package-registry"]
    host: str
    lockfile: str
    integrity_algorithm: Literal["sha512"]


class BrowserRecord(_Component):
    kind: Literal["browser-bundle"]
    version: str
    installer: str
    source: str


class SystemPackageRecord(_Component):
    kind: Literal["system-package"]
    minimum_version: str


class LockfileRecord(_Component):
    kind: Literal["package-lock"]
    lockfile: str
    install_mode: str
    registry: str | None = None


class ActionPin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ref: str
    sha: str

    @field_validator("sha")
    @classmethod
    def _field_sha(cls, value: str) -> str:
        if not _COMMIT_SHA.fullmatch(value):
            raise ValueError("action pins must be 40-character commit SHAs")
        return value


class ActionsRecord(_Component):
    kind: Literal["github-actions"]
    actions: dict[str, ActionPin]


ComponentRecord = Annotated[
    Union[
        ImageRecord,
        ArchiveRecord,
        RegistryRecord,
        BrowserRecord,
        SystemPackageRecord,
        LockfileRecord,
        ActionsRecord,
    ],
    Field(discriminator="kind"),
]


class SupplyChainRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str
    description: str = ""
    components: dict[str, ComponentRecord]

    def component[T: BaseModel](self, key: str, expected: type[T]) -> T:
        value = self.components.get(key)
        if not isinstance(value, expected):
            raise ConfigurationError(
                f"{RECORD_PATH.as_posix()} is missing a '{key}' {expected.__name__} entry"
            )
        return value


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True)
    check_id: str
    status: Status
    detail: str

    def line(self) -> str:
        return f"[{self.status.upper()}] {self.check_id}: {self.detail}"


class SupplyChainReport(BaseModel):
    findings: list[Finding]

    @property
    def ok(self) -> bool:
        return all(finding.status == "pass" for finding in self.findings)

    def failures(self) -> list[Finding]:
        return [finding for finding in self.findings if finding.status != "pass"]


def _pass(check_id: str, detail: str) -> Finding:
    return Finding(check_id=check_id, status="pass", detail=detail)


def _fail(check_id: str, detail: str) -> Finding:
    return Finding(check_id=check_id, status="fail", detail=detail)


def load_record(root: Path | None = None) -> SupplyChainRecord:
    base = repository_root() if root is None else root
    path = base / RECORD_PATH
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigurationError(f"cannot read {RECORD_PATH.as_posix()}: {exc}") from exc
    except ValueError as exc:
        raise ConfigurationError(f"{RECORD_PATH.as_posix()} is not valid JSON: {exc}") from exc
    try:
        return SupplyChainRecord.model_validate(payload)
    except ValidationError as exc:
        raise ConfigurationError(f"{RECORD_PATH.as_posix()} is invalid: {exc}") from exc


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _json(path: Path) -> dict:
    payload = json.loads(_read(path))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def _check_base_image(root: Path, record: SupplyChainRecord) -> Finding:
    check_id = "SC-01-base-image-digest"
    image = record.component("base_image", ImageRecord)
    dockerfile = root / DOCKERFILE_PATH
    try:
        text = _read(dockerfile)
    except OSError as exc:
        return _fail(
            check_id, f"cannot read {DOCKERFILE_PATH.as_posix()}: {exc.__class__.__name__}"
        )
    from_lines = [
        line.strip().split()
        for line in text.splitlines()
        if line.strip().upper().startswith("FROM ")
    ]
    if not from_lines:
        return _fail(check_id, f"{DOCKERFILE_PATH.as_posix()} has no FROM line")
    tokens = [token for token in from_lines[0][1:] if not token.startswith("--")]
    if not tokens:
        return _fail(check_id, f"{DOCKERFILE_PATH.as_posix()} FROM line is empty")
    reference = tokens[0]
    if "@sha256:" not in reference:
        return _fail(check_id, f"base image '{reference}' is not pinned by digest")
    name, _, digest = reference.partition("@")
    if name != image.reference:
        return _fail(check_id, f"base image is '{name}', record says '{image.reference}'")
    if digest != image.digest:
        return _fail(check_id, f"base image digest {digest} does not match the recorded digest")
    return _pass(check_id, f"{name} pinned at {digest[:19]}...")


def _check_node_distribution(root: Path, record: SupplyChainRecord) -> Finding:
    check_id = "SC-02-node-archive-checksum"
    node = record.component("node_distribution", ArchiveRecord)
    dockerfile = root / DOCKERFILE_PATH
    try:
        text = _read(dockerfile)
    except OSError as exc:
        return _fail(
            check_id, f"cannot read {DOCKERFILE_PATH.as_posix()}: {exc.__class__.__name__}"
        )
    problems: list[str] = []
    if f"ARG NODE_VERSION={node.version}" not in text:
        problems.append(f"ARG NODE_VERSION={node.version} is missing")
    if f"ARG NODE_SHA256={node.sha256}" not in text:
        problems.append("ARG NODE_SHA256 does not carry the recorded SHA-256")
    verified = any("sha256sum -c" in line and "NODE_SHA256" in line for line in text.splitlines())
    if not verified:
        problems.append("sha256sum -c does not verify the archive against NODE_SHA256")
    template = "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz"
    if template not in text:
        problems.append("the official Node distribution URL template is missing")
    expected_url = (
        f"https://nodejs.org/dist/v{node.version}/node-v{node.version}-{node.platform}.tar.xz"
    )
    if node.url != expected_url:
        problems.append(f"recorded URL does not match version/platform: {node.url}")
    if node.platform != "linux-x64":
        problems.append(f"unexpected Node platform '{node.platform}'")
    if problems:
        return _fail(check_id, "; ".join(problems))
    return _pass(check_id, f"Node {node.version} verified by SHA-256 before extraction")


def _npm_packages(root: Path) -> dict[str, dict]:
    payload = _json(root / NPM_LOCKFILE_PATH)
    packages = payload.get("packages")
    if not isinstance(packages, dict):
        raise ValueError(f"{NPM_LOCKFILE_PATH.as_posix()} has no 'packages' map")
    return {name: entry for name, entry in packages.items() if isinstance(entry, dict)}


def _check_npm_registry(root: Path, record: SupplyChainRecord) -> Finding:
    check_id = "SC-03-npm-lockfile-integrity"
    registry = record.component("npm_registry", RegistryRecord)
    if registry.lockfile != NPM_LOCKFILE_PATH.as_posix():
        return _fail(
            check_id,
            f"record names lockfile '{registry.lockfile}', expected {NPM_LOCKFILE_PATH.as_posix()}",
        )
    try:
        packages = _npm_packages(root)
    except (OSError, ValueError) as exc:
        return _fail(check_id, f"cannot read {NPM_LOCKFILE_PATH.as_posix()}: {exc}")
    if "" not in packages:
        return _fail(check_id, f"{NPM_LOCKFILE_PATH.as_posix()} has no root package entry")
    hosts: set[str] = set()
    bad_integrity: list[str] = []
    missing_resolved: list[str] = []
    for name, entry in packages.items():
        if not name:
            continue
        if entry.get("link") is True:
            continue
        resolved = entry.get("resolved")
        if isinstance(resolved, str):
            host = urlsplit(resolved).netloc
            if host != registry.host:
                hosts.add(host)
        else:
            missing_resolved.append(name)
        integrity = entry.get("integrity")
        prefix = f"{registry.integrity_algorithm}-"
        if not isinstance(integrity, str) or not integrity.startswith(prefix):
            bad_integrity.append(name)
    problems: list[str] = []
    if hosts:
        problems.append(f"packages resolve outside {registry.host}: {sorted(hosts)}")
    if bad_integrity:
        problems.append(f"{len(bad_integrity)} packages lack sha512 integrity")
    if missing_resolved:
        problems.append(f"{len(missing_resolved)} packages have no resolved URL")
    if problems:
        return _fail(check_id, "; ".join(problems))
    return _pass(
        check_id,
        f"{len(packages) - 1} packages from {registry.host} with sha512 integrity",
    )


def _check_npm_lock_matches_package(root: Path, _record: SupplyChainRecord) -> Finding:
    check_id = "SC-04-npm-lock-matches-package-json"
    try:
        declared = _json(root / NPM_PACKAGE_PATH)
        packages = _npm_packages(root)
    except (OSError, ValueError) as exc:
        return _fail(check_id, f"cannot read the npm manifests: {exc}")
    locked_root = packages.get("")
    if locked_root is None:
        return _fail(check_id, f"{NPM_LOCKFILE_PATH.as_posix()} has no root package entry")
    problems: list[str] = []
    for section in ("dependencies", "devDependencies"):
        wanted = declared.get(section) or {}
        pinned = locked_root.get(section) or {}
        if not isinstance(wanted, dict) or not isinstance(pinned, dict):
            problems.append(f"package.json {section} is not an object")
            continue
        if wanted != pinned:
            problems.append(f"package.json {section} does not match the lockfile root")
        for name, version in sorted(wanted.items()):
            if not isinstance(version, str) or not _EXACT_VERSION.fullmatch(version):
                problems.append(f"{name} is not pinned to an exact version")
                continue
            entry = packages.get(f"node_modules/{name}")
            locked_version = entry.get("version") if entry else None
            if locked_version != version:
                problems.append(f"{name}: lockfile has {locked_version or 'no entry'}")
    if problems:
        return _fail(check_id, "; ".join(problems[:5]))
    return _pass(check_id, "direct dependencies match the lockfile exactly")


def _iter_uses(node: object) -> Iterator[str]:
    if isinstance(node, dict):
        uses = node.get("uses")
        if isinstance(uses, str):
            yield uses
        for value in node.values():
            yield from _iter_uses(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_uses(item)


def _check_actions(root: Path, record: SupplyChainRecord) -> Finding:
    check_id = "SC-05-github-actions-pinned"
    pinned = record.component("github_actions", ActionsRecord)
    workflows = sorted(
        path for pattern in ("*.yml", "*.yaml") for path in (root / WORKFLOWS_DIR).glob(pattern)
    )
    if not workflows:
        return _fail(check_id, f"no workflows under {WORKFLOWS_DIR.as_posix()}")
    problems: list[str] = []
    seen: set[str] = set()
    for path in workflows:
        relative = path.relative_to(root).as_posix()
        try:
            payload = yaml.safe_load(_read(path)) or {}
        except (OSError, yaml.YAMLError) as exc:
            problems.append(f"{relative} cannot be parsed: {exc.__class__.__name__}")
            continue
        for uses in _iter_uses(payload):
            if uses.startswith("./"):
                continue
            if "${{" in uses:
                problems.append(f"{relative}: '{uses}' is an expression, not a pinned action")
                continue
            repo, _, ref = uses.rpartition("@")
            if not repo or not ref:
                problems.append(f"{relative}: '{uses}' has no repository@ref")
                continue
            owner_repo = "/".join(repo.split("/")[:2])
            seen.add(owner_repo)
            recorded = pinned.actions.get(owner_repo)
            if recorded is None:
                problems.append(f"{relative}: {owner_repo} is not recorded")
                continue
            if not _COMMIT_SHA.fullmatch(ref):
                problems.append(f"{relative}: {owner_repo}@{ref} is not a commit SHA")
                continue
            if ref != recorded.sha:
                problems.append(
                    f"{relative}: {owner_repo} uses {ref[:12]}..., record has another SHA"
                )
    if problems:
        return _fail(check_id, "; ".join(problems[:5]))
    return _pass(
        check_id,
        f"{len(workflows)} workflows use recorded commit SHAs for {len(seen)} actions",
    )


def _check_versions(root: Path, record: SupplyChainRecord) -> Finding:
    check_id = "SC-06-version-constants"
    node = record.component("node_distribution", ArchiveRecord)
    browser = record.component("playwright_browser", BrowserRecord)
    ffmpeg = record.component("ffmpeg", SystemPackageRecord)
    try:
        package = _json(root / NPM_PACKAGE_PATH)
    except (OSError, ValueError) as exc:
        return _fail(check_id, f"cannot read {NPM_PACKAGE_PATH.as_posix()}: {exc}")
    dependencies = package.get("dependencies") or {}
    engines = package.get("engines") or {}
    problems: list[str] = []
    if node.version != NODE_VERSION:
        problems.append(f"adapter pins Node {NODE_VERSION}, record says {node.version}")
    if engines.get("node") != NODE_VERSION:
        problems.append(f"motion/package.json engines.node is not {NODE_VERSION}")
    if dependencies.get("@motion-canvas/core") != MOTION_CANVAS_VERSION:
        problems.append(f"@motion-canvas/core is not pinned to {MOTION_CANVAS_VERSION}")
    if dependencies.get("@motion-canvas/2d") != MOTION_CANVAS_VERSION:
        problems.append(f"@motion-canvas/2d is not pinned to {MOTION_CANVAS_VERSION}")
    if dependencies.get("playwright") != PLAYWRIGHT_VERSION:
        problems.append(f"playwright is not pinned to {PLAYWRIGHT_VERSION}")
    if browser.version != PLAYWRIGHT_VERSION:
        problems.append(f"browser record says Playwright {browser.version}")
    floor = f"{MIN_FFMPEG[0]}.{MIN_FFMPEG[1]}"
    if ffmpeg.minimum_version != floor:
        problems.append(f"FFmpeg record says >= {ffmpeg.minimum_version}, adapter requires {floor}")
    if problems:
        return _fail(check_id, "; ".join(problems))
    return _pass(
        check_id,
        f"Node {NODE_VERSION}, Motion Canvas {MOTION_CANVAS_VERSION}, "
        f"Playwright {PLAYWRIGHT_VERSION}, FFmpeg >= {floor}",
    )


def _requirement_name(requirement: str) -> str:
    match = _REQUIREMENT.match(requirement.strip())
    name = match.group(1) if match else requirement
    return re.sub(r"[-_.]+", "-", name.lower())


def _check_python_lock(root: Path, record: SupplyChainRecord) -> Finding:
    check_id = "SC-07-python-lockfile"
    python_lock = record.component("python_lock", LockfileRecord)
    try:
        project = tomllib.loads(_read(root / PYPROJECT_PATH))
        lock = tomllib.loads(_read(root / UV_LOCK_PATH))
        workflow = _read(root / CI_WORKFLOW_PATH)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return _fail(check_id, f"cannot read the Python lock inputs: {exc.__class__.__name__}")
    locked = {
        _requirement_name(str(entry.get("name", "")))
        for entry in lock.get("package", [])
        if isinstance(entry, dict)
    }
    requirements: list[str] = []
    project_table = project.get("project") or {}
    requirements.extend(str(item) for item in project_table.get("dependencies") or [])
    for extra in (project_table.get("optional-dependencies") or {}).values():
        requirements.extend(str(item) for item in extra)
    for group in (project.get("dependency-groups") or {}).values():
        requirements.extend(str(item) for item in group if isinstance(item, str))
    missing = sorted({_requirement_name(item) for item in requirements} - locked)
    registries = {
        str(entry["source"]["registry"])
        for entry in lock.get("package", [])
        if isinstance(entry, dict)
        and isinstance(entry.get("source"), dict)
        and isinstance(entry["source"].get("registry"), str)
    }
    problems: list[str] = []
    if missing:
        problems.append(f"uv.lock is missing direct dependencies: {missing[:5]}")
    if python_lock.registry is not None:
        unexpected = sorted(registries - {python_lock.registry})
        if unexpected:
            problems.append(f"uv.lock resolves outside {python_lock.registry}: {unexpected}")
        if not registries:
            problems.append("uv.lock has no registry sources")
    if "uv sync --locked" not in workflow:
        problems.append(f"{CI_WORKFLOW_PATH.as_posix()} does not install with --locked")
    if problems:
        return _fail(check_id, "; ".join(problems))
    return _pass(check_id, f"{len(requirements)} direct requirements present in uv.lock")


def audit_supply_chain(root: Path | None = None) -> SupplyChainReport:
    """Check every pin against the file that consumes it."""

    base = repository_root() if root is None else root
    record = load_record(base)
    findings = [
        _check_base_image(base, record),
        _check_node_distribution(base, record),
        _check_npm_registry(base, record),
        _check_npm_lock_matches_package(base, record),
        _check_actions(base, record),
        _check_versions(base, record),
        _check_python_lock(base, record),
    ]
    return SupplyChainReport(findings=findings)
