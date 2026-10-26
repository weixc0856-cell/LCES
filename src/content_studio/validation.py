"""Automated QA gates (PRD section 14).

Only checks actually implemented here may report PASS. Anything requiring a
browser, media decoder, or human scientific review is reported NOT_RUN.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from content_studio.browser_qa import OVERFLOW_TOLERANCE_PX, BrowserQAResult, run_browser_qa
from content_studio.content import (
    load_outline,
    load_public_content,
    load_speaker_script,
)
from content_studio.course_audit import (
    CourseAuditReport,
    audit_is_current,
    load_audit,
    run_course_audit,
    write_audit,
)
from content_studio.course_quality import (
    load_quality,
    quality_is_current,
    quality_status,
)
from content_studio.errors import ValidationFailure
from content_studio.evidence import is_contradicted, review_state
from content_studio.ingestion import load_registry, load_source_text
from content_studio.media import MediaError, probe_media, subtitle_problems, tool_status
from content_studio.models import (
    CheckResult,
    Claim,
    EvidenceLedger,
    FrameManifest,
    ProjectConfig,
    PublicContent,
    QAReport,
    ReleaseManifest,
)
from content_studio.paths import (
    BUILD_MARKER,
    PUBLIC_BUILD_ALLOWLIST,
    symlink_components,
    symlinks_in_tree,
)
from content_studio.planning import (
    coverage_gaps,
    load_course_master,
    load_coverage_matrix,
    load_paper_map,
    paper_map_sha256,
    unknown_paper_items,
)
from content_studio.research import load_evidence_ledger, load_research_brief
from content_studio.structured_review import (
    default_review_path,
    load_review,
    unacknowledged_conflicts,
    unsigned_items,
    validate_review_links,
)
from content_studio.utils import normalize_quote, sha256_file, write_json
from content_studio.video_qa import verify_video_against_manifest
from content_studio.visual_acceptance import acceptance_problem

PUBLIC_MARKERS = (
    "TODO",
    "待核实",
    "口播稿",
    "讲者备注",
    "内部草稿",
    "内部 QA",
    "DRAFT ONLY",
    "调试信息",
)

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{16,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"(?i)api[_-]?key\s*[:=]\s*\S{8,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{20,}"),
]

TEXT_SUFFIXES = {".html", ".htm", ".svg", ".js", ".css", ".md", ".txt", ".json", ".srt", ".vtt"}

ALLOWED_PREFIXES = ("slides/charts/",)


def _check(
    gate: str,
    check_id: str,
    status: str,
    message: str,
    *,
    blocking: bool = True,
) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        gate=gate,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        message=message,
        blocking=blocking,
    )


def find_markers(text: str) -> list[str]:
    lowered = text.lower()
    return [marker for marker in PUBLIC_MARKERS if marker.lower() in lowered]


def find_secrets(text: str) -> list[str]:
    return [pattern.pattern for pattern in SECRET_PATTERNS if pattern.search(text)]


def _generation_providers(project_dir: Path) -> set[str]:
    path = project_dir / "internal" / "qa" / "generation_trace.json"
    if not path.exists():
        return set()
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return set()
    if not isinstance(entries, list):
        return set()
    return {
        str(entry.get("provider", ""))
        for entry in entries
        if isinstance(entry, dict) and entry.get("provider")
    }


def _browser_checks(project_dir: Path, *, enabled: bool) -> list[CheckResult]:
    """Gate 3 browser checks; never claim PASS when no browser ran."""

    if not enabled:
        return [
            _check(
                "gate_3_engineering",
                "browser_visual_regression",
                "not_run",
                "已通过 LCES_BROWSER_QA=0 关闭浏览器检查",
                blocking=False,
            )
        ]

    result = run_browser_qa(project_dir)
    if not result.ran:
        return [
            _check(
                "gate_3_engineering",
                "browser_visual_regression",
                "not_run",
                result.reason or "浏览器检查未运行",
                blocking=False,
            )
        ]
    return _browser_result_checks(result)


def _browser_result_checks(result: BrowserQAResult) -> list[CheckResult]:
    visits = result.visits
    total = len(visits)

    failed_loads = [f"{visit.page}@{visit.viewport}" for visit in visits if not visit.loaded]
    checks: list[CheckResult] = []
    checks.append(
        _check(
            "gate_3_engineering",
            "browser_pages_load",
            "fail" if failed_loads else "pass",
            "加载失败: " + ", ".join(failed_loads)
            if failed_loads
            else f"{total} 个页面/视口组合均加载成功",
        )
    )

    js_errors = [
        f"{visit.page}@{visit.viewport}: {error}"
        for visit in visits
        for error in visit.javascript_errors
    ]
    checks.append(
        _check(
            "gate_3_engineering",
            "browser_no_js_errors",
            "fail" if js_errors else "pass",
            "未处理的 JavaScript 错误: " + "; ".join(js_errors[:3])
            if js_errors
            else "页面运行期无未处理 JavaScript 错误",
        )
    )

    broken = [
        f"{visit.page}@{visit.viewport}: {item}"
        for visit in visits
        for item in [*visit.broken_images, *visit.failed_requests]
        if "favicon.ico" not in item
    ]
    checks.append(
        _check(
            "gate_3_engineering",
            "browser_resources_loaded",
            "fail" if broken else "pass",
            "资源加载失败: " + "; ".join(broken[:3]) if broken else "本地图片与资源均加载成功",
        )
    )

    worst = max(visits, key=lambda visit: visit.overflow_px, default=None)
    overflow = worst is not None and worst.overflow_px > OVERFLOW_TOLERANCE_PX
    checks.append(
        _check(
            "gate_3_engineering",
            "browser_layout_no_overflow",
            "fail" if overflow else "pass",
            f"视口 {worst.viewport} 出现 {worst.overflow_px}px 横向溢出"
            if overflow and worst is not None
            else f"{total} 个视口均无横向溢出",
        )
    )

    screenshots = f"截图: internal/qa/screenshots（{total} 张）"
    if result.visual_changes:
        changed = ", ".join(result.visual_changes)
        checks.append(
            _check(
                "gate_3_engineering",
                "browser_visual_regression",
                "warn",
                f"与基准截图不同: {changed}；需人工确认。{screenshots}",
                blocking=False,
            )
        )
    elif result.baselines_created:
        checks.append(
            _check(
                "gate_3_engineering",
                "browser_visual_regression",
                "pass",
                f"已建立基准截图 {len(result.baselines_created)} 张。{screenshots}",
                blocking=False,
            )
        )
    else:
        checks.append(
            _check(
                "gate_3_engineering",
                "browser_visual_regression",
                "pass",
                f"与基准截图一致。{screenshots}",
                blocking=False,
            )
        )
    return checks


def _evidence_quote_checks(project_dir: Path, ledger: EvidenceLedger) -> list[CheckResult]:
    """A quoted excerpt should exist in the source text; otherwise flag it.

    Locator presence is already checked. This goes one step further: the
    model can invent a plausible quote and a plausible locator, and only a
    substring test against the extracted source catches it.

    Nothing is silently skipped: a missing excerpt, an unavailable source
    text or a too-short excerpt is reported as unverifiable with its
    evidence id. The check warns rather than blocks because normalisation
    can fail on unusual typography.
    """

    unmatched: list[str] = []
    unverifiable: list[str] = []
    structural: list[str] = []
    compared = 0
    for record in ledger.records:
        # A table row or a formula is not a quote. Those records are checked
        # by the structured validator and their review records; comparing
        # them to the prose source would only produce a false warning.
        if record.evidence_type in {"table", "formula"}:
            structural.append(record.evidence_id)
            continue
        excerpt = record.source_excerpt.strip()
        if not excerpt:
            unverifiable.append(f"{record.evidence_id}(缺少摘录)")
            continue
        source = load_source_text(project_dir, record.source_id)
        if not source:
            unverifiable.append(f"{record.evidence_id}(来源文本不可用)")
            continue
        normalized = normalize_quote(excerpt)
        if len(normalized) < 12:
            unverifiable.append(f"{record.evidence_id}(摘录过短)")
            continue
        compared += 1
        if normalized not in normalize_quote(source):
            unmatched.append(record.evidence_id)
    if not ledger.records:
        return []
    problems: list[str] = []
    if unmatched:
        problems.append("未在来源中找到：" + ", ".join(unmatched))
    if unverifiable:
        problems.append("无法核对：" + ", ".join(unverifiable))
    excluded = (
        f"；{len(structural)} 条表格/公式证据按结构检查，未按引文检查：" + ", ".join(structural)
        if structural
        else ""
    )
    return [
        _check(
            "gate_1_research",
            "evidence_quotes_in_source",
            "warn" if problems else "pass",
            ("；".join(problems) if problems else f"{compared} 条证据摘录均可在来源文本中找到")
            + excluded,
            blocking=False,
        )
    ]


def _claim_review_checks(
    claims: list[Claim], ledger: EvidenceLedger, claims_error: str
) -> list[CheckResult]:
    """Gate 1 review-state checks. Unparseable claims are reported elsewhere."""

    key_claims = [claim for claim in claims if claim.importance == "key"]
    if not key_claims or claims_error:
        return []

    checks: list[CheckResult] = []
    contradicted_claims = [
        claim.claim_id for claim in key_claims if is_contradicted(claim.verification_status)
    ]
    checks.append(
        _check(
            "gate_1_research",
            "contradicted_claims_blocked",
            "fail" if contradicted_claims else "pass",
            "关键主张与证据冲突：" + ", ".join(contradicted_claims)
            if contradicted_claims
            else "关键主张未与证据冲突",
        )
    )

    pending_claims = [
        claim.claim_id
        for claim in key_claims
        if review_state(claim.verification_status, claim.reviewer)
        not in {"supported", "not_applicable", "contradicted"}
    ]
    checks.append(
        _check(
            "gate_1_research",
            "pending_claims_flagged",
            "warn" if pending_claims else "pass",
            "关键主张尚未完成人工核验：" + ", ".join(pending_claims)
            if pending_claims
            else "关键主张均已记录核验状态",
            blocking=False,
        )
    )

    if ledger.records:
        key_claim_ids = {claim.claim_id for claim in key_claims}
        missing_locator = [
            record.evidence_id
            for record in ledger.records
            if record.claim_id in key_claim_ids
            and not record.locator.strip()
            and not record.source_excerpt.strip()
        ]
        checks.append(
            _check(
                "gate_1_research",
                "evidence_locators_present",
                "warn" if missing_locator else "pass",
                "证据缺少定位与摘录：" + ", ".join(missing_locator)
                if missing_locator
                else "关键证据均带定位信息或原文摘录",
                blocking=False,
            )
        )
    return checks


def _coverage_checks(project_dir: Path) -> list[CheckResult]:
    """Check that required paper elements have a teaching unit.

    A project without a PaperMap/CourseMaster/coverage matrix reports
    ``not_run``: the absence of planning data is not evidence of coverage.
    """

    paper_map = load_paper_map(project_dir)
    master = load_course_master(project_dir)
    matrix = load_coverage_matrix(project_dir)
    if paper_map is None or master is None or matrix is None:
        return [
            _check(
                "gate_2_content",
                "coverage_matrix_complete",
                "not_run",
                "未找到 PaperMap、CourseMaster 或覆盖矩阵，覆盖完整性未检查",
                blocking=False,
            )
        ]

    current = paper_map_sha256(project_dir)
    if matrix.paper_map_sha256 and matrix.paper_map_sha256 != current:
        return [
            _check(
                "gate_2_content",
                "coverage_matrix_complete",
                "fail",
                "覆盖矩阵基于另一版 PaperMap 构建；重新运行 plan-coverage",
            )
        ]

    problems: list[str] = []
    unknown = unknown_paper_items(paper_map, master)
    if unknown:
        problems.append("教学单元引用了不存在的论文要素：" + ", ".join(unknown))
    gaps = coverage_gaps(paper_map, matrix)
    if gaps:
        problems.append("必需要素没有教学单元：" + ", ".join(gaps))

    if problems:
        return [
            _check(
                "gate_2_content",
                "coverage_matrix_complete",
                "fail",
                "；".join(problems),
            )
        ]
    required = sum(1 for element in paper_map.elements if element.required)
    return [
        _check(
            "gate_2_content",
            "coverage_matrix_complete",
            "pass",
            f"{len(paper_map.elements)} 个论文要素中 {required} 个必需要素均有教学单元",
        )
    ]


def _course_audit_checks(project_dir: Path) -> list[CheckResult]:
    """Gate 2: the shown numbers/formulas must match the reviewed evidence."""

    if not (project_dir / "content" / "public_content.json").is_file():
        return [
            _check(
                "gate_2_content",
                "course_content_audit",
                "not_run",
                "没有公开课程内容，内容一致性审计未运行（未运行不代表通过）",
                blocking=False,
            )
        ]
    report = run_course_audit(project_dir)
    write_audit(project_dir, report)
    if report.decision in {"blocked", "needs_correction"}:
        details = [
            f"{finding.severity}/{finding.check_type}@{finding.location}"
            for finding in [*report.blockers, *report.majors]
        ]
        return [
            _check(
                "gate_2_content",
                "course_content_audit",
                "fail",
                f"课程内容与复核证据不一致（{report.decision}）：" + "; ".join(details),
            )
        ]
    return [
        _check(
            "gate_2_content",
            "course_content_audit",
            "pass",
            f"课程版本 {report.course_version[:12]} 的数值与公式一致（"
            f"blocker=0, major=0, advisory={report.summary.get('advisory', 0)}）",
        )
    ]


def _course_release_checks(project_dir: Path, release_root: Path) -> list[CheckResult]:
    """Gate 4: signatures, conflict disclosure and the audited version."""

    review_path = default_review_path(project_dir)
    has_content = (project_dir / "content" / "public_content.json").is_file()
    if not has_content and not review_path.is_file():
        return []

    checks: list[CheckResult] = []
    ledger = load_evidence_ledger(project_dir)
    structured = [
        record for record in ledger.records if record.evidence_type in {"formula", "table"}
    ]
    if review_path.is_file():
        try:
            document = load_review(review_path)
            validate_review_links(project_dir, document)
        except ValidationFailure as exc:
            checks.append(
                _check(
                    "gate_4_release",
                    "structured_evidence_review_valid",
                    "fail",
                    f"结构化证据复核记录不可用：{exc}",
                )
            )
        else:
            checks.append(
                _check(
                    "gate_4_release",
                    "structured_evidence_review_valid",
                    "pass",
                    f"{len(document.items)} 条结构化证据复核记录均可追溯",
                )
            )
            unsigned = unsigned_items(document)
            checks.append(
                _check(
                    "gate_4_release",
                    "structured_evidence_signed",
                    "fail" if unsigned else "pass",
                    "结构化证据缺少人工结论："
                    + ", ".join(f"{item.review_id}={item.conclusion}" for item in unsigned)
                    if unsigned
                    else "结构化证据均有人工结论",
                )
            )
            conflicts = unacknowledged_conflicts(document)
            checks.append(
                _check(
                    "gate_4_release",
                    "source_conflicts_acknowledged",
                    "fail" if conflicts else "pass",
                    "来源冲突未显式确认：" + ", ".join(item.review_id for item in conflicts)
                    if conflicts
                    else "来源冲突均已确认或不存在",
                )
            )
    elif structured:
        checks.append(
            _check(
                "gate_4_release",
                "structured_evidence_review_valid",
                "fail",
                "存在结构化公式/表格证据，但没有复核记录；未复核证据不得发布",
            )
        )

    report = load_audit(project_dir)
    if report is None:
        checks.append(
            _check(
                "gate_4_release",
                "course_content_audit_current",
                "fail",
                "缺少课程内容审计报告；先运行 `lces audit-course`",
            )
        )
    else:
        stale = audit_is_current(project_dir, report)
        checks.append(
            _check(
                "gate_4_release",
                "course_content_audit_current",
                "fail" if stale else "pass",
                "课程内容在审计后已变更，旧审计结论不再适用：" + ", ".join(stale)
                if stale
                else f"审计对应当前课程版本 {report.course_version[:12]}",
            )
        )
        checks.append(
            _check(
                "gate_4_release",
                "course_content_audit_passed",
                "fail" if report.decision in {"blocked", "needs_correction"} else "pass",
                (
                    f"课程内容审计结论：{report.decision}；"
                    + "; ".join(
                        f"{finding.severity}/{finding.check_type}@{finding.location}"
                        for finding in [*report.blockers, *report.majors]
                    )
                )
                if report.decision in {"blocked", "needs_correction"}
                else f"课程内容审计通过（版本 {report.course_version[:12]}）",
            )
        )
        checks.append(_release_matches_audit(release_root, report))

    contract_defined = (project_dir / "internal" / "plan" / "course_contract.json").is_file() or (
        project_dir / "internal" / "qa" / "course_quality_audit.json"
    ).is_file()
    quality = load_quality(project_dir)
    if not contract_defined:
        # Gate B is opt-in until a project freezes a product contract. NOT_RUN is
        # reported, never PASS; a contract-bearing project must pass all checks.
        checks.append(
            _check(
                "gate_4_release",
                "course_product_qualified",
                "not_run",
                "未定义课程产品契约；Gate B 未运行（未运行不代表通过）",
                blocking=False,
            )
        )
    elif quality is None:
        checks.append(
            _check(
                "gate_4_release",
                "course_product_qualified",
                "fail",
                "缺少 Gate B 课程产品验收报告；先运行 `lces audit-product`",
            )
        )
    else:
        stale = quality_is_current(project_dir, quality)
        checks.append(
            _check(
                "gate_4_release",
                "course_product_current",
                "fail" if stale else "pass",
                "课程产品验收后内容已变更，旧结论不再适用：" + ", ".join(stale)
                if stale
                else f"Gate B 对应当前内容版本 {quality.content_version[:12]}",
            )
        )
        labels = [
            f"{finding.severity}/{finding.check_id}: {finding.message}"
            for finding in [*quality.blockers, *quality.human_items]
        ]
        if quality.blockers:
            checks.append(
                _check(
                    "gate_4_release",
                    "course_product_qualified",
                    "fail",
                    "Gate B 课程产品验收存在阻断项：" + "; ".join(labels),
                )
            )
        elif quality.human_items:
            checks.append(
                _check(
                    "gate_4_release",
                    "course_product_qualified",
                    "pass",
                    "Gate B 自动化检查通过；以下人工项尚未完成",
                )
            )
            checks.append(
                _check(
                    "gate_4_release",
                    "course_product_human_pending",
                    "fail",
                    "Gate B 人工验收尚未完成：" + "; ".join(labels),
                )
            )
        else:
            checks.append(
                _check(
                    "gate_4_release",
                    "course_product_qualified",
                    "pass",
                    f"Gate B 课程产品验收通过（{quality.content_version[:12]}）",
                )
            )
    return checks


def _release_matches_audit(release_root: Path, report: CourseAuditReport) -> CheckResult:
    audited = {item.path: item.sha256 for item in report.files if item.path.startswith("build/")}
    problems: list[str] = []
    mapping = {
        "slides/index.html": "build/slides/index.html",
        "reading_edition.html": "build/reading_edition.html",
    }
    for released, built in mapping.items():
        path = release_root / released
        if not path.is_file():
            continue
        if built not in audited:
            problems.append(f"{released}(未审计)")
        elif sha256_file(path) != audited[built]:
            problems.append(f"{released}(与审计版本不一致)")
    return _check(
        "gate_4_release",
        "release_matches_audited_content",
        "fail" if problems else "pass",
        "发布资产不是被审计的课程版本：" + ", ".join(problems)
        if problems
        else "发布资产与被审计版本一致",
    )


SIGNATURE_CHECK_IDS = {
    "structured_evidence_signed",
    "source_conflicts_acknowledged",
    "course_product_human_pending",
}


def release_decision(checks: list[CheckResult], *, conflict_disclosed: bool = False) -> str:
    """Classify a release without hiding why it was refused."""

    failures = [item for item in checks if item.status == "fail" and item.blocking]
    if not failures:
        return "approved_with_disclosures" if conflict_disclosed else "approved"
    if all(item.check_id in SIGNATURE_CHECK_IDS for item in failures):
        return "needs_human_review"
    return "blocked"


VALIDATION_FILES = (
    Path("content") / "public_content.json",
    Path("content") / "reading_edition.json",
    Path("content") / "outline.json",
    Path("internal") / "speaker_script.json",
    Path("build") / "slides" / "index.html",
    Path("build") / "reading_edition.html",
)


def content_version(project_dir: Path) -> tuple[str, list[dict[str, str]]]:
    """Fingerprint the artefacts a validation pass is about.

    Content, narration and the built HTML -- what Gates 1-3 read. Gate B's
    fingerprint adds the product contract, because a contract change must
    invalidate the human acceptance; validation deliberately excludes it.
    Editing any bound file after ``lces validate`` makes the report stale and
    the release gate refuses to reuse it (SAD-001 §9.3, TDD-001 §11.1).
    """

    files: list[dict[str, str]] = []
    for relative in VALIDATION_FILES:
        path = project_dir / relative
        if path.is_file():
            files.append({"path": relative.as_posix(), "sha256": sha256_file(path)})
    payload = "\n".join(f"{item['path']}:{item['sha256']}" for item in files)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest(), files


def run_validation(
    project_dir: Path,
    config: ProjectConfig,
    template_dir: Path,
    *,
    browser_qa: bool = True,
) -> QAReport:
    project_dir = project_dir.resolve()
    qa_links = symlink_components(project_dir / "internal" / "qa", project_dir)
    if qa_links:
        raise ValidationFailure(f"internal/qa contains a symlink: {qa_links[0]}")
    checks: list[CheckResult] = []

    registry = load_registry(project_dir)
    brief = load_research_brief(project_dir)
    ledger = load_evidence_ledger(project_dir)
    outline = load_outline(project_dir)
    public = load_public_content(project_dir)
    script = load_speaker_script(project_dir)

    claims: list[Claim] = []
    claims_error = ""
    claims_path = project_dir / "internal" / "claims.json"
    if claims_path.exists():
        try:
            raw = json.loads(claims_path.read_text(encoding="utf-8"))
            claims = [Claim.model_validate(item) for item in raw]
        except (ValueError, TypeError) as exc:
            # A broken claims file must not silently become "no claims".
            claims_error = f"{exc.__class__.__name__}: {exc}"
            claims = []

    # --- Gate 1 -------------------------------------------------------
    if registry is None or not registry.sources:
        checks.append(
            _check("gate_1_research", "source_registry_exists", "fail", "来源台账缺失或为空")
        )
    else:
        checks.append(
            _check(
                "gate_1_research",
                "source_registry_exists",
                "pass",
                f"来源台账包含 {len(registry.sources)} 条来源",
            )
        )
        unavailable = [s.source_id for s in registry.sources if s.access_status != "fetched"]
        checks.append(
            _check(
                "gate_1_research",
                "sources_available",
                "warn" if unavailable else "pass",
                "部分来源不可用或不完整：" + ", ".join(unavailable)
                if unavailable
                else "所有来源均已获取",
            )
        )

    if brief is None:
        checks.append(_check("gate_1_research", "research_brief_exists", "fail", "研究简报缺失"))
    else:
        checks.append(_check("gate_1_research", "research_brief_exists", "pass", "研究简报存在"))

    if claims_path.exists():
        checks.append(
            _check(
                "gate_1_research",
                "claims_parse",
                "fail" if claims_error else "pass",
                f"claims.json 无法解析：{claims_error}"
                if claims_error
                else f"claims.json 可解析（{len(claims)} 条主张）",
            )
        )

    source_ids = {s.source_id for s in registry.sources} if registry else set()
    claim_ids = {claim.claim_id for claim in claims}
    bad_refs = [
        record.evidence_id
        for record in ledger.records
        if record.source_id not in source_ids or record.claim_id not in claim_ids
    ]
    if not ledger.records:
        checks.append(
            _check("gate_1_research", "evidence_references_valid", "fail", "证据台账为空")
        )
    elif bad_refs:
        checks.append(
            _check(
                "gate_1_research",
                "evidence_references_valid",
                "fail",
                "证据引用了不存在的来源或主张：" + ", ".join(bad_refs),
            )
        )
    else:
        checks.append(
            _check("gate_1_research", "evidence_references_valid", "pass", "证据引用均可解析")
        )

    supported_claims = {
        record.claim_id
        for record in ledger.records
        if record.support_relation in {"supports", "partially_supports"}
    }
    key_claims = [claim for claim in claims if claim.importance == "key"]
    missing = [claim.claim_id for claim in key_claims if claim.claim_id not in supported_claims]
    if not key_claims:
        checks.append(
            _check("gate_1_research", "key_claims_have_evidence", "fail", "没有识别出关键主张")
        )
    elif missing:
        checks.append(
            _check(
                "gate_1_research",
                "key_claims_have_evidence",
                "fail",
                "关键主张缺少支持证据：" + ", ".join(missing),
            )
        )
    else:
        checks.append(
            _check("gate_1_research", "key_claims_have_evidence", "pass", "关键主张均有支持证据")
        )

    checks.extend(_claim_review_checks(claims, ledger, claims_error))
    checks.extend(_evidence_quote_checks(project_dir, ledger))

    unverified = [
        record.evidence_id
        for record in ledger.records
        if record.claim_id in {claim.claim_id for claim in key_claims}
        and review_state(record.verification_status, record.reviewer) == "pending"
    ]
    checks.append(
        _check(
            "gate_1_research",
            "unverified_key_evidence_flagged",
            "warn" if unverified else "pass",
            "关键证据尚未人工核验：" + ", ".join(unverified)
            if unverified
            else "关键证据均已标记核验状态",
        )
    )
    checks.append(
        _check(
            "gate_1_research",
            "scientific_review",
            "not_run",
            "公式、量纲、因果关系与科学解释未自动审查，须人工核验",
            blocking=False,
        )
    )

    # --- Gate 2 -------------------------------------------------------
    if public is None:
        checks.append(
            _check("gate_2_content", "public_content_schema_valid", "fail", "公开内容缺失")
        )
    else:
        try:
            checks.append(
                _check(
                    "gate_2_content",
                    "public_content_schema_valid",
                    "pass",
                    f"公开内容通过 Schema 校验，共 {len(public.slides)} 节",
                )
            )
        except ValueError as exc:  # defensive: loader normally raises already
            checks.append(_check("gate_2_content", "public_content_schema_valid", "fail", str(exc)))

    if script is None:
        checks.append(
            _check(
                "gate_2_content", "speaker_script_separate", "fail", "口播稿缺失或不在 internal/"
            )
        )
        checks.append(
            _check("gate_2_content", "speaker_script_covers_slides", "fail", "口播稿缺失")
        )
    else:
        public_text = (
            json.dumps(public.model_dump(mode="json"), ensure_ascii=False) if public else ""
        )
        leaked = [
            section.slide_id
            for section in script.sections
            if len(section.narration) >= 40 and section.narration[:40] in public_text
        ]
        checks.append(
            _check(
                "gate_2_content",
                "speaker_script_separate",
                "fail" if leaked else "pass",
                "口播稿内容出现在公开数据中：" + ", ".join(leaked)
                if leaked
                else "公开内容与口播稿为独立文件与独立模型",
            )
        )
        expected = [slide.slide_id for slide in public.slides] if public else []
        actual = [section.slide_id for section in script.sections]
        ok = bool(expected) and actual == expected
        checks.append(
            _check(
                "gate_2_content",
                "speaker_script_covers_slides",
                "pass" if ok else "fail",
                "口播稿与展示章节一一对应"
                if ok
                else f"口播稿章节不匹配：期望 {expected}，实际 {actual}",
            )
        )

    if public is not None:
        markers = find_markers(json.dumps(public.model_dump(mode="json"), ensure_ascii=False))
        checks.append(
            _check(
                "gate_2_content",
                "public_text_clean",
                "fail" if markers else "pass",
                "公开内容包含内部标记：" + ", ".join(markers) if markers else "公开内容无内部标记",
            )
        )
        uncited = [slide.slide_id for slide in public.slides if not slide.source_ids]
        checks.append(
            _check(
                "gate_2_content",
                "citations_have_source_ids",
                "fail" if uncited else "pass",
                "以下章节没有来源引用：" + ", ".join(uncited)
                if uncited
                else "所有章节均带来源引用",
            )
        )

    providers = _generation_providers(project_dir)
    checks.append(
        _check(
            "gate_2_content",
            "no_mock_provider_in_release",
            "fail" if "mock" in providers else "pass",
            "内容由 mock provider 生成，禁止发布"
            if "mock" in providers
            else "内容未使用 mock provider",
        )
    )

    if script is not None and config.target_duration_minutes > 0:
        actual_minutes = script.total_estimated_seconds / 60
        target = config.target_duration_minutes
        tolerance = max(3.0, target * 0.35)
        within = abs(actual_minutes - target) <= tolerance
        checks.append(
            _check(
                "gate_2_content",
                "duration_within_tolerance",
                "pass" if within else "warn",
                f"预计 {actual_minutes:.1f} 分钟，目标 {target} 分钟（估算方法：{4.2} 字/秒）",
            )
        )

    if outline is None:
        checks.append(_check("gate_2_content", "outline_exists", "fail", "课程大纲缺失"))

    checks.extend(_coverage_checks(project_dir))
    checks.extend(_course_audit_checks(project_dir))
    checks.append(quality_status(project_dir))

    # --- Gate 3 -------------------------------------------------------
    html_path = project_dir / "build" / "slides" / "index.html"
    if not html_path.exists():
        checks.append(
            _check("gate_3_engineering", "public_html_built", "fail", "公开 HTML 尚未构建")
        )
    else:
        checks.append(_check("gate_3_engineering", "public_html_built", "pass", "公开 HTML 已构建"))
        try:
            html = html_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            checks.append(
                _check("gate_3_engineering", "public_html_utf8", "fail", "HTML 不是 UTF-8")
            )
        else:
            checks.append(_check("gate_3_engineering", "public_html_utf8", "pass", "HTML 为 UTF-8"))
            markers = find_markers(html)
            checks.append(
                _check(
                    "gate_3_engineering",
                    "no_internal_markers_in_html",
                    "fail" if markers else "pass",
                    "HTML 含内部标记：" + ", ".join(markers) if markers else "HTML 无内部标记",
                )
            )
            external = re.findall(r'(?:src|href)\s*=\s*["\']https?://', html, flags=re.IGNORECASE)
            checks.append(
                _check(
                    "gate_3_engineering",
                    "no_external_assets",
                    "warn" if external else "pass",
                    f"发现 {len(external)} 个外部资源引用，离线预览可能失败"
                    if external
                    else "无外部脚本/样式依赖",
                )
            )

    if public is not None:
        missing_figures = []
        for slide in public.slides:
            for block in slide.body:
                if block.type == "figure":
                    candidate = project_dir / "content" / block.path
                    if not candidate.exists():
                        missing_figures.append(block.path)
        checks.append(
            _check(
                "gate_3_engineering",
                "figures_exist",
                "fail" if missing_figures else "pass",
                "缺少图表文件：" + ", ".join(missing_figures)
                if missing_figures
                else "引用的图表文件均存在",
            )
        )

        checks.extend(_animation_media_checks(project_dir, public))

    checks.append(_build_committed_check(project_dir))
    checks.extend(_browser_checks(project_dir, enabled=browser_qa))

    version, bound_files = content_version(project_dir)
    report = QAReport(
        project_id=config.project_id,
        provider=",".join(sorted(providers)),
        model="",
        checks=checks,
        content_version=version,
        content_files=bound_files,
    )
    write_json(project_dir / "internal" / "qa" / "qa_report.json", report)
    return report


def _animation_media_checks(project_dir: Path, public: PublicContent) -> list[CheckResult]:
    has_animation = any(
        block.type == "animation" for slide in public.slides for block in slide.body
    )
    if not has_animation:
        return []
    required = {
        "build/media/course.mp4": project_dir / "build" / "media" / "course.mp4",
        "internal/qa/frame_manifest.json": project_dir / "internal" / "qa" / "frame_manifest.json",
        "internal/qa/encode_report.json": project_dir / "internal" / "qa" / "encode_report.json",
    }
    missing = [name for name, path in required.items() if not path.is_file()]
    return [
        _check(
            "gate_3_engineering",
            "animation_media_exists",
            "fail" if missing else "pass",
            "动画媒体或证据缺失：" + ", ".join(missing)
            if missing
            else "动画视频、帧清单与编码记录均存在",
        )
    ]


def _build_committed_check(project_dir: Path) -> CheckResult:
    marker = project_dir / "build" / BUILD_MARKER
    return _check(
        "gate_3_engineering",
        "build_committed",
        "fail" if marker.is_file() else "pass",
        "构建未完成（build/.build-in-progress 仍存在）" if marker.is_file() else "构建已提交",
    )


def run_release_checks(
    release_root: Path,
    *,
    manifest: ReleaseManifest | None,
    approval_required: bool,
    approval_present: bool,
    project_dir: Path | None = None,
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    if project_dir is not None:
        root_links = symlink_components(release_root, project_dir.resolve())
        if root_links:
            # Known-bad root: stop before reading external content.
            return [
                _check(
                    "gate_4_release",
                    "no_symlinks",
                    "fail",
                    "发布目录路径包含符号链接："
                    + ", ".join(link.as_posix() for link in root_links),
                )
            ]
    if not release_root.is_dir():
        return [_check("gate_4_release", "release_directory_exists", "fail", "发布目录不存在")]

    links = symlinks_in_tree(release_root)
    checks.append(
        _check(
            "gate_4_release",
            "no_symlinks",
            "fail" if links else "pass",
            "发布目录包含符号链接：" + ", ".join(link.as_posix() for link in links)
            if links
            else "发布目录无符号链接",
        )
    )

    files = sorted(
        path.relative_to(release_root).as_posix()
        for path in release_root.rglob("*")
        if path.is_file() and not path.is_symlink()
    )
    unexpected = [
        name
        for name in files
        if name not in PUBLIC_BUILD_ALLOWLIST
        and not any(name.startswith(prefix) for prefix in ALLOWED_PREFIXES)
    ]
    checks.append(
        _check(
            "gate_4_release",
            "allowlist_only",
            "fail" if unexpected else "pass",
            "发布目录包含白名单以外的文件：" + ", ".join(unexpected)
            if unexpected
            else "发布目录仅包含白名单文件",
        )
    )

    marker_hits: list[str] = []
    secret_hits: list[str] = []
    for name in files:
        path = release_root / name
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            checks.append(
                _check("gate_4_release", "text_assets_utf8", "fail", f"{name} 不是 UTF-8 文本")
            )
            continue
        markers = find_markers(text)
        if markers:
            marker_hits.append(f"{name}({','.join(markers)})")
        secrets = find_secrets(text)
        if secrets:
            secret_hits.append(name)

    checks.append(
        _check(
            "gate_4_release",
            "no_internal_markers",
            "fail" if marker_hits else "pass",
            "发布资产含内部标记：" + "; ".join(marker_hits)
            if marker_hits
            else "发布资产无内部标记",
        )
    )
    checks.append(
        _check(
            "gate_4_release",
            "no_secret_patterns",
            "fail" if secret_hits else "pass",
            "疑似密钥：" + ", ".join(secret_hits) if secret_hits else "未发现密钥模式",
        )
    )

    if manifest is None:
        checks.append(_check("gate_4_release", "manifest_hashes_match", "fail", "发布清单缺失"))
    else:
        mismatched = []
        listed = {item.path for item in manifest.files}
        for item in manifest.files:
            path = release_root / item.path
            if not path.is_file():
                mismatched.append(f"{item.path}(missing)")
                continue
            if sha256_file(path) != item.sha256:
                mismatched.append(f"{item.path}(hash)")
        actual = {name for name in files if name != "release_manifest.json"}
        if actual != listed:
            mismatched.append("file list differs from manifest")
        checks.append(
            _check(
                "gate_4_release",
                "manifest_hashes_match",
                "fail" if mismatched else "pass",
                "发布清单不一致：" + ", ".join(mismatched)
                if mismatched
                else "发布清单与文件哈希一致",
            )
        )

    if approval_required:
        checks.append(
            _check(
                "gate_4_release",
                "human_approval_recorded",
                "pass" if approval_present else "fail",
                "人工审批已记录" if approval_present else "缺少人工审批记录",
            )
        )
    else:
        checks.append(
            _check(
                "gate_4_release",
                "human_approval_recorded",
                "warn",
                "项目配置不要求人工审批（不建议用于正式发布）",
            )
        )

    if manifest is not None and manifest.manifest_schema_version.split(".", 1)[0] != "1":
        problems: list[str] = []
        if not manifest.content_version:
            problems.append("content_version 为空")
        if manifest.decision not in {"approved", "approved_with_disclosures"}:
            problems.append(f"decision={manifest.decision or '空'}")
        if manifest.disclosures and manifest.decision != "approved_with_disclosures":
            problems.append("记录了披露但 decision 不是 approved_with_disclosures")
        if manifest.limitations and manifest.decision != "approved_with_disclosures":
            problems.append("存在 NOT_RUN 限制但 decision 不是 approved_with_disclosures")
        checks.append(
            _check(
                "gate_4_release",
                "manifest_lineage",
                "fail" if problems else "pass",
                "发布清单的版本绑定不完整：" + "; ".join(problems)
                if problems
                else (
                    f"发布清单绑定了内容 {manifest.content_version[:12]}、"
                    f"课程 {manifest.course_version or '-'}、"
                    f"代码 {manifest.code_version[:12] or '-'}"
                ),
            )
        )
        if not manifest.code_version:
            checks.append(
                _check(
                    "gate_4_release",
                    "manifest_code_version",
                    "warn",
                    "发布清单没有记录代码版本（构建不在 Git 工作区内）",
                    blocking=False,
                )
            )

    if project_dir is not None:
        checks.extend(_course_release_checks(project_dir, release_root))
    checks.extend(_media_checks(release_root, project_dir=project_dir))
    return checks


def _media_checks(release_root: Path, *, project_dir: Path | None = None) -> list[CheckResult]:
    """Gate 4 media checks: decode, audio presence, subtitle timing."""

    media_dir = release_root / "media"
    video = media_dir / "course.mp4"
    subtitles = [
        media_dir / name for name in ("course.srt", "course.vtt") if (media_dir / name).is_file()
    ]
    if not video.is_file() and not subtitles:
        return [
            _check(
                "gate_4_release",
                "media_decode_check",
                "not_run",
                "发布物未包含媒体文件",
                blocking=False,
            )
        ]

    available, reason = tool_status()
    if not available:
        return [_check("gate_4_release", "media_decode_check", "not_run", reason, blocking=False)]

    checks: list[CheckResult] = []
    duration: float | None = None
    if video.is_file():
        try:
            info = probe_media(video)
        except MediaError as exc:
            checks.append(
                _check("gate_4_release", "media_decodable", "fail", f"视频无法解码: {exc}")
            )
        else:
            duration = info.duration_seconds
            checks.append(
                _check("gate_4_release", "media_decodable", "pass", f"视频可解码: {info.summary()}")
            )
            checks.append(
                _check(
                    "gate_4_release",
                    "media_audio_present",
                    "pass" if info.has_audio else "warn",
                    f"音频流: {info.audio_codec}" if info.has_audio else "视频不含音频流",
                    blocking=False,
                )
            )
    for subtitle in subtitles:
        problems = subtitle_problems(subtitle, duration)
        checks.append(
            _check(
                "gate_4_release",
                "subtitle_timing",
                "fail" if problems else "pass",
                "; ".join(problems) if problems else f"{subtitle.name} 字幕时间轴有效",
            )
        )
    if project_dir is not None and video.is_file():
        checks.extend(_manifest_video_checks(video, project_dir))
    return checks


def _manifest_video_checks(video: Path, project_dir: Path) -> list[CheckResult]:
    """Gate 4 re-reads the manifest and the video; it never trusts a flag."""

    qa_dir = project_dir / "internal" / "qa"
    manifest_path = qa_dir / "frame_manifest.json"
    if not manifest_path.is_file():
        return [
            _check(
                "gate_4_release",
                "video_matches_manifest",
                "warn",
                "视频存在但没有 FrameManifest，无法独立核对",
                blocking=False,
            )
        ]
    try:
        frame_manifest = FrameManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
    except ValueError as exc:
        return [
            _check(
                "gate_4_release",
                "video_matches_manifest",
                "fail",
                f"FrameManifest 无法解析: {exc}",
            )
        ]
    problems = verify_video_against_manifest(video, frame_manifest)
    checks = [
        _check(
            "gate_4_release",
            "video_matches_manifest",
            "fail" if problems else "pass",
            "; ".join(problems) if problems else "视频与 FrameManifest 一致",
        )
    ]
    report_path = qa_dir / "encode_report.json"
    if report_path.is_file():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except ValueError:
            report = {}
        expected = report.get("video_sha256") if isinstance(report, dict) else None
        if isinstance(expected, str) and expected:
            actual = sha256_file(video)
            checks.append(
                _check(
                    "gate_4_release",
                    "video_hash_matches_encode_report",
                    "pass" if expected == actual else "fail",
                    "视频哈希与编码记录一致" if expected == actual else "视频哈希与编码记录不一致",
                )
            )
    checks.extend(_visual_acceptance_checks(project_dir))
    return checks


def _visual_acceptance_checks(project_dir: Path) -> list[CheckResult]:
    """P2.4-D: a machine may fail an asset; only a person may accept it."""

    qa_dir = project_dir / "internal" / "qa"
    visual_path = qa_dir / "visual_qa.json"
    if not visual_path.is_file():
        return [
            _check(
                "gate_4_release",
                "visual_acceptance",
                "warn",
                "视频存在但没有 visual_qa.json，无法核对人工视觉验收",
                blocking=False,
            )
        ]
    try:
        visual = json.loads(visual_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [
            _check(
                "gate_4_release",
                "visual_acceptance",
                "fail",
                "visual_qa.json 无法解析，无法核对人工视觉验收",
            )
        ]
    if not isinstance(visual, dict) or visual.get("status") != "pass":
        return [
            _check(
                "gate_4_release",
                "visual_acceptance",
                "fail",
                "视觉检查未通过，人工验收不能替代它",
            )
        ]
    template = str(visual.get("template") or "")
    problem = acceptance_problem(project_dir, template=template)
    return [
        _check(
            "gate_4_release",
            "visual_acceptance",
            "pass" if not problem else "fail",
            problem or f"{template} 已有与当前工具链匹配的人工视觉验收",
        )
    ]
