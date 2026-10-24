"""Gate B: course product qualification.

The course-content audit (``course_audit``) checks that shown numbers and
formulas match reviewed evidence. That is a necessary condition, not a
course. This module checks the product contract: the course must declare its
audience, objectives, modules, deliverables and timing rule, and the delivered
content must satisfy them.

Automated checks can prove structure, coverage mappings, presence of learning
checks and the existence of measured timing evidence. They cannot prove that
an explanation is clear or that a learner understood it. Those stay in the
human acceptance record, and the report says so explicitly.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from content_studio.content import (
    load_outline,
    load_public_content,
    load_reading_edition,
    load_speaker_script,
)
from content_studio.models import (
    CheckBlock,
    CheckResult,
    FormulaBlock,
    QAReport,
    StrictModel,
)
from content_studio.utils import utc_now, write_json_atomic

QUALITY_SCHEMA_VERSION = "1.0"
QUALITY_RELATIVE_PATH = Path("internal") / "qa" / "course_quality_audit.json"
CONTRACT_RELATIVE_PATH = Path("internal") / "plan" / "course_contract.json"
TIMING_RELATIVE_PATH = Path("internal") / "qa" / "timing_evidence.json"
ACCEPTANCE_RELATIVE_PATH = Path("internal") / "qa" / "course_acceptance.json"
QUALITY_FILES = (
    CONTRACT_RELATIVE_PATH,
    Path("content") / "public_content.json",
    Path("content") / "reading_edition.json",
    Path("content") / "outline.json",
    Path("internal") / "speaker_script.json",
    Path("build") / "slides" / "index.html",
    Path("build") / "reading_edition.html",
)

TimingMethod = Literal["estimate", "tts_readthrough", "human_readthrough", "human_recording"]
Decision = Literal["passed", "needs_human_review", "blocked", "not_run"]
Severity = Literal["blocker", "human"]


class CourseObjective(StrictModel):
    objective_id: str = Field(pattern=r"^objective-[a-z0-9.-]+$")
    statement: str = Field(min_length=1)
    required: bool = True
    slide_ids: list[str] = Field(min_length=1)


class CourseModule(StrictModel):
    module_id: str = Field(pattern=r"^module-[a-z0-9.-]+$")
    title: str = Field(min_length=1)
    target_minutes: float = Field(gt=0)
    slide_ids: list[str] = Field(min_length=1)


class CourseContract(StrictModel):
    schema_version: str = "1.0"
    project_id: str
    version: str = "1.0"
    status: Literal["draft", "approved"] = "draft"
    approved_by: str = ""
    approved_at: datetime | None = None
    audience: str = Field(min_length=1)
    prerequisites: list[str] = Field(default_factory=list)
    target_duration_minutes: float = Field(gt=0)
    timing_rule: str = Field(min_length=1)
    objectives: list[CourseObjective] = Field(min_length=1)
    modules: list[CourseModule] = Field(min_length=1)
    deliverables: list[str] = Field(min_length=1)
    required_formula_count: int = Field(default=3, ge=0)
    required_check_count: int = Field(default=6, ge=0)
    manual_items: list[str] = Field(default_factory=list)
    notes: str = ""

    @model_validator(mode="after")
    def _unique_ids(self) -> CourseContract:
        objective_ids = [item.objective_id for item in self.objectives]
        module_ids = [item.module_id for item in self.modules]
        if len(objective_ids) != len(set(objective_ids)):
            raise ValueError("objective_id values must be unique")
        if len(module_ids) != len(set(module_ids)):
            raise ValueError("module_id values must be unique")
        if self.status == "approved" and not self.approved_by.strip():
            raise ValueError("an approved contract needs approved_by")
        return self


class TimingEvidence(StrictModel):
    project_id: str
    method: TimingMethod = "estimate"
    measured_seconds: float = Field(ge=0)
    target_minutes: float = Field(gt=0)
    script_sha256: str = ""
    audio_path: str = ""
    audio_sha256: str = ""
    voice: str = ""
    generated_at: datetime
    notes: str = ""


class CourseAcceptance(StrictModel):
    project_id: str
    contract_version: str
    content_version: str
    reviewer: str = Field(min_length=1)
    reviewed_at: datetime
    decision: Literal["pass", "needs_revision"] = "needs_revision"
    timing_confirmed: bool = False
    visual_confirmed: bool = False
    checks_confirmed: bool = False
    notes: str = ""


class QualityFinding(StrictModel):
    finding_id: str
    check_id: str
    severity: Severity
    message: str
    location: str = ""


class CourseQualityReport(StrictModel):
    schema_version: str = QUALITY_SCHEMA_VERSION
    audit_id: str
    project_id: str
    contract_version: str = ""
    content_version: str = ""
    generated_at: datetime
    files: list[dict[str, str]] = Field(default_factory=list)
    findings: list[QualityFinding] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)
    decision: Decision = "not_run"
    notes: str = ""

    @property
    def blockers(self) -> list[QualityFinding]:
        return [item for item in self.findings if item.severity == "blocker"]

    @property
    def human_items(self) -> list[QualityFinding]:
        return [item for item in self.findings if item.severity == "human"]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _finding_id(check_id: str, location: str, message: str) -> str:
    payload = f"{check_id}|{location}|{message}".encode()
    return "quality-" + hashlib.sha256(payload).hexdigest()[:12]


def _add(
    findings: list[QualityFinding],
    check_id: str,
    severity: Severity,
    message: str,
    *,
    location: str = "",
) -> None:
    findings.append(
        QualityFinding(
            finding_id=_finding_id(check_id, location, message),
            check_id=check_id,
            severity=severity,
            message=message,
            location=location,
        )
    )


def contract_path(project_dir: Path) -> Path:
    return project_dir / CONTRACT_RELATIVE_PATH


def timing_path(project_dir: Path) -> Path:
    return project_dir / TIMING_RELATIVE_PATH


def acceptance_path(project_dir: Path) -> Path:
    return project_dir / ACCEPTANCE_RELATIVE_PATH


def quality_path(project_dir: Path) -> Path:
    return project_dir / QUALITY_RELATIVE_PATH


def load_contract(project_dir: Path) -> CourseContract | None:
    path = contract_path(project_dir)
    if not path.is_file():
        return None
    return CourseContract.model_validate_json(path.read_text(encoding="utf-8"))


def load_timing(project_dir: Path) -> TimingEvidence | None:
    path = timing_path(project_dir)
    if not path.is_file():
        return None
    return TimingEvidence.model_validate_json(path.read_text(encoding="utf-8"))


def load_acceptance(project_dir: Path) -> CourseAcceptance | None:
    path = acceptance_path(project_dir)
    if not path.is_file():
        return None
    return CourseAcceptance.model_validate_json(path.read_text(encoding="utf-8"))


def load_quality(project_dir: Path) -> CourseQualityReport | None:
    path = quality_path(project_dir)
    if not path.is_file():
        return None
    return CourseQualityReport.model_validate_json(path.read_text(encoding="utf-8"))


def write_quality(project_dir: Path, report: CourseQualityReport) -> Path:
    path = quality_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, report)
    return path


def _project_target(project_dir: Path) -> float:
    path = project_dir / "project.yaml"
    if not path.is_file():
        return 0.0
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    try:
        return float(payload.get("target_duration_minutes", 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def _qa_report(project_dir: Path) -> QAReport | None:
    path = project_dir / "internal" / "qa" / "qa_report.json"
    if not path.is_file():
        return None
    return QAReport.model_validate_json(path.read_text(encoding="utf-8"))


def _content_version(project_dir: Path) -> tuple[str, list[dict[str, str]]]:
    entries: list[dict[str, str]] = []
    for relative in QUALITY_FILES:
        path = project_dir / relative
        if path.is_file():
            entries.append({"path": relative.as_posix(), "sha256": _sha256(path)})
    payload = "\n".join(f"{item['path']}:{item['sha256']}" for item in entries)
    return hashlib.sha256(payload.encode()).hexdigest(), entries


def _slide_text_length(body: list[object]) -> int:
    total = 0
    for block in body:
        for attribute in (
            "text",
            "explanation",
            "caption",
            "question",
            "answer",
            "rationale",
            "latex",
        ):
            value = getattr(block, attribute, "")
            if isinstance(value, str):
                total += len(value)
        items = getattr(block, "items", None)
        if isinstance(items, list):
            total += sum(len(str(item)) for item in items)
        rows = getattr(block, "rows", None)
        if isinstance(rows, list):
            total += sum(len(str(cell)) for row in rows for cell in row)
    return total


def run_course_quality_audit(project_dir: Path) -> CourseQualityReport:
    project_dir = project_dir.resolve()
    content_version, files = _content_version(project_dir)
    contract = load_contract(project_dir)
    public = load_public_content(project_dir)
    reading = load_reading_edition(project_dir)
    outline = load_outline(project_dir)
    script = load_speaker_script(project_dir)
    qa = _qa_report(project_dir)
    findings: list[QualityFinding] = []

    if contract is None:
        _add(
            findings,
            "product_contract_present",
            "blocker",
            "缺少课程产品契约 internal/plan/course_contract.json",
            location="internal/plan/course_contract.json",
        )
        return _report(
            project_dir,
            contract=None,
            content_version=content_version,
            files=files,
            findings=findings,
            notes="没有产品契约，Gate B 无法判定。",
        )

    if contract.status != "approved":
        _add(
            findings,
            "product_contract_approved",
            "human",
            "课程产品契约尚未由产品负责人批准（status != approved）",
            location="internal/plan/course_contract.json",
        )

    target = _project_target(project_dir)
    if target and abs(contract.target_duration_minutes - target) > 0.01:
        _add(
            findings,
            "target_not_downgraded",
            "blocker",
            (
                f"契约目标 {contract.target_duration_minutes} 分钟与 project.yaml 的 "
                f"{target} 分钟不一致；未经授权不得降标"
            ),
            location="project.yaml",
        )

    if public is None:
        _add(findings, "public_content_present", "blocker", "缺少公开课程内容")
        return _report(
            project_dir,
            contract=contract,
            content_version=content_version,
            files=files,
            findings=findings,
        )

    slides = {slide.slide_id: slide for slide in public.slides}
    if outline is not None:
        outline_ids = {section.slide_id for section in outline.sections}
        extra = sorted(set(outline_ids) - set(slides))
        missing = sorted(set(slides) - outline_ids)
        if extra or missing:
            _add(
                findings,
                "outline_matches_content",
                "blocker",
                f"大纲与内容章节不一致：仅在大纲 {extra or '-'}；仅在内容 {missing or '-'}",
            )

    module_slides: set[str] = set()
    for module in contract.modules:
        for slide_id in module.slide_ids:
            module_slides.add(slide_id)
            if slide_id not in slides:
                _add(
                    findings,
                    "module_slide_exists",
                    "blocker",
                    f"模块 {module.module_id} 引用不存在的章节 {slide_id}",
                    location=module.module_id,
                )
    unassigned = sorted(set(slides) - module_slides)
    if unassigned:
        _add(
            findings,
            "every_slide_in_a_module",
            "blocker",
            "以下章节没有归入任何模块：" + ", ".join(unassigned),
        )

    for objective in contract.objectives:
        if not objective.required:
            continue
        weak: list[str] = []
        for slide_id in objective.slide_ids:
            slide = slides.get(slide_id)
            if slide is None:
                weak.append(f"{slide_id}(不存在)")
            elif _slide_text_length(list(slide.body)) < 120:
                weak.append(f"{slide_id}(内容过少)")
        if weak:
            _add(
                findings,
                "objective_coverage",
                "blocker",
                f"学习目标 {objective.objective_id} 未落到实质内容：" + ", ".join(weak),
                location=objective.objective_id,
            )

    formulas = sum(
        1 for slide in public.slides for block in slide.body if isinstance(block, FormulaBlock)
    )
    if formulas < contract.required_formula_count:
        _add(
            findings,
            "deliverable_formulas",
            "blocker",
            f"公式块 {formulas} 个，契约要求至少 {contract.required_formula_count} 个",
        )

    checks = [
        block for slide in public.slides for block in slide.body if isinstance(block, CheckBlock)
    ]
    if len(checks) < contract.required_check_count:
        _add(
            findings,
            "deliverable_checks",
            "blocker",
            f"学习检查 {len(checks)} 个，契约要求至少 {contract.required_check_count} 个",
        )
    for index, check in enumerate(checks, start=1):
        if not check.question.strip() or not check.answer.strip():
            _add(
                findings,
                "check_complete",
                "blocker",
                f"第 {index} 个学习检查缺少问题或答案",
            )

    if reading is not None:
        reading_ids = {section.slide_id for section in reading.sections}
        if reading_ids != set(slides):
            _add(
                findings,
                "reading_matches_slides",
                "blocker",
                f"阅读版章节与幻灯片不一致：阅读版 {sorted(reading_ids)}；幻灯片 {sorted(slides)}",
            )
    else:
        _add(findings, "reading_present", "blocker", "缺少阅读版内容")

    if script is not None:
        script_ids = {section.slide_id for section in script.sections}
        if script_ids != set(slides):
            _add(
                findings,
                "narration_matches_slides",
                "blocker",
                f"口播稿章节与幻灯片不一致：口播稿 {sorted(script_ids)}；幻灯片 {sorted(slides)}",
            )
    else:
        _add(findings, "narration_present", "blocker", "缺少口播稿")

    timing = load_timing(project_dir)
    if timing is None:
        _add(
            findings,
            "timing_evidence",
            "blocker",
            "缺少实际计时证据 internal/qa/timing_evidence.json；文本估算不能替代实测",
            location="internal/qa/timing_evidence.json",
        )
    else:
        if timing.method == "estimate":
            _add(
                findings,
                "timing_measured",
                "blocker",
                "计时证据的方法仍是 estimate；必须有完整讲解或录制的实测时长",
            )
        expected = contract.target_duration_minutes * 60
        if not (0.8 * expected <= timing.measured_seconds <= 1.3 * expected):
            _add(
                findings,
                "timing_in_range",
                "blocker",
                f"实测 {timing.measured_seconds / 60:.1f} 分钟，目标 "
                f"{contract.target_duration_minutes:.1f} 分钟（允许 80%–130%）",
            )
        script_path = project_dir / "internal" / "speaker_script.json"
        if script_path.is_file() and timing.script_sha256:
            if timing.script_sha256 != _sha256(script_path):
                _add(
                    findings,
                    "timing_matches_script",
                    "blocker",
                    "计时证据对应的口播稿与当前 speaker_script.json 不一致",
                )
        if timing.audio_path:
            audio = project_dir / timing.audio_path
            if not audio.is_file():
                _add(
                    findings,
                    "timing_audio_exists",
                    "blocker",
                    f"计时音频不存在：{timing.audio_path}",
                )
            elif timing.audio_sha256 and timing.audio_sha256 != _sha256(audio):
                _add(
                    findings,
                    "timing_audio_hash",
                    "blocker",
                    "计时音频的 SHA-256 与记录不一致",
                )

    if qa is None:
        _add(
            findings,
            "visual_qa_present",
            "blocker",
            "缺少 QA 报告；先运行 `lces validate`",
        )
    else:
        statuses = {item.check_id: item.status for item in qa.checks}
        for check_id in ("browser_pages_load", "browser_layout_no_overflow"):
            if statuses.get(check_id) != "pass":
                _add(
                    findings,
                    "visual_readability",
                    "blocker",
                    f"{check_id} 不是 pass（当前 {statuses.get(check_id, 'missing')}）",
                )

    acceptance = load_acceptance(project_dir)
    if acceptance is None:
        _add(
            findings,
            "human_course_acceptance",
            "human",
            "缺少课程产品验收人工记录 internal/qa/course_acceptance.json",
            location="internal/qa/course_acceptance.json",
        )
    else:
        if acceptance.decision != "pass":
            _add(
                findings,
                "human_course_decision",
                "human",
                f"人工课程验收结论为 {acceptance.decision}，不是 pass",
            )
        if acceptance.contract_version != contract.version:
            _add(
                findings,
                "acceptance_contract_version",
                "human",
                f"人工验收针对契约 {acceptance.contract_version}，当前为 {contract.version}",
            )
        if acceptance.content_version != content_version:
            _add(
                findings,
                "acceptance_content_version",
                "blocker",
                "人工验收后课程内容已变更，旧验收记录不再适用",
            )
        for flag, label in (
            (acceptance.timing_confirmed, "计时"),
            (acceptance.visual_confirmed, "视觉"),
            (acceptance.checks_confirmed, "学习检查"),
        ):
            if not flag:
                _add(
                    findings,
                    "acceptance_flags",
                    "human",
                    f"人工验收尚未确认{label}项",
                )

    return _report(
        project_dir,
        contract=contract,
        content_version=content_version,
        files=files,
        findings=findings,
        notes=(
            "Gate B 只判定契约、结构覆盖、交付物、计时证据和人工验收状态；"
            "讲解是否清晰、学习者是否理解必须由人工试听与学习检查确认。"
        ),
    )


def _report(
    project_dir: Path,
    *,
    contract: CourseContract | None,
    content_version: str,
    files: list[dict[str, str]],
    findings: list[QualityFinding],
    notes: str = "",
) -> CourseQualityReport:
    unique: dict[str, QualityFinding] = {}
    for finding in findings:
        unique.setdefault(finding.finding_id, finding)
    ordered = list(unique.values())
    blockers = sum(1 for item in ordered if item.severity == "blocker")
    human = sum(1 for item in ordered if item.severity == "human")
    if blockers:
        decision: Decision = "blocked"
    elif human:
        decision = "needs_human_review"
    else:
        decision = "passed"
    contract_version = contract.version if contract is not None else ""
    audit_id = (
        "course-quality-"
        + hashlib.sha256(
            f"{project_dir.name}|{contract_version}|{content_version}".encode()
        ).hexdigest()[:12]
    )
    return CourseQualityReport(
        audit_id=audit_id,
        project_id=contract.project_id if contract is not None else project_dir.name,
        contract_version=contract_version,
        content_version=content_version,
        generated_at=utc_now(),
        files=files,
        findings=ordered,
        summary={"blocker": blockers, "human": human},
        decision=decision,
        notes=notes,
    )


def quality_is_current(project_dir: Path, report: CourseQualityReport) -> list[str]:
    stale: list[str] = []
    for item in report.files:
        path = project_dir / item["path"]
        if not path.is_file() or _sha256(path) != item["sha256"]:
            stale.append(item["path"])
    return stale


def quality_status(project_dir: Path) -> CheckResult:
    """One advisory Gate 2 check so `lces validate` shows the product state."""

    report = load_quality(project_dir)
    if report is None:
        return CheckResult(
            check_id="course_product_status",
            gate="gate_2_content",
            status="not_run",
            message="未运行课程产品验收（Gate B）；运行 `lces audit-product`",
            blocking=False,
        )
    return CheckResult(
        check_id="course_product_status",
        gate="gate_2_content",
        status="warn" if report.decision != "passed" else "pass",
        message=(
            f"Gate B 课程产品验收：{report.decision}"
            f"（blocker={report.summary.get('blocker', 0)},"
            f" human={report.summary.get('human', 0)}）"
        ),
        blocking=False,
    )


def write_acceptance(project_dir: Path, acceptance: CourseAcceptance) -> Path:
    path = acceptance_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, acceptance)
    return path


__all__ = [
    "ACCEPTANCE_RELATIVE_PATH",
    "CONTRACT_RELATIVE_PATH",
    "CourseAcceptance",
    "CourseContract",
    "CourseQualityReport",
    "QUALITY_RELATIVE_PATH",
    "TIMING_RELATIVE_PATH",
    "TimingEvidence",
    "acceptance_path",
    "contract_path",
    "load_acceptance",
    "load_contract",
    "load_quality",
    "load_timing",
    "quality_is_current",
    "quality_path",
    "quality_status",
    "run_course_quality_audit",
    "timing_path",
    "write_acceptance",
    "write_quality",
]
