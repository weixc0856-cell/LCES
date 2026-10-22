"""Automated QA gates (PRD section 14).

Only checks actually implemented here may report PASS. Anything requiring a
browser, media decoder, or human scientific review is reported NOT_RUN.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from content_studio.content import (
    load_outline,
    load_public_content,
    load_speaker_script,
)
from content_studio.ingestion import load_registry
from content_studio.models import (
    CheckResult,
    Claim,
    ProjectConfig,
    QAReport,
    ReleaseManifest,
)
from content_studio.paths import PUBLIC_BUILD_ALLOWLIST
from content_studio.research import load_evidence_ledger, load_research_brief
from content_studio.utils import sha256_file, write_json

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


def run_validation(project_dir: Path, config: ProjectConfig, template_dir: Path) -> QAReport:
    project_dir = project_dir.resolve()
    checks: list[CheckResult] = []

    registry = load_registry(project_dir)
    brief = load_research_brief(project_dir)
    ledger = load_evidence_ledger(project_dir)
    outline = load_outline(project_dir)
    public = load_public_content(project_dir)
    script = load_speaker_script(project_dir)

    claims: list[Claim] = []
    claims_path = project_dir / "internal" / "claims.json"
    if claims_path.exists():
        try:
            raw = json.loads(claims_path.read_text(encoding="utf-8"))
            claims = [Claim.model_validate(item) for item in raw]
        except (ValueError, TypeError):
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

    unverified = [
        record.evidence_id
        for record in ledger.records
        if record.claim_id in {claim.claim_id for claim in key_claims}
        and record.verification_status == "unverified"
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

    checks.append(
        _check(
            "gate_3_engineering",
            "browser_visual_regression",
            "not_run",
            "Playwright 浏览器渲染与视觉回归尚未实现（Phase 3）",
            blocking=False,
        )
    )

    report = QAReport(
        project_id=config.project_id,
        provider=",".join(sorted(providers)),
        model="",
        checks=checks,
    )
    write_json(project_dir / "internal" / "qa" / "qa_report.json", report)
    return report


def run_release_checks(
    release_root: Path,
    *,
    manifest: ReleaseManifest | None,
    approval_required: bool,
    approval_present: bool,
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    if not release_root.is_dir():
        return [_check("gate_4_release", "release_directory_exists", "fail", "发布目录不存在")]

    files = sorted(
        path.relative_to(release_root).as_posix()
        for path in release_root.rglob("*")
        if path.is_file()
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

    checks.append(
        _check(
            "gate_4_release",
            "media_decode_check",
            "not_run",
            "视频/音频解码检查尚未实现（Phase 3）",
            blocking=False,
        )
    )
    return checks
