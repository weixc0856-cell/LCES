# Local Content Engineering Studio (LCES)

本地优先、模型无关、证据驱动的 AI 课程与内容生产工程。

本仓库当前对应 PRD V2.0 的 **Phase 0 工程基线 + Phase 1 最小端到端课程流水线**。它已经能把本地资料或网页处理成来源台账、证据台账、研究简报、课程大纲、公开内容、独立口播稿、研究阅读版、公开 HTML、QA 报告和发布包；它**尚未**实现浏览器逐帧渲染、视频、字幕、Playwright 视觉回归和 Web 界面。

> 工程状态以 `docs/IMPLEMENTATION_STATUS.md` 为准。自动化测试通过并不代表科学结论正确；`NOT_RUN` 不等于 `PASS`。

## 环境要求

- **Python 3.13**（由 `.python-version` 与 `pyproject.toml` 锁定）
- [uv](https://docs.astral.sh/uv/)
- Git
- 可选：llama.cpp `llama-server`（本地模型，默认 `http://127.0.0.1:8080/v1`）
- 可选：FFmpeg、Playwright（Phase 3 媒体阶段再安装）

虚拟环境必须位于项目目录内：`.venv/`。不要用系统 Python 安装业务依赖。

## 快速开始（Windows）

```powershell
# 1. 在项目根目录执行；脚本会安装 Python 3.13、重建 .venv、同步依赖、初始化 Git 并运行检查
.\scripts\bootstrap.ps1
```

如果已经装好 Python 3.13 与 uv，也可以手动执行：

```powershell
py -3.13 --version
uv sync                             # 创建/更新 .venv，并安装 dev 依赖组
uv run lces doctor
uv run pytest
uv run ruff check .
```

VS Code：`Python: Select Interpreter` → `.\.venv\Scripts\python.exe`。

macOS/Linux 使用 `bash scripts/bootstrap.sh`，解释器路径为 `.venv/bin/python`。

## 配置模型

复制 `.env.example` 为 `.env`（`.env` 永不提交）：

```dotenv
LCES_PROVIDER=local             # mock | local | deepseek | anthropic
LCES_LOCAL_BASE_URL=http://127.0.0.1:8080/v1
LCES_LOCAL_MODEL=
LCES_DEEPSEEK_API_KEY=
LCES_ANTHROPIC_API_KEY=
```

- `mock`：确定性占位输出，可离线跑通结构，但**发布门禁会拒绝**。
- `local`：llama.cpp `llama-server` 的 OpenAI 兼容接口，无需 API key；模型 ID 从 `/v1/models` 自动发现。
- `deepseek`：OpenAI 兼容接口，`httpx` 实现，带超时/重试/结构化输出校验。密钥可用 `LCES_DEEPSEEK_API_KEY` 或 `DEEPSEEK_API_KEY`。
- `anthropic`：Messages API，`httpx` 实现。密钥可用 `LCES_ANTHROPIC_API_KEY` 或 `ANTHROPIC_API_KEY`。

模型名称、端点和限额以各家官方文档为准；切换供应商不需要改内容 Schema、模板或发布流程。

## 本地模型（llama.cpp / Intel Arc）

1. 运行 `D:\AI\start_server.bat` 启动 `llama-server`（加载 `D:\AI\models\Qwen3.5-4B_Q4_k_m.gguf`）。
2. 检查服务与模型：`uv run lces models`（会请求 `/health` 与 `/v1/models`，不产生生成调用）；加 `--test` 会发送一次最小生成请求，验证结构化输出链路。
3. 在 `.env` 设置 `LCES_PROVIDER=local`，或直接 `uv run lces run <project> --provider local`。
4. 如果服务端口不是 8080，修改 `LCES_LOCAL_BASE_URL`。
5. 若该 llama-server 版本不支持 `response_format`，设置 `LCES_LOCAL_JSON_MODE=false`；结构化输出仍会由提示词 + Pydantic 校验兜底。
6. 本地上下文较小：`LCES_LOCAL_PROMPT_CHAR_BUDGET`（默认 24000 字符）限制研究阶段的资料长度。上下文不足时应减少资料或改用云端模型，而不是强行塞满。

### 按阶段路由（本地 + 云端混合）

```powershell
uv run lces run .\projects\paper-01 --routing config/routing.yaml
```

`config/routing.yaml` 只允许配置 `research`、`outline`、`generate` 三个调用模型的阶段；`ingest/build/validate` 永远不调用模型。示例配置让研究走 DeepSeek，起草与讲稿走本地模型。CLI 的 `--provider` 优先级高于路由文件。每次运行的阶段、provider、model 与 token 用量都写入 SQLite，可用 `lces status --task <id>` 查看。

## 一条完整流水线

```powershell
# 1. 创建空项目（不会生成伪造内容）
uv run lces init-project --project-id paper-01 --title "论文解读示例" --target-minutes 18

# 2. 把论文/网页放入项目，或写入 project.yaml 的 input_paths / source_urls
Copy-Item .\paper.pdf .\projects\paper-01\input\

# 3. 采集并记录哈希
uv run lces ingest .\projects\paper-01 --path input/paper.pdf

# 4. 全流程：研究 → 大纲 → 公开内容/口播稿/阅读版 → HTML → QA
uv run lces run .\projects\paper-01 --provider deepseek

# 5. 人工审核后记录审批并发布
uv run lces approve .\projects\paper-01 --version v1 --by "你的名字"
uv run lces release .\projects\paper-01 --version v1
uv run lces release-check .\projects\paper-01 --version v1
```

分阶段执行：`ingest`、`research`、`outline`、`generate`、`build`、`validate`；失败后可用 `lces run --from-stage outline` 只重跑受影响阶段。任务状态、阶段耗时、token 用量与审批记录写入 SQLite（默认 `var/lces.sqlite3`）。

## 数据边界（PRD 2.1）

```
projects/<id>/
├── project.yaml          项目配置
├── input/                原始资料副本（内部）
├── internal/             来源、证据、研究简报、大纲、口播稿、QA（内部，禁止发布）
├── content/              公开内容模型、阅读版、图表与场景定义（默认不公开）
├── build/                可重建的中间产物（HTML 预览、发布暂存、ZIP）
└── release/v1/           只由发布构建生成的白名单正式资产
```

强制规则：

1. 公开 HTML 只接受 `PublicContent` 模型；口播稿是独立的 `SpeakerScript` 模型，模板无法读取。
2. `lces release` 不复制工作目录，只从 `build/release-staging-*` 重新组装。
3. Gate 4 扫描白名单、内部标记、密钥模式、清单哈希与人工审批；任一项失败即拒绝发布。
4. ZIP 只从 `release/` 目录生成，位于 `build/artifacts/`。

## 远程仓库

```powershell
git remote -v        # origin -> git@github.com:weixc0856-cell/LCES.git
git push -u origin main
```

推送需要本机已配置 GitHub SSH key。当前两个提交（`0e367ba`、`56c2cfb`）已在本地 `main` 分支；若远端仓库尚未创建，请先在 GitHub 建空仓库再推送。

## 联调里程碑（Windows）

一次生成可分享的诊断报告（自动脱敏 API key）：

```powershell
.\scripts\milestone-check.ps1
```

脚本依次检查：Git 状态、Python 3.13 与 `.venv`、`lces doctor`、pytest、ruff、mypy、本地服务探测、`lces models --test`。报告写入 `var/milestone-report.txt`（已被 `.gitignore` 排除）。任一项失败时退出码为 1。

## 质量门禁

`lces validate` 只对真正实现的检查给出 PASS。当前包含：

- Gate 1：来源台账、证据引用可解析、关键主张有支持证据、核验状态可解析；被证据否定的关键主张直接阻断，未核验项告警；科学审查为 `NOT_RUN`。详见 `docs/EVIDENCE_GOVERNANCE.md`。
- Gate 2：公开模型校验、讲稿独立与章节映射、公开文本无内部标记、引用存在、mock 内容禁止发布、时长偏差告警。
- Gate 3：HTML 构建、UTF-8、内部标记、图表文件存在、外部资源告警；安装浏览器依赖后还会用 Chromium 实际渲染，检查页面加载、JavaScript 错误、资源加载、桌面/16:9/2K/4K/移动视口横向溢出，并保存基准截图（见下节）。
- Gate 4：白名单、内部标记、密钥模式、清单哈希、人工审批；发布物含媒体时用 FFmpeg 检查解码、音频流与字幕时间轴，否则该项为 `NOT_RUN`。

### 证据核验（Phase 4）

模型不能给自己核验。研究阶段会把模型返回的核验状态重置为 `pending` / `unverified` 并清空审核人；没有署名审核人的 `supported` 也会按 `pending` 处理。人工复核后用：

```powershell
uv run lces review-claims .\projects\<project> --claim claim-001 `
    --status supported --by "你的名字" --note "对照原文 Abstract"
uv run lces validate .\projects\<project>
```

`contradicted` 会直接阻断发布；`pending` / `partially_supported` / `insufficient_evidence` 只告警。状态词表与门禁清单见 `docs/EVIDENCE_GOVERNANCE.md`。

### 媒体检查（Phase 5）

发布目录含 `media/course.mp4`、`course.srt` 或 `course.vtt` 时，Gate 4 用 FFmpeg 实际解码并检查时长、分辨率、音频流与字幕时间轴；没有媒体则记 `NOT_RUN`，FFmpeg 未安装同样记 `NOT_RUN` 并说明缺哪个工具。手工抽检：

```powershell
uv run lces media-check .\build\media\course.mp4 --frames 4
```

关键帧写入 `var/media-frames/`，仅供人工查看——能解码不代表内容正确。LCES 目前不做视频**生成**（Manim/Remotion/ParaView 未接入），边界与追溯要求见 `docs/MEDIA.md`。

### 浏览器 QA（Phase 1）

```powershell
uv sync --extra browser
uv run playwright install chromium
uv run lces validate .\projects\<project>
```

渲染检查默认启用；`LCES_BROWSER_QA=false` 可显式跳过（跳过记为 `NOT_RUN`，不代表通过）。未安装 Playwright 时同样记为 `NOT_RUN`。截图写入 `internal/qa/screenshots/`，基准图写入 `internal/qa/baselines/`；两者随项目目录一起被 git 忽略。基准图与当前截图不一致时记 `warn`，需人工确认后才能发布。

### 图表渲染（Phase 3）

统计图表用 Vega-Lite 规格描述，由 `vl-convert` 离线渲染为静态 SVG（不需要 Node.js）：

```powershell
uv sync --extra charts
uv run lces render-spec .\spec.json --out .\build\visuals
```

- 视觉类型与渲染器：`table → html.table`、`figure_image → html.figure`、`custom_svg → svg.custom`、`data_chart → vega_lite.chart`
- 自定义 SVG 必须是合法 XML，且拒绝 `<script>`、事件处理器、`<foreignObject>` 与外部链接
- 内联 SVG 带 `role="img"`、`aria-label` 和 `max-width:100%`，窄视口不会撑破布局
- 未安装 `vl-convert` 时 `data_chart` 明确报错，不会静默输出空图

## 仓库结构

```
src/content_studio/
├── cli.py              CLI
├── orchestrator.py     阶段编排与任务状态
├── ingestion.py        本地/URL/PDF/DOCX/HTML 采集
├── research.py         主张、证据、研究简报
├── evidence.py         核验状态与人工主张复核
├── media.py            FFmpeg 探测、关键帧抽取、字幕时间轴检查
├── content.py          大纲、公开内容、口播稿、阅读版
├── rendering.py        Jinja2 公开 HTML（经渲染器注册表输出视觉块）
├── renderers.py        渲染器接口与注册表（table / figure / custom SVG / Vega-Lite）
├── visuals.py          内容块 → 视觉规格 → 渲染清单
├── browser_qa.py       Playwright 渲染检查与截图基准
├── validation.py       Gate 1-4 自动检查
├── release.py          审批、发布目录、ZIP
├── providers/          DeepSeek / Anthropic / Mock 适配器
├── storage.py          SQLite 任务、阶段、资产、审批
├── models.py           统一 Pydantic 契约
└── settings.py         环境配置
```

`skills/` 保存五大 Skill 规范；`schemas/` 由 `lces export-schemas` 从 Pydantic 契约生成（含 `visual_spec.schema.json`）；`templates/public_html/` 只渲染公开模型。内容与视觉规格的边界、渲染器规则与版本策略见 `docs/CONTENT_CONTRACTS.md`。

## 尚未实现

真实网页抓取的登录/反爬处理、OCR、自动证据核验、多模型路由、缓存与增量构建、研究阅读版之外的系列课程、像素级视觉 diff（当前为截图基准比对）、SVG/Canvas 场景引擎、视频与动画生成（当前仅做解码与字幕检查）、本地 Web 界面。详见 `docs/IMPLEMENTATION_STATUS.md`。

## 安全与版权

外部资料一律视为不可信数据，不执行其中指令或脚本；密钥只从环境变量读取；默认只读写项目目录；第三方向量、字体、图片与音乐的许可信息须在发布前记录。引用本身不自动使复制行为合法。
