"""Command-line interface for Local Content Engineering Studio."""

from __future__ import annotations

import functools
import json
import os
import subprocess
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn, cast

import typer
import yaml
from pydantic import BaseModel

from content_studio import __version__
from content_studio.content import (
    load_outline,
    load_public_content,
    load_speaker_script,
    regenerate_slide,
)
from content_studio.course_audit import run_course_audit, write_audit
from content_studio.course_quality import (
    CourseAcceptance,
    CourseContract,
    CourseQualityReport,
    TimingEvidence,
    contract_path,
    load_contract,
    load_quality,
    quality_is_current,
    run_course_quality_audit,
    write_acceptance,
    write_quality,
)
from content_studio.duration import build_duration_budget, write_duration_budget
from content_studio.errors import ConfigurationError, LCESError, RenderError
from content_studio.eval import build_report, load_tasks, run_tasks, write_report
from content_studio.evidence import load_claims, review_claim
from content_studio.evidence_locator import QuoteAudit, QuoteCandidate
from content_studio.expansion import ProvidedProvider, UnitExpansion, expand_unit
from content_studio.ingestion import ingest_project, load_registry
from content_studio.media import extract_frames, probe_media
from content_studio.models import (
    ContentOutline,
    CourseMaster,
    CoverageMatrix,
    EvidenceLedger,
    EvidenceRecord,
    FrameManifest,
    LearningUnit,
    PaperMap,
    ProjectConfig,
    PublicContent,
    QAReport,
    ReadingEdition,
    ReleaseManifest,
    ResearchAnalysis,
    ResearchBrief,
    SceneContract,
    SceneSet,
    SectionAnalysis,
    SourceMap,
    SourceRegistry,
    SpeakerScript,
    VideoContract,
    VisualAsset,
    VisualSpec,
)
from content_studio.motion_canvas import MotionCanvasRenderer, motion_canvas_registry, motion_status
from content_studio.motion_templates import SUPPORTED_SCENE_TYPES
from content_studio.orchestrator import load_project_config, run_pipeline
from content_studio.paths import (
    ensure_project_layout,
    repository_root,
    require_project_dir,
    safe_project_id,
    template_dir,
)
from content_studio.planning import (
    build_coverage,
    coverage_gaps,
    load_course_master,
    load_coverage_matrix,
    load_paper_map,
    paper_map_sha256,
    unknown_paper_items,
)
from content_studio.providers.base import GenerationRequest, Message, ModelProvider
from content_studio.providers.factory import LOCAL_NAMES, build_provider
from content_studio.providers.local_llama_cpp import LocalLlamaProvider
from content_studio.release import (
    approve as approve_release,
)
from content_studio.release import (
    build_release,
    load_qa_report,
    verify_release,
)
from content_studio.renderers import (
    RenderContext,
    default_registry,
    graphviz_status,
    mermaid_status,
)
from content_studio.research import load_evidence_ledger
from content_studio.review_packets import build_packets
from content_studio.settings import get_settings
from content_studio.storage import TaskStore
from content_studio.structured_review import record_review, record_substantive_review
from content_studio.supply_chain import audit_supply_chain
from content_studio.units import (
    affected_units,
    delivered_units,
    load_materialized_course,
    materialize_project_course,
    stale_units,
    write_materialized_course,
)
from content_studio.usage import apply_pricing, collect_usage, load_pricing, total_cost
from content_studio.utils import (
    read_json,
    redact_home,
    utc_now,
    write_json,
    write_json_atomic,
)
from content_studio.visual_acceptance import record_acceptance
from content_studio.visual_baseline import build_baseline

app = typer.Typer(no_args_is_help=True, help="Local Content Engineering Studio (LCES)")


