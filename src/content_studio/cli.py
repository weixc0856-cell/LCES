"""Command-line interface for Local Content Engineering Studio."""

from __future__ import annotations

import functools
import os
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any, NoReturn, cast

import typer
import yaml
from pydantic import BaseModel

from content_studio import __version__
from content_studio.errors import ConfigurationError, LCESError, RenderError
from content_studio.eval import build_report, load_tasks, run_tasks, write_report
from content_studio.evidence import review_claim
from content_studio.ingestion import ingest_project
from content_studio.media import extract_frames, probe_media
from content_studio.models import (
    ContentOutline,
    EvidenceLedger,
    EvidenceRecord,
    FrameManifest,
    ProjectConfig,
    PublicContent,
    QAReport,
    ReadingEdition,
    ReleaseManifest,
    ResearchAnalysis,
    ResearchBrief,
    SceneContract,
    SceneSet,
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
from content_studio.providers.base import GenerationRequest, Message
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
from content_studio.settings import get_settings
from content_studio.storage import TaskStore
from content_studio.supply_chain import audit_supply_chain
from content_studio.usage import apply_pricing, collect_usage, load_pricing, total_cost
from content_studio.utils import read_json, redact_home, write_json
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
) -> None:
    """Generate public content, the internal speaker script, and the reading edition."""

    _run_single(project_dir, "generate", provider)
    typer.echo("公开内容、口播稿与研究阅读版已生成。")


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
            f"任务 {task['id']} | {task['project_id']} | {task['status']} |"
            f" stage={task['stage']} | {task['updated_at']}"
        )
        for run in store.stage_runs(task_id):
            typer.echo(
                f"  {run['stage']:<10} {run['status']:<8} {run['provider']}/{run['model']}"
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
        "research_brief": ResearchBrief,
        "research_analysis": ResearchAnalysis,
        "content_outline": ContentOutline,
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


if __name__ == "__main__":
    app()