def guarded[F: Callable[..., Any]](func: F) -> F:
    """Turn expected LCES failures into clean CLI errors with exit code 1."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except typer.Exit:
            raise
        except LCESError as exc:
            typer.secho(f"错误: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc
        except Exception as exc:  # unexpected: no traceback unless LCES_DEBUG is set
            typer.secho(
                f"未预期错误: {exc.__class__.__name__}: {exc}", fg=typer.colors.RED, err=True
            )
            if get_settings().log_level.upper() == "DEBUG":
                traceback.print_exc()
            raise typer.Exit(code=1) from exc

    return cast(F, wrapper)


def _project(path: Path) -> tuple[Path, ProjectConfig]:
    root = require_project_dir(path)
    return root, load_project_config(root / "project.yaml")


def _exit(message: str, code: int = 1) -> NoReturn:
    typer.secho(message, err=True)
    raise typer.Exit(code=code)


@app.command()
@guarded
def doctor() -> None:
    """Check interpreter, environment, database, and templates without calling a model."""

    settings = get_settings()
    typer.echo(f"LCES {__version__} | Python {sys.version.split()[0]}")
    typer.echo(f"解释器: {redact_home(sys.executable)}")
    typer.echo(f"配置: {redact_home(settings.describe())}")

    if sys.version_info[:2] != (3, 13):
        typer.secho("警告: 项目锁定 Python 3.13，当前解释器版本不同。", fg=typer.colors.YELLOW)
    if ".venv" not in sys.prefix.replace("\\", "/"):
        typer.secho("警告: 当前解释器不在项目 .venv 中。", fg=typer.colors.YELLOW)

    templates = template_dir()
    typer.echo(
        f"模板目录: {redact_home(str(templates))} ({'存在' if templates.is_dir() else '缺失'})"
    )

    store = TaskStore(settings.database_path)
    typer.echo(
        f"数据库: {redact_home(str(settings.database_path))} "
        f"(可用, {len(store.list_tasks(limit=1))} 条近期任务)"
    )

    provider = settings.provider.lower()
    if provider == "mock":
        typer.echo("模型: mock（离线占位，不能发布）")
    elif provider in LOCAL_NAMES:
        typer.echo(f"模型: local / {settings.local_base_url}（模型自动发现，无需 API key）")
        typer.echo("提示: 运行 `lces models` 检查本地服务是否可达。")
    else:
        key = settings.api_key_for(provider)
        typer.echo(f"模型: {provider} / {settings.model_for(provider)}")
        if not key:
            _exit(f"错误: provider={provider} 但未配置 API key")
    if settings.routing_file:
        typer.echo(f"路由文件: {redact_home(str(settings.routing_file))}")

    mermaid_ok, mermaid_detail = mermaid_status()
    typer.echo(f"Mermaid: {'可用' if mermaid_ok else '不可用'} — {mermaid_detail}")
    dot_ok, dot_detail = graphviz_status()
    typer.echo(f"Graphviz: {'可用' if dot_ok else '不可用'} — {dot_detail}")
    motion_ok, motion_detail = motion_status()
    typer.echo(f"Motion Canvas: {'可用' if motion_ok else '不可用'} — {motion_detail}")
    typer.echo("配置检查完成；未测试网络连通性。")


@app.command("supply-chain-check")
@guarded
def supply_chain_check(
    root: Path | None = typer.Option(
        None, help="仓库根目录；默认使用当前源码树", file_okay=False, dir_okay=True
    ),
) -> None:
    """Audit pinned build inputs against the files that consume the pins."""

    report = audit_supply_chain(root)
    for finding in report.findings:
        colour = typer.colors.GREEN if finding.status == "pass" else typer.colors.RED
        typer.secho(finding.line(), fg=colour)
    if not report.ok:
        _exit(f"供应链审计失败：{len(report.failures())} 项未通过")
    typer.echo("供应链审计通过：版本固定、来源记录与消费文件一致。")


@app.command("init-project")
@guarded
def init_project(
    project_id: str = typer.Option(..., help="小写字母、数字与连字符，例如 paper-course-01"),
    title: str = typer.Option(..., help="课程标题"),
    content_mode: str = typer.Option("paper_course", help="任务类型 A-F 对应的内容模式"),
    audience: str = typer.Option("具备技术背景的学习者", help="目标受众"),
    target_minutes: int = typer.Option(20, help="目标时长（分钟）"),
) -> None:
    """Create an empty project skeleton. It contains no generated content."""

    settings = get_settings()
    try:
        safe_project_id(project_id)
        config = ProjectConfig(
            project_id=project_id,
            title=title,
            content_mode=content_mode,  # type: ignore[arg-type]
            audience=audience,
            target_duration_minutes=target_minutes,
        )
    except ValueError as exc:
        raise ConfigurationError(f"invalid project parameters: {exc}") from exc

    root = ensure_project_layout(settings.projects_dir / project_id)
    project_file = root / "project.yaml"
    if project_file.exists():
        _exit(f"项目已存在: {project_file}")
    project_file.write_text(
        yaml.safe_dump(config.model_dump(mode="json"), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    typer.echo(f"已创建项目骨架: {root}")
    typer.echo(
        "下一步: 将资料放入 input/ 或写入 project.yaml 的 source_urls，然后运行 `lces run`。"
    )


@app.command()
@guarded
def ingest(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    path: list[str] | None = typer.Option(None, "--path", help="追加本地资料路径"),
    url: list[str] | None = typer.Option(None, "--url", help="追加网页地址"),
    allow_external: bool = typer.Option(False, help="允许读取项目目录之外的本地文件"),
) -> None:
    """Collect local files/URLs, hash them, and write the source registry."""

    settings = get_settings()
    root, config = _project(project_dir)
    store = TaskStore(settings.database_path)
    task_id = store.create_task(config.project_id, config.content_mode, "none", "")
    run_id = store.start_stage(task_id, "ingest", "none", "")
    try:
        registry = ingest_project(
            root,
            config,
            settings,
            extra_paths=path,
            extra_urls=url,
            allow_external=allow_external,
        )
    except Exception as exc:
        store.finish_stage(run_id, status="fail", error=f"{exc.__class__.__name__}: {exc}")
        store.update_task(task_id, status="FAILED", stage="ingest", error=str(exc))
        raise
    store.finish_stage(run_id, status="pass")
    store.update_task(task_id, status="INGESTING", stage="ingest")

    typer.echo(f"来源台账: {len(registry.sources)} 条")
    for source in registry.sources:
        typer.echo(
            f"  {source.source_id} | {source.kind} | {source.access_status} |"
            f" {source.text_chars} 字 | {source.title[:60]}"
        )
    unavailable = [s.source_id for s in registry.sources if s.access_status != "fetched"]
    if unavailable:
        typer.secho(
            "警告: 以下来源不完整或不可用，研究阶段不得假定其内容: " + ", ".join(unavailable),
            fg=typer.colors.YELLOW,
        )


@app.command()
@guarded
def research(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    provider: str | None = typer.Option(None, help="mock | deepseek | anthropic"),
) -> None:
    """Extract claims, evidence, unknowns, and write the research brief."""

    _run_single(project_dir, "research", provider)
    typer.echo("研究简报与证据台账已写入 internal/。")


@app.command()
@guarded
def outline(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    provider: str | None = typer.Option(None, help="mock | deepseek | anthropic"),
) -> None:
    """Design the course outline from the research brief."""

    _run_single(project_dir, "outline", provider)
    typer.echo("课程大纲已写入 content/outline.json。")


@app.command()
@guarded
def generate(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    provider: str | None = typer.Option(None, help="mock | deepseek | anthropic"),
    slide: list[str] = typer.Option([], "--slide", help="只重生成指定场景，可重复"),
    unit: list[str] = typer.Option([], "--unit", help="只重生成指定教学单元，可重复"),
    force: bool = typer.Option(False, "--force", help="输入未变时也重新生成"),
) -> None:
    """Generate the whole course, or regenerate named units/scenes only."""

    if slide and unit:
        _exit("--slide 与 --unit 不能同时使用")
    if unit:
        _regenerate_units(project_dir, provider, unit, force)
        return
    if slide:
        _regenerate_slides(project_dir, provider, slide)
        return
    _run_single(project_dir, "generate", provider)
    typer.echo("公开内容、口播稿与研究阅读版已生成。")


def _regenerate_slides(project_dir: Path, provider_name: str | None, slide_ids: list[str]) -> None:
    root, config = _project(project_dir)
    settings = get_settings()
    outline = load_outline(root)
    ledger = load_evidence_ledger(root)
    registry = load_registry(root)
    if outline is None:
        _exit("大纲缺失；先运行完整 generate 或 outline")
    if registry is None:
        _exit("来源登记缺失；先运行 ingest")
    provider = build_provider(settings, provider_name or settings.provider)
    for slide_id in dict.fromkeys(slide_ids):
        try:
            regenerate_slide(
                root,
                config,
                outline,
                ledger,
                registry,
                provider,
                slide_id,
                max_output_tokens=settings.max_output_tokens,
            )
        except LCESError as exc:
            _exit(f"场景 {slide_id} 重生成失败（现有内容保持不变）: {exc}")
        typer.echo(f"已重生成场景: {slide_id}（其余场景未改动）")


@app.command()
@guarded
def build(project_dir: Path = typer.Argument(..., exists=True, file_okay=False)) -> None:
    """Build public HTML from the public-only content model."""

    _run_single(project_dir, "build", None)
    typer.echo("已构建 build/slides/index.html 与 build/reading_edition.html。")


@app.command()
@guarded
def validate(project_dir: Path = typer.Argument(..., exists=True, file_okay=False)) -> None:
    """Run automated gates 1-3 and write the QA report."""

    result = _run_single(project_dir, "validate", None)
    report = result.qa or load_qa_report(project_dir)
    if report is None:
        _exit("QA 报告未生成")
    _print_qa(report)
    if report.blocking_failures:
        _exit(f"验证失败: {len(report.blocking_failures)} 项阻断问题", code=1)
    typer.echo("自动检查通过；科学审查与人工发布审批仍需单独完成。")


@app.command("audit-course")
@guarded
def audit_course(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    output: Path | None = typer.Option(None, "--output", help="审计报告输出路径"),
    scan: list[Path] = typer.Option(
        [], "--scan", help="额外审计的文件或目录（例如某个发布版本），可重复"
    ),
) -> None:
    """Audit course numbers and formulas against the reviewed evidence."""

    root, _config = _project(project_dir)
    extra: list[Path] = []
    for path in scan:
        target = path if path.is_absolute() else (root / path)
        if target.is_dir():
            extra.extend(sorted(item for item in target.rglob("*") if item.is_file()))
        elif target.is_file():
            extra.append(target)
        else:
            _exit(f"审计目标不存在: {target}")
    report = run_course_audit(root, extra_paths=extra)
    path = write_audit(root, report, path=output)
    typer.echo(f"审计报告: {path}")
    typer.echo(
        f"课程版本: {report.course_version[:16] or '-'} | 复核记录: {report.items_checked} |"
        f" blocker={report.summary.get('blocker', 0)}"
        f" major={report.summary.get('major', 0)}"
        f" advisory={report.summary.get('advisory', 0)}"
    )
    for finding in report.findings:
        color = {
            "blocker": typer.colors.RED,
            "major": typer.colors.YELLOW,
            "advisory": typer.colors.CYAN,
        }[finding.severity]
        typer.secho(
            f"[{finding.severity}] {finding.check_type} @ {finding.location}: "
            f"{finding.actual} ({finding.finding_id})",
            fg=color,
        )
    if report.decision in {"blocked", "needs_correction"}:
        _exit(f"课程内容审计未通过: {report.decision}")
    if report.decision == "not_run":
        _exit("没有可审计的课程内容文件", code=0)
    typer.echo("课程内容审计通过（只覆盖列出的检查项）。")


@app.command("audit-product")
@guarded
def audit_product(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    production: bool = typer.Option(
        False, "--production", help="只判断自动化生产质量，不把发布记录当作阻断"
    ),
) -> None:
    """Run Gate B: course product qualification against the frozen contract."""

    root, _config = _project(project_dir)
    report = run_course_quality_audit(root)
    path = write_quality(root, report)
    typer.echo(f"Gate B 报告: {path}")
    typer.echo(
        f"课程内容版本: {report.content_version[:16] or '-'} | 契约:"
        f" {report.contract_version or '-'} | blocker={report.summary.get('blocker', 0)}"
        f" human={report.summary.get('human', 0)} | decision={report.decision}"
        f" | production={report.production_decision}"
    )
    for finding in report.findings:
        color = typer.colors.RED if finding.severity == "blocker" else typer.colors.YELLOW
        typer.secho(
            f"[{finding.severity}] {finding.check_id}: {finding.message} ({finding.finding_id})",
            fg=color,
        )
    if production:
        for item in report.disclosures:
            typer.echo(f"[release-disclosure] {item}")
        if report.production_decision == "blocked":
            _exit("自动生产质量存在阻断项", code=1)
        typer.echo("自动生产质量通过；发布记录另行处理，不阻断构建、播放和录屏。")
        return
    if report.decision == "blocked":
        _exit("Gate B 课程产品验收存在阻断项", code=1)
    if report.decision == "needs_human_review":
        _exit("Gate B 自动化检查通过，但仍有未完成的人工验收项", code=2)
    if report.decision == "not_run":
        _exit("Gate B 未运行", code=0)
    typer.echo("Gate B 课程产品验收通过。")


@app.command("export-review-packets")
@guarded
def export_review_packets(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    output: Path | None = typer.Option(
        None, "--output", help="审核包输出目录（默认 internal/qa/review_packets）"
    ),
) -> None:
    """Export read-only evidence review packets for a human reviewer."""

    root, _config = _project(project_dir)
    destination = output or (root / "internal" / "qa" / "review_packets")
    entries, index = build_packets(root, destination)
    typer.echo(f"审核包: {destination}")
    typer.echo(
        f"记录: {len(entries)} | review sha256: {index.review_file_sha256[:16]}"
        f" | source sha256: {index.source_text_sha256[:16]}"
    )
    unresolved = [entry.review_id for entry in entries if entry.current_conclusion == "pending"]
    typer.echo(f"待人工结论: {len(unresolved)}/{len(entries)}")
    typer.echo("提示: 审核包只读；签署仍须由真实审核者通过 `lces review-evidence` 完成。")


@app.command("approve-course-contract")
@guarded
def approve_course_contract(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    by: str = typer.Option(..., "--by", help="产品负责人"),
    notes: str = typer.Option("", "--notes", help="批准说明"),
) -> None:
    """Record the product owner's approval of the course contract (human only)."""

    root, _config = _project(project_dir)
    contract = load_contract(root)
    if contract is None:
        _exit("缺少课程产品契约 internal/plan/course_contract.json")
    if not by.strip():
        _exit("必须提供产品负责人 --by")
    if not notes.strip():
        _exit("批准必须提供 --notes 说明决定依据")
    try:
        updated = CourseContract.model_validate(
            {
                **contract.model_dump(mode="json"),
                "status": "approved",
                "approved_by": by.strip(),
                "approved_at": utc_now(),
                "notes": (contract.notes + " | " + notes).strip(" |"),
            }
        )
    except ValueError as exc:
        _exit(f"契约缺少批准所需内容: {exc}")
    write_json_atomic(contract_path(root), updated)
    typer.echo(f"课程产品契约已批准: {contract.version} by {updated.approved_by}")


@app.command("accept-course")
@guarded
def accept_course(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    by: str = typer.Option(..., "--by", help="课程产品验收人"),
    decision: str = typer.Option("pass", "--decision", help="pass | needs_revision"),
    timing_confirmed: bool = typer.Option(False, "--timing-confirmed", help="已确认计时证据"),
    visual_confirmed: bool = typer.Option(False, "--visual-confirmed", help="已确认视觉呈现"),
    checks_confirmed: bool = typer.Option(False, "--checks-confirmed", help="已确认学习检查"),
    learner_trial_confirmed: bool = typer.Option(
        False, "--learner-trial-confirmed", help="已确认学习者试测记录"
    ),
    notes: str = typer.Option("", "--notes", help="验收说明"),
) -> None:
    """Record the human Gate B acceptance (never generated by an AI)."""

    root, _config = _project(project_dir)
    if decision not in {"pass", "needs_revision"}:
        _exit(f"未知验收结论: {decision}")
    if not by.strip():
        _exit("必须提供验收人 --by")
    contract = load_contract(root)
    if contract is None:
        _exit("缺少课程产品契约")
    if contract.status != "approved":
        _exit("课程产品契约尚未批准；先运行 `lces approve-course-contract`")
    report = load_quality(root)
    if report is None:
        _exit("缺少 Gate B 报告；先运行 `lces audit-product`")
    stale = quality_is_current(root, report)
    if stale:
        _exit("Gate B 报告已过期，课程内容在报告后变更：" + ", ".join(stale))
    if report.decision == "blocked":
        _exit("Gate B 仍有阻断项，不能记录通过验收")
    if decision == "pass" and not (
        timing_confirmed and visual_confirmed and checks_confirmed and learner_trial_confirmed
    ):
        _exit("结论为 pass 时必须同时确认计时、视觉、学习检查与学习者试测")
    acceptance = CourseAcceptance(
        project_id=contract.project_id,
        contract_version=contract.version,
        content_version=report.content_version,
        reviewer=by.strip(),
        reviewed_at=utc_now(),
        decision=decision,  # type: ignore[arg-type]
        timing_confirmed=timing_confirmed,
        visual_confirmed=visual_confirmed,
        checks_confirmed=checks_confirmed,
        learner_trial_confirmed=learner_trial_confirmed,
        notes=notes.strip(),
    )
    path = write_acceptance(root, acceptance)
    typer.echo(f"课程产品验收记录: {path} -> {acceptance.decision} by {acceptance.reviewer}")


@app.command("release-check")
@guarded
def release_check(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    version: str = typer.Option("v1", help="发布版本目录，例如 v1"),
) -> None:
    """Verify an assembled release directory against Gate 4."""

    root, _config = _project(project_dir)
    manifest, errors = verify_release(root, version)
    if manifest is None:
        _exit("; ".join(errors))
    if errors:
        for error in errors:
            typer.secho(f"FAIL: {error}", fg=typer.colors.RED)
        _exit("发布检查未通过")
    typer.echo(f"发布检查通过: {root / 'release' / version}")
    typer.echo("注意: 标记为 NOT_RUN 的检查不代表通过；科学审查仍需人工完成。")


@app.command()
@guarded
def approve(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    version: str = typer.Option("v1", help="发布版本"),
    by: str = typer.Option(..., "--by", help="审批人"),
    notes: str = typer.Option("", help="审批备注"),
) -> None:
    """Record a human approval for a specific release version."""

    root, config = _project(project_dir)
    report = load_qa_report(root)
    if report is None:
        typer.secho("警告: 尚无 QA 报告；审批记录仍会保存。", fg=typer.colors.YELLOW)
    elif report.blocking_failures:
        typer.secho(
            "警告: QA 存在阻断问题，发布仍会被拒绝，除非问题已修复并重新验证。",
            fg=typer.colors.YELLOW,
        )
    record = approve_release(
        root,
        config,
        version,
        by,
        notes=notes,
        store=TaskStore(get_settings().database_path),
    )
    typer.echo(f"已记录 {version} 的人工审批: {record.approved_by} @ {record.approved_at}")


@app.command()
@guarded
def release(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    version: str = typer.Option("v1", help="发布版本目录"),
    force: bool = typer.Option(False, help="覆盖同版本发布目录"),
) -> None:
    """Assemble the release package from whitelisted public assets and zip it."""

    root, config = _project(project_dir)
    manifest = build_release(
        root,
        config,
        version,
        store=TaskStore(get_settings().database_path),
        force=force,
    )
    archive = root / "build" / "artifacts" / f"{config.project_id}-{version}.zip"
    typer.echo(f"发布目录: {root / 'release' / version}")
    typer.echo(f"交付压缩包（仅由发布目录生成）: {archive}")
    typer.echo(f"文件数: {len(manifest.files)} | Python {manifest.python_version}")


@app.command()
@guarded
def models(
    provider: str | None = typer.Option(None, help="只检查指定 provider"),
    probe: bool = typer.Option(True, "--probe/--no-probe", help="探测本地服务与可用模型"),
    test: bool = typer.Option(False, "--test/--no-test", help="向本地模型发送一次最小生成请求"),
) -> None:
    """Show configured providers and probe the local llama-server."""

    settings = get_settings()
    target = provider.lower() if provider else None
    typer.echo(f"默认 provider: {settings.provider}")
    typer.echo(f"路由文件: {settings.routing_file or '未配置（所有阶段使用默认 provider）'}")

    if target in (None, "mock"):
        typer.echo("mock: 可用（离线占位，禁止发布）")

    if target in (None, *LOCAL_NAMES):
        info: dict[str, Any] = {
            "base_url": settings.local_base_url,
            "reachable": None,
            "health": None,
            "models": [],
            "latency_ms": 0,
            "error": "not probed",
        }
        if probe:
            local = LocalLlamaProvider(
                base_url=settings.local_base_url,
                model=settings.local_model,
                api_key=settings.local_api_key,
                timeout=settings.local_timeout_seconds,
                max_retries=settings.local_max_retries,
                json_mode=settings.local_json_mode,
                discover_model=False,
            )
            info = local.probe()
        typer.echo(f"local: {settings.local_base_url}")
        if probe:
            typer.echo(
                f"  reachable={info['reachable']} health={info['health']}"
                f" latency={info['latency_ms']}ms"
            )
            typer.echo(f"  models={info['models'] or '（未发现）'}")
            expected = info.get("expected_model") or ""
            if expected and info.get("model_match") is True:
                typer.echo(f"  模型固定: {expected}（已加载）")
            elif expected and info.get("model_match") is False:
                typer.secho(
                    f"  模型不匹配: 期望 {expected}，服务端为 {info['models']}",
                    fg=typer.colors.RED,
                )
            if info["error"] and info["error"] != "not probed":
                typer.secho(f"  错误: {info['error']}", fg=typer.colors.YELLOW)
            if not info["reachable"]:
                typer.secho(
                    "  提示: 先运行 D:\\AI\\start_server.bat 启动 llama-server，"
                    "再用 LCES_LOCAL_BASE_URL 指定实际端口。",
                    fg=typer.colors.YELLOW,
                )
            elif test:
                local = LocalLlamaProvider(
                    base_url=settings.local_base_url,
                    model=settings.local_model,
                    api_key=settings.local_api_key,
                    timeout=settings.local_timeout_seconds,
                    max_retries=1,
                    json_mode=settings.local_json_mode,
                )
                try:
                    result = local.generate(
                        GenerationRequest(
                            messages=[Message("user", "只回复 OK")],
                            max_tokens=16,
                            temperature=0,
                        )
                    )
                except LCESError as exc:
                    typer.secho(f"  生成测试失败: {exc}", fg=typer.colors.RED)
                    raise typer.Exit(code=1) from exc
                finally:
                    local.close()
                typer.echo(
                    f"  生成测试: {result.text[:80]!r} | {result.latency_ms}ms"
                    f" | usage={result.usage.as_dict()}"
                )

    for name in ("deepseek", "anthropic"):
        if target not in (None, name):
            continue
        key = settings.api_key_for(name)
        typer.echo(
            f"{name}: model={settings.model_for(name)} base={settings.base_url_for(name)}"
            f" key={'已配置' if key else '未配置'}"
        )
        if probe and key:
            typer.echo("  云端连通性未自动探测，避免产生计费调用。")


@app.command("eval")
@guarded
def evaluate(
    provider: str | None = typer.Option(None, help="local | deepseek | anthropic"),
    set_path: Path = typer.Option(
        Path("evals/basic.jsonl"), "--set", exists=True, dir_okay=False, help="固定基准集"
    ),
    out: Path = typer.Option(Path("var/evals"), "--out", help="评测报告目录"),
    limit: int | None = typer.Option(None, min=1, help="只跑前 N 项"),
) -> None:
    """Run the fixed benchmark set against one provider and record the result."""

    settings = get_settings()
    tasks = load_tasks(set_path)
    if limit:
        tasks = tasks[:limit]
    model_provider = build_provider(settings, provider)
    typer.echo(
        f"基准: {len(tasks)} 项 | provider={model_provider.name} model={model_provider.model}"
    )
    try:
        results = run_tasks(tasks, model_provider)
    finally:
        close = getattr(model_provider, "close", None)
        if callable(close):
            close()

    report = build_report(model_provider, results)
    path = write_report(report, out)
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        detail = "; ".join(result.failures) if result.failures else result.error
        typer.echo(f"{status} {result.task_id:<18} {result.latency_ms:>7}ms  {detail}"[:170])
    typer.echo(report.summary())
    typer.echo(f"报告: {path}")


@app.command()
@guarded
def usage(
    project: str | None = typer.Option(None, help="只统计某个项目"),
    pricing: Path | None = typer.Option(
        None, "--pricing", exists=True, dir_okay=False, help="价格表（见 config/pricing.yaml）"
    ),
) -> None:
    """Report token usage, failures, time, and estimated cost from stage records."""

    settings = get_settings()
    rows = collect_usage(TaskStore(settings.database_path), project)
    if not rows:
        typer.echo("暂无阶段用量记录。")
        return

    pricing_path = pricing or settings.pricing_file
    policy = load_pricing(pricing_path) if pricing_path else None
    if policy is not None:
        apply_pricing(rows, policy)

    typer.echo(
        f"{'PROVIDER':<10}{'MODEL':<28}{'CALLS':>6}{'IN':>9}{'OUT':>9}"
        f"{'FAIL':>6}{'SECONDS':>9}  COST"
    )
    for row in rows:
        cost = f"{row.cost:.4f}" if row.cost is not None else row.cost_note
        typer.echo(
            f"{row.provider:<10}{row.model:<28}{row.calls:>6}{row.input_tokens:>9}"
            f"{row.output_tokens:>9}{row.failures:>6}{row.duration_seconds:>9.1f}  {cost}"
        )
    if policy is not None:
        total, excluded = total_cost(rows)
        typer.echo(f"已计价合计: {total:.4f} {policy.currency}")
        if excluded:
            typer.echo("未纳入计价: " + ", ".join(excluded))


@app.command()
@guarded
def status(
    project: str | None = typer.Option(None, help="只显示某个项目"),
    limit: int = typer.Option(10, help="任务数量"),
    task_id: int | None = typer.Option(None, "--task", help="显示某任务的阶段记录"),
) -> None:
    """Show recent task records from the local SQLite database."""

    settings = get_settings()
    store = TaskStore(settings.database_path)
    if task_id is not None:
        task = store.get_task(task_id)
        if task is None:
            _exit(f"任务不存在: {task_id}")
        typer.echo(
            f"任务 {task['id']} | run_id={task.get('run_id', '')} | {task['project_id']} |"
            f" {task['status']} | stage={task['stage']} | {task['updated_at']}"
        )
        typer.echo(
            f"  input_sha256={task.get('input_sha256') or '-'}"
            f" config={task.get('config_json') or '{}'}"
        )
        for run in store.stage_runs(task_id):
            typer.echo(
                f"  {run['stage']:<10} {run['status']:<8} {run['provider']}/{run['model']}"
                f" retry={run.get('retry_count', 0)} class={run.get('error_class') or '-'}"
                f" artifacts={run.get('artifacts_json') or '[]'}"
                f" usage={run['usage_json']} error={run['error']}"
            )
        return

    tasks = store.list_tasks(limit=limit, project_id=project)
    if not tasks:
        typer.echo("暂无任务记录。")
        return
    for task in tasks:
        typer.echo(
            f"{task['id']:>3} | {task['project_id']:<24} | {task['status']:<16} |"
            f" {task['stage']:<10} | {task['updated_at']}"
        )


@app.command()
@guarded
def run(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    provider: str | None = typer.Option(None, help="mock | local | deepseek | anthropic"),
    from_stage: str | None = typer.Option(None, "--from-stage", help="从指定阶段重跑"),
    only_stage: str | None = typer.Option(None, "--only", help="只跑一个阶段"),
    task_id: int | None = typer.Option(None, "--task", help="复用已有任务记录"),
    routing: Path | None = typer.Option(
        None,
        "--routing",
        exists=True,
        dir_okay=False,
        help="按阶段路由的 YAML，例如 config/routing.yaml",
    ),
) -> None:
    """Run the full pipeline (or a subset) with stage tracking and retry support."""

    root, config = _project(project_dir)
    settings = get_settings()
    result = run_pipeline(
        root,
        config,
        settings,
        provider_name=provider,
        from_stage=from_stage,
        only_stage=only_stage,
        task_id=task_id,
        routing_path=routing,
    )
    typer.echo(
        f"任务 {result.task_id} | 状态 {result.status} | 完成阶段:"
        f" {', '.join(result.completed_stages) or '-'}"
    )
    if result.error:
        _exit(f"阶段 {result.failed_stage} 失败: {result.error}")
    if result.qa is not None:
        _print_qa(result.qa)
    if result.status == "NEEDS_REVISION":
        _exit("自动检查未通过，任务标记为 NEEDS_REVISION。", code=1)
    typer.echo("流水线结束；发布仍需 `lces approve` 与 `lces release`。")


@app.command("plan-coverage")
@guarded
def plan_coverage(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
) -> None:
    """Derive internal/plan/coverage_matrix.json from PaperMap + CourseMaster."""

    project = require_project_dir(project_dir)
    paper_map = load_paper_map(project)
    master = load_course_master(project)
    if paper_map is None:
        _exit("缺少 internal/plan/paper_map.json；先运行 research 或提供课程蓝图")
    if master is None:
        _exit("缺少 internal/course_master.json；先提供课程蓝图")

    unknown = unknown_paper_items(paper_map, master)
    if unknown:
        _exit("教学单元引用了不存在的论文要素：" + ", ".join(unknown))

    matrix = build_coverage(
        paper_map,
        master,
        paper_map_sha256=paper_map_sha256(project),
        previous=load_coverage_matrix(project),
    )
    path = write_json(project / "internal" / "plan" / "coverage_matrix.json", matrix)
    typer.echo(f"写入 {path}")

    gaps = coverage_gaps(paper_map, matrix)
    if gaps:
        _exit("必需要素没有教学单元：" + ", ".join(gaps))
    typer.echo(f"覆盖完整：{len(paper_map.elements)} 个论文要素")


@app.command("export-schemas")
@guarded
def export_schemas(
    output_dir: Path = typer.Option(repository_root() / "schemas", help="Schema 输出目录"),
) -> None:
    """Write JSON Schemas from the Pydantic contracts (single source of truth)."""

    mapping: dict[str, type[BaseModel]] = {
        "project": ProjectConfig,
        "source_registry": SourceRegistry,
        "evidence": EvidenceRecord,
        "evidence_ledger": EvidenceLedger,
        "quote_candidate": QuoteCandidate,
        "quote_audit": QuoteAudit,
        "research_brief": ResearchBrief,
        "research_analysis": ResearchAnalysis,
        "section_analysis": SectionAnalysis,
        "source_map": SourceMap,
        "content_outline": ContentOutline,
        "paper_map": PaperMap,
        "coverage_matrix": CoverageMatrix,
        "learning_unit": LearningUnit,
        "course_master": CourseMaster,
        "public_content": PublicContent,
        "speaker_script": SpeakerScript,
        "reading_edition": ReadingEdition,
        "qa_report": QAReport,
        "release_manifest": ReleaseManifest,
        "visual_spec": VisualSpec,
        "visual_asset": VisualAsset,
        "scene_contract": SceneContract,
        "frame_manifest": FrameManifest,
        "scene_set": SceneSet,
        "video_contract": VideoContract,
        "course_contract": CourseContract,
        "course_quality": CourseQualityReport,
        "timing_evidence": TimingEvidence,
        "course_acceptance": CourseAcceptance,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, model in mapping.items():
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            **model.model_json_schema(),
        }
        path = output_dir / f"{name}.schema.json"
        write_json(path, schema)
        typer.echo(f"写入 {path}")
    typer.echo("注意: scene_render_contract.schema.json 属于 Phase 3，不由本命令覆盖。")


@app.command("render-spec")
@guarded
def render_spec(
    spec_file: Path = typer.Argument(..., exists=True, dir_okay=False),
    output: Path = typer.Option(Path("build/visuals"), "--out", help="输出目录"),
    project_dir: Path | None = typer.Option(
        None, "--project", help="用于校验图表资源是否存在的项目目录"
    ),
) -> None:
    """Render one VisualSpec through the renderer registry."""

    try:
        spec = VisualSpec.model_validate_json(spec_file.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise ConfigurationError(f"invalid visual spec: {exc}") from exc
    registry = default_registry()
    result = registry.render(spec, RenderContext(project_dir=project_dir, output_dir=output))
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"{spec.visual_id}.html"
    path.write_text(result.html, encoding="utf-8")
    typer.echo(f"{spec.visual_id} -> {path} | {result.renderer} {result.renderer_version}")


@app.command("render-scene")
@guarded
def render_scene(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    spec_file: Path = typer.Argument(..., exists=True, dir_okay=False),
    out: Path | None = typer.Option(
        None,
        "--out",
        help=(
            "构建输出目录（默认 <project>/build；必须在项目内，"
            "且不得是 input/internal/content/release）"
        ),
    ),
    build_id: str | None = typer.Option(None, "--build-id", help="固定构建 ID"),
) -> None:
    """Render one Motion Canvas scene (P1, Linux only; not in the release path)."""

    root, _config = _project(project_dir)
    payload = read_json(spec_file)
    if not isinstance(payload, dict):
        raise ConfigurationError("scene build spec must be a JSON object")
    video = payload.get("video")
    if not isinstance(video, dict) or not isinstance(video.get("video_id"), str):
        raise ConfigurationError("scene build spec needs video.video_id")
    previous_build_id = os.environ.get("LCES_BUILD_ID")
    if build_id:
        os.environ["LCES_BUILD_ID"] = build_id
    spec = VisualSpec(
        visual_id=str(video["video_id"]),
        visual_type="animation",
        renderer=MotionCanvasRenderer.name,
        data={"scene_set": payload.get("scene_set"), "video": video},
    )
    registry = motion_canvas_registry()
    try:
        result = registry.render(
            spec, RenderContext(project_dir=root, output_dir=out or root / "build")
        )
    except RenderError as exc:
        typer.secho(f"错误[{exc.code}]: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=exc.exit_code) from exc
    finally:
        if build_id:
            if previous_build_id is None:
                os.environ.pop("LCES_BUILD_ID", None)
            else:
                os.environ["LCES_BUILD_ID"] = previous_build_id
    typer.echo(f"{spec.visual_id} -> build {result.build_id}")
    for artifact in result.artifacts:
        typer.echo(f"  产物: {artifact}")
    typer.echo("提示: 此命令是独立渲染入口；生产构建请使用内容中的 animation 块与 `lces build`。")


@app.command("visual-baseline")
@guarded
def visual_baseline(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    template: str = typer.Option(..., help="场景模板：title | flow | compare"),
    note: str = typer.Option("", help="建立或更新基线的原因"),
) -> None:
    """Record a passing build as the visual baseline for a template (P2.4-B)."""

    root = require_project_dir(project_dir)
    if template not in SUPPORTED_SCENE_TYPES:
        _exit(f"未知模板 '{template}'；可用: {sorted(SUPPORTED_SCENE_TYPES)}")
    qa_dir = root / "internal" / "qa"
    visual_path = qa_dir / "visual_qa.json"
    manifest_path = qa_dir / "frame_manifest.json"
    if not visual_path.is_file() or not manifest_path.is_file():
        _exit("缺少 internal/qa/visual_qa.json 或 frame_manifest.json；先运行 `lces build`。")
    try:
        visual = read_json(visual_path)
        manifest = read_json(manifest_path)
    except ValueError as exc:
        _exit(f"无法读取视觉证据: {exc}")
    if not isinstance(visual, dict) or not isinstance(manifest, dict):
        _exit("视觉证据格式不正确。")
    if visual.get("status") != "pass":
        _exit("visual_qa.json 不是 pass，不能作为基线。")
    hashes = {
        int(frame["index"]): str(frame["sha256"])
        for frame in manifest.get("frames", [])
        if isinstance(frame, dict) and "index" in frame
    }
    path = build_baseline(
        root,
        template=template,
        width=int(manifest["width"]),
        height=int(manifest["height"]),
        fps_num=int(manifest["fps_num"]),
        fps_den=int(manifest["fps_den"]),
        visual=visual,
        build_id=str(manifest["build_id"]),
        note=note,
        frame_sha256=hashes,
    )
    typer.echo(f"视觉基线: {path.relative_to(root).as_posix()}")


@app.command("accept-visual")
@guarded
def accept_visual(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    template: str = typer.Option(..., help="场景模板：title | flow | compare"),
    by: str = typer.Option(..., "--by", help="审阅人"),
    frame: list[int] = typer.Option([], "--frame", help="抽看的帧索引，可重复"),
    verdict: str = typer.Option("pass", help="pass | fail"),
    note: str = typer.Option("", help="结论与备注"),
) -> None:
    """Record a human visual review; machines may fail an asset, never pass it."""

    root = require_project_dir(project_dir)
    if template not in SUPPORTED_SCENE_TYPES:
        _exit(f"未知模板 '{template}'；可用: {sorted(SUPPORTED_SCENE_TYPES)}")
    if not frame:
        _exit("至少提供一个 --frame 索引（抽看的帧）")
    try:
        path = record_acceptance(
            root,
            template=template,
            reviewer=by,
            frames=frame,
            verdict=verdict,
            note=note,
        )
    except ValueError as exc:
        _exit(str(exc))
    typer.echo(f"视觉验收记录: {path.relative_to(root).as_posix()}")


@app.command("review-claims")
@guarded
def review_claims(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    claim: str = typer.Option(..., "--claim", help="主张编号，例如 claim-001"),
    status: str = typer.Option(
        ...,
        "--status",
        help="pending | supported | partially_supported | contradicted | "
        "insufficient_evidence | not_applicable",
    ),
    by: str = typer.Option(..., "--by", help="审核人"),
    note: str = typer.Option("", "--note", help="审核备注"),
) -> None:
    """Record a human verification decision for one claim."""

    root, _config = _project(project_dir)
    updated = review_claim(root, claim, status, by, note=note)
    typer.echo(
        f"{updated.claim_id} -> {updated.verification_status} |"
        f" {updated.reviewer} @ {updated.reviewed_at}"
    )
    typer.echo("提示: 重新运行 `lces validate` 让 Gate 1 反映该核验结果。")


@app.command("review-evidence")
@guarded
def review_evidence(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    review_id: str = typer.Option(..., "--review-id", help="结构化证据复核记录 ID"),
    by: str = typer.Option(..., "--by", help="复核人"),
    conclusion: str = typer.Option(
        ...,
        "--conclusion",
        help="pass | fail | needs_revision | blocked",
    ),
    basis: str = typer.Option(..., "--basis", help="复核依据"),
    missing: str = typer.Option("", "--missing", help="仍然缺少的信息"),
    conflict_ack: bool = typer.Option(
        False, "--conflict-ack", help="确认来源冲突已披露（冲突项 pass 时必需）"
    ),
    review_file: Path | None = typer.Option(
        None, "--review-file", exists=True, dir_okay=False, help="复核记录 JSON"
    ),
) -> None:
    """Record one human decision for structured evidence (research stays separate)."""

    root, _config = _project(project_dir)
    item = record_review(
        root,
        review_id,
        by,
        conclusion,
        basis,
        missing=missing,
        conflict_ack=conflict_ack,
        review_path=review_file,
    )
    typer.echo(f"{item.review_id} -> {item.conclusion} | {item.reviewer} @ {item.reviewed_at}")
    typer.echo(
        "提示: 研究核验（research_verification）与人工签署分开；"
        "此命令不改变证据定位状态，也不自动通过冲突项。"
    )


@app.command("review-evidence-ai")
@guarded
def review_evidence_ai(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    review_id: str = typer.Option(..., "--review-id", help="结构化证据复核记录 ID"),
    by: str = typer.Option(..., "--by", help="AI 复核者标识（不得写成人名冒充签署）"),
    finding: str = typer.Option(
        ..., "--finding", help="consistent | inconsistent | partial | not_assessed"
    ),
    scope: list[str] = typer.Option(
        ...,
        "--scope",
        help="source_transcription | claim_interpretation | course_usage（可重复）",
    ),
    basis: str = typer.Option(..., "--basis", help="复核依据与对照的原文位置"),
    limitations: str = typer.Option("", "--limitations", help="本次复核不覆盖的范围"),
    review_file: Path | None = typer.Option(
        None, "--review-file", exists=True, dir_okay=False, help="复核记录 JSON"
    ),
) -> None:
    """Record an AI substantive review; the human conclusion stays untouched."""

    root, _config = _project(project_dir)
    item = record_substantive_review(
        root,
        review_id,
        by,
        finding,
        list(scope),
        basis,
        limitations=limitations,
        review_path=review_file,
    )
    record = item.substantive_review
    assert record is not None  # the writer above always sets it
    typer.echo(
        f"{item.review_id} -> AI {record.finding} ({', '.join(record.scopes)}) |"
        f" {record.reviewer} @ {record.reviewed_at}"
    )
    typer.echo(f"人工结论保持不变: {item.conclusion}（AI 复核不是签署）")


@app.command("media-check")
@guarded
def media_check(
    media_file: Path = typer.Argument(..., exists=True, dir_okay=False),
    frames: int = typer.Option(4, min=1, max=20, help="抽取的关键帧数量"),
    out: Path = typer.Option(Path("var/media-frames"), "--out", help="关键帧输出目录"),
) -> None:
    """Probe a media file and sample frames for human review."""

    info = probe_media(media_file)
    typer.echo(f"{media_file.name}: {info.summary()}")
    extracted = extract_frames(media_file, out / media_file.stem, count=frames)
    for path in extracted:
        typer.echo(f"  关键帧: {path}")
    typer.echo("提示: 关键帧仅用于人工抽检；数值结果仍需单独核验。")


@app.command("mcp-serve")
@guarded
def mcp_serve(
    caller: str = typer.Option("mcp-client", help="写入工具调用日志的调用方名称"),
    allow_write: bool = typer.Option(
        False, "--allow-write", help="允许 run_validate（不包含发布/审批）"
    ),
) -> None:
    """Serve permissioned LCES tools over MCP stdio (requires the `mcp` extra)."""

    from content_studio.mcp_server import mcp_available, run_stdio

    if not mcp_available():
        raise ConfigurationError("MCP SDK 未安装；执行 `uv sync --extra mcp` 后重试")
    typer.echo(
        f"MCP stdio: caller={caller} allow_write={allow_write}",
        err=True,
    )
    run_stdio(get_settings(), caller=caller, allow_write=allow_write)


def _run_single(project_dir: Path, stage: str, provider: str | None):
    root, config = _project(project_dir)
    settings = get_settings()
    result = run_pipeline(
        root,
        config,
        settings,
        provider_name=provider,
        only_stage=stage,
    )
    if result.error:
        _exit(f"阶段 {stage} 失败: {result.error}")
    return result


def _print_qa(report: QAReport) -> None:
    typer.echo("")
    typer.echo(f"{'GATE':<22}{'CHECK':<34}{'STATUS':<10}MESSAGE")
    for check in report.checks:
        typer.echo(f"{check.gate:<22}{check.check_id:<34}{check.status:<10}{check.message}")
    statuses = report.gate_status()
    typer.echo("")
    typer.echo("Gate 汇总: " + ", ".join(f"{gate}={status}" for gate, status in statuses.items()))
    if report.not_run:
        typer.secho(
            "NOT_RUN（不代表通过）: " + ", ".join(item.check_id for item in report.not_run),
            fg=typer.colors.YELLOW,
        )


def _regenerate_units(
    project_dir: Path, provider_name: str | None, unit_ids: list[str], force: bool
) -> None:
    root, config = _project(project_dir)
    settings = get_settings()
    content = load_public_content(root)
    if content is None:
        _exit("公开内容缺失；先运行完整 generate")
    outline = load_outline(root)
    ledger = load_evidence_ledger(root)
    registry = load_registry(root)
    if outline is None or registry is None:
        _exit("大纲或来源登记缺失；先运行完整流水线")
    master = load_materialized_course(root) or materialize_project_course(root, content)
    stale = set(stale_units(root, content, master))
    provider = build_provider(settings, provider_name or settings.provider)
    delivered = {unit.unit_id: unit for unit in delivered_units(master)}
    processed: list[str] = []
    for unit_id in dict.fromkeys(unit_ids):
        unit = delivered.get(unit_id)
        if unit is None:
            _exit(f"单元 {unit_id} 不存在或没有已交付场景")
        if not force and unit_id not in stale:
            typer.echo(f"跳过 {unit_id}：输入未变化（使用 --force 可强制重生成）")
            continue
        for scene_id in unit.scene_ids:
            try:
                regenerate_slide(
                    root,
                    config,
                    outline,
                    ledger,
                    registry,
                    provider,
                    scene_id,
                    max_output_tokens=settings.max_output_tokens,
                )
            except LCESError as exc:
                _exit(f"单元 {unit_id} 的场景 {scene_id} 重生成失败（现有内容保持不变）: {exc}")
        typer.echo(f"已重生成单元: {unit_id} -> {', '.join(unit.scene_ids)}")
        processed.append(unit_id)
    refreshed = materialize_project_course(root, load_public_content(root) or content)
    # Only the units regenerated above get a new fingerprint. Re-stamping every
    # unit would mark the other stale units fresh without regenerating them.
    previous = {item.unit_id: item.input_sha256 for item in master.units}
    regenerated = set(processed)
    units = [
        item.model_copy(update={"input_sha256": previous[item.unit_id]})
        if item.unit_id in previous and item.unit_id not in regenerated
        else item
        for item in refreshed.units
    ]
    write_materialized_course(root, refreshed.model_copy(update={"units": units}))


@app.command("plan-impact")
@guarded
def plan_impact(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    claim: str | None = typer.Option(None, "--claim", help="只看引用该主张的单元"),
) -> None:
    """Report stale units, or the units/scenes that reference a claim."""

    root, _config = _project(project_dir)
    content = load_public_content(root)
    if content is None:
        _exit("公开内容缺失；先运行 generate")
    master = load_materialized_course(root) or materialize_project_course(root, content)
    if claim:
        units = affected_units(master, claim)
        scenes = [
            scene_id
            for unit in master.units
            if unit.unit_id in units
            for scene_id in unit.scene_ids
        ]
        typer.echo(f"主张 {claim}: 单元 {len(units)} 个，场景 {len(scenes)} 个")
        for unit_id in units:
            unit = next(item for item in master.units if item.unit_id == unit_id)
            typer.echo(f"  {unit_id} -> {', '.join(unit.scene_ids)}")
        return
    stale = stale_units(root, content, master)
    if not stale:
        typer.echo("没有失效单元：所有单元指纹与当前输入一致。")
        return
    typer.secho(f"失效单元: {len(stale)} 个", fg=typer.colors.YELLOW)
    for unit_id in stale:
        unit = next(item for item in master.units if item.unit_id == unit_id)
        typer.echo(f"  {unit_id} -> {', '.join(unit.scene_ids)}")


@app.command("duration-plan")
@guarded
def duration_plan(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    as_json: bool = typer.Option(False, "--json", help="输出 JSON"),
) -> None:
    """Show the per-unit duration budget, current estimates and measurements."""

    root, _config = _project(project_dir)
    content = load_public_content(root)
    if content is None:
        _exit("公开内容缺失；先运行 generate")
    master = load_materialized_course(root) or materialize_project_course(root, content)
    budget = build_duration_budget(root, master, content, load_speaker_script(root))
    path = write_duration_budget(root, budget)
    if as_json:
        typer.echo(json.dumps(budget.as_dict(), ensure_ascii=False, indent=2))
        return
    typer.echo(
        f"目标 {budget.target_minutes:.1f} 分钟"
        f"（允许 {budget.lower_seconds / 60:.1f}–{budget.upper_seconds / 60:.1f} 分钟）"
    )
    typer.echo(f"{'UNIT':<10}{'SCENE':<12}{'BUDGET':>8}{'EST':>7}{'MEAS':>8}{'GAP':>7}  TITLE")
    for unit in budget.units:
        measured = f"{unit.measured_seconds:.1f}" if unit.measured_seconds is not None else "-"
        typer.echo(
            f"{unit.unit_id:<10}{unit.scene_id:<12}{unit.budget_seconds:>8}"
            f"{unit.estimated_seconds:>7}{measured:>8}{unit.gap_seconds:>7}  {unit.title[:24]}"
        )
    total = (
        budget.total_measured_seconds
        if budget.measured_valid and budget.total_measured_seconds is not None
        else budget.total_estimated_seconds
    )
    label = (
        "实测" if budget.measured_valid and budget.total_measured_seconds is not None else "估算"
    )
    if not budget.measured_valid:
        evidence_state = "无效/缺失"
    elif budget.total_measured_seconds is None:
        evidence_state = "哈希有效但缺逐单元秒数"
    else:
        evidence_state = "有效"
    typer.echo(
        f"合计预算 {budget.total_budget_seconds / 60:.2f} 分钟 | "
        f"{label} {total / 60:.2f} 分钟 | 计时证据{evidence_state}"
    )
    typer.echo(f"预算文件: {path}")


def _unit_inputs(root: Path):
    content = load_public_content(root)
    if content is None:
        _exit("公开内容缺失；先运行 generate")
    master = load_materialized_course(root) or materialize_project_course(root, content)
    script = load_speaker_script(root)
    if script is None:
        _exit("口播稿缺失；先运行 generate")
    outline = load_outline(root)
    ledger = load_evidence_ledger(root)
    claims = load_claims(root)
    return content, master, script, outline, ledger, claims


def _expand_one(
    root, config, settings, provider_name, unit_id, force, from_file: Path | None = None
) -> bool:
    content, master, script, outline, ledger, claims = _unit_inputs(root)
    budget = build_duration_budget(root, master, content, script)
    unit_budget = next((item for item in budget.units if item.unit_id == unit_id), None)
    if unit_budget is None:
        _exit(f"单元 {unit_id} 不存在或没有已交付场景")
    unit = next(item for item in delivered_units(master) if item.unit_id == unit_id)
    slide = next(item for item in content.slides if item.slide_id == unit.scene_ids[0])
    if not force and unit_budget.estimated_seconds >= unit_budget.budget_seconds * 0.85:
        typer.echo(
            f"跳过 {unit_id}：估算 {unit_budget.estimated_seconds}s 已达到预算 "
            f"{unit_budget.budget_seconds}s 的 85%（--force 可强制扩展）"
        )
        return False
    provided = None
    provider: ModelProvider
    if from_file is not None:
        provided = UnitExpansion.model_validate_json(from_file.read_text(encoding="utf-8"))
        provider = ProvidedProvider()
    else:
        provider = build_provider(settings, provider_name or settings.provider)
    result = expand_unit(
        root,
        config,
        unit,
        slide,
        script,
        outline,
        ledger,
        claims,
        unit_budget.budget_seconds,
        provider,
        max_tokens=settings.max_output_tokens,
        expansion_override=provided,
    )
    typer.echo(
        f"已扩展 {result.unit_id} / {result.scene_id}: "
        f"{result.before_chars} → {result.after_chars} 字，"
        f"{result.before_seconds} → {result.after_seconds}s（预算 {result.budget_seconds}s）"
    )
    typer.echo(
        "  使用主张: "
        + (", ".join(result.claims_used) or "无")
        + " | 证据: "
        + (", ".join(result.evidence_used) or "无")
        + " | 视觉同步 block: "
        + (", ".join(map(str, result.visual_sync_blocks)) or "无")
    )
    return True


@app.command("expand-unit")
@guarded
def expand_unit_command(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    unit: str = typer.Option(..., "--unit", help="教学单元 ID"),
    provider: str | None = typer.Option(None, help="mock | local | deepseek | anthropic"),
    force: bool = typer.Option(False, "--force", help="达到预算也重新扩展"),
    from_file: Path | None = typer.Option(
        None, "--from-file", exists=True, dir_okay=False, help="读取已撰写的 UnitExpansion JSON"
    ),
) -> None:
    """Expand one unit's narration under its evidence and visual constraints."""

    root, config = _project(project_dir)
    _expand_one(root, config, get_settings(), provider, unit, force, from_file)


@app.command()
@guarded
def rebalance(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False),
    provider: str | None = typer.Option(None, help="mock | local | deepseek | anthropic"),
    max_rounds: int = typer.Option(2, "--max-rounds", min=1, max=5),
    max_units: int = typer.Option(4, "--max-units", min=1, max=14),
    measure: bool = typer.Option(True, "--measure/--no-measure", help="扩展后用 TTS 实测"),
) -> None:
    """Expand under-budget units, measure, and report the remaining gap."""

    root, config = _project(project_dir)
    settings = get_settings()
    for round_index in range(1, max_rounds + 1):
        content, master, script, _outline, _ledger, _claims = _unit_inputs(root)
        budget = build_duration_budget(root, master, content, script)
        gaps = [
            item
            for item in budget.units
            if item.gap_seconds > 0 and item.estimated_seconds < item.budget_seconds * 0.85
        ]
        if not gaps:
            typer.echo("没有低于预算 85% 的单元。")
            return
        expanded = 0
        for item in gaps[:max_units]:
            if _expand_one(root, config, settings, provider, item.unit_id, False):
                expanded += 1
        if expanded == 0:
            return
        if not measure:
            typer.echo("已扩展；使用 --measure 运行 TTS 实测。")
            return
        script_path = repository_root() / "scripts" / "measure-narration-timing.py"
        result = subprocess.run(
            [sys.executable, str(script_path), str(root), "--per-unit"],
            check=False,
        )
        if result.returncode != 0:
            typer.secho("TTS 测量失败；计时保持 NOT_RUN，不用估算值填充。", fg=typer.colors.YELLOW)
            return
        content, master, script, _o, _l, _c = _unit_inputs(root)
        budget = build_duration_budget(root, master, content, script)
        total = budget.total_measured_seconds
        if not budget.measured_valid or total is None:
            typer.secho("测量结果未绑定当前讲稿；计时保持无效。", fg=typer.colors.YELLOW)
            return
        typer.echo(f"第 {round_index} 轮: 实测 {total / 60:.2f} 分钟")
        if budget.lower_seconds <= total <= budget.upper_seconds:
            typer.echo("已达到契约允许的时长范围。")
            return


if __name__ == "__main__":
    app()
