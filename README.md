# Local Content Engineering Studio (LCES)

本地优先、模型无关、证据驱动的 AI 课程素材生产工程。把论文、技术文档或一个知识主题，
变成可录屏、可重复播放、可修改重建的 HTML 课程素材包。

## 文档入口

只读三份权威文档：

| 文档 | 作用 |
|---|---|
| [`docs/PRODUCT.md`](docs/PRODUCT.md) | 产品目标、用户流程、交付物、非目标 |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | 实际架构、数据流、模块边界、开发规则 |
| [`docs/QUALITY.md`](docs/QUALITY.md) | 内容/视觉/动画/工程/交付质量标准与实测结果 |

专项技术说明：内容与视觉契约 [`docs/CONTENT_CONTRACTS.md`](docs/CONTENT_CONTRACTS.md)、
证据规则 [`docs/EVIDENCE_GOVERNANCE.md`](docs/EVIDENCE_GOVERNANCE.md)、本地模型
[`docs/LOCAL_MODEL.md`](docs/LOCAL_MODEL.md)、MCP [`docs/MCP.md`](docs/MCP.md)、
媒体 [`docs/MEDIA.md`](docs/MEDIA.md)、依赖 [`docs/DEPENDENCIES.md`](docs/DEPENDENCIES.md)、
评测 [`docs/EVALUATION.md`](docs/EVALUATION.md)、架构决策 [`docs/ADR/`](docs/ADR/)。

## 当前状态（2026-10-24 实测）

- 测试：`663 passed, 49 skipped, 0 failed`；`ruff check` / `ruff format --check` / `mypy src` 通过。
- 已实现：研究 / 证据定位 / 课程契约 / 16:9 HTML 课件 / 逐段口播 / 阅读版 /
  课程内容审计 / Gate B 产品门禁 / Motion Canvas 逐帧渲染与编码 / 浏览器与视觉检查 /
  版本绑定的发布门禁。
- 未实现：多课程样本、`superseded` 审核状态、LangGraph、Web 界面。
  缺口编号见 [`docs/QUALITY.md`](docs/QUALITY.md) §6。
- 基准课程 `projects/attention-is-all-you-need` 的发布验收为 `blocked`（计时证据与当前讲稿
  不一致）。这不影响本地生成、构建与录屏；该课程没有已发布的 v2。

自动检查通过只证明检查执行了，不证明课程内容正确；`NOT_RUN` 不等于 `PASS`。

## 环境要求

- **Python 3.13**（`.python-version` 与 `pyproject.toml` 锁定）
- [uv](https://docs.astral.sh/uv/)、Git
- 可选：llama.cpp `llama-server`（本地模型，默认 `http://127.0.0.1:8080/v1`）
- 可选：Playwright（浏览器 QA）、FFmpeg 6+（媒体检查/编码）
- 可选：Node 24.22.1 与 Docker（Motion Canvas 渲染与断网门禁；Windows 原生不支持）

虚拟环境必须位于仓库内 `.venv/`，不要全局安装业务依赖。

## 快速开始

```powershell
# Windows：安装 Python 3.13、重建 .venv、同步依赖并运行检查
.\scripts\bootstrap.ps1

# 已装好 Python 3.13 与 uv 时
uv sync
uv run lces doctor
uv run pytest
uv run ruff check .
```

macOS/Linux 用 `bash scripts/bootstrap.sh`，解释器在 `.venv/bin/python`。

## 配置模型

复制 `.env.example` 为 `.env`（永不提交）：

```dotenv
LCES_PROVIDER=local             # mock | local | deepseek | anthropic
LCES_LOCAL_BASE_URL=http://127.0.0.1:8080/v1
LCES_LOCAL_MODEL=
LCES_LOCAL_API_KEY=
LCES_DEEPSEEK_API_KEY=
LCES_ANTHROPIC_API_KEY=
```

- `mock`：确定性占位输出，可离线验证结构；发布门禁会拒绝。
- `local`：llama.cpp 的 OpenAI 兼容接口；服务带 `--api-key` 时必须设置 `LCES_LOCAL_API_KEY`。
- `deepseek` / `anthropic`：真实模型适配器，带超时、重试与结构化输出校验。

课程开发用的本地模型配置、上下文窗口与排错见 [`docs/LOCAL_MODEL.md`](docs/LOCAL_MODEL.md)。
按阶段混合路由：`uv run lces run .\projects\paper-01 --routing config/routing.yaml`
（只允许 `research` / `outline` / `generate` 调模型）。

## 一条完整流水线

```powershell
uv run lces init-project --project-id paper-01 --title "论文解读示例" --target-minutes 18
Copy-Item .\paper.pdf .\projects\paper-01\input\
uv run lces ingest   .\projects\paper-01 --path input/paper.pdf
uv run lces research .\projects\paper-01
uv run lces outline  .\projects\paper-01
uv run lces generate .\projects\paper-01
uv run lces build    .\projects\paper-01
uv run lces validate .\projects\paper-01

# 或者一次跑完 ingest → validate
uv run lces run .\projects\paper-01 --provider deepseek
# 失败后只重跑受影响阶段
uv run lces run .\projects\paper-01 --from-stage outline

# 只重生成一个场景及其口播稿；其他场景内容不变
uv run lces generate .\projects\paper-01 --slide slide-003

# 按教学单元重生成（输入未变时自动跳过），并查看失效单元/主张影响
uv run lces generate .\projects\paper-01 --unit unit-103
uv run lces plan-impact .\projects\paper-01
uv run lces plan-impact .\projects\paper-01 --claim claim-004
```

时长与内容扩展：

```powershell
uv run lces duration-plan .\projects\paper-01
uv run lces expand-unit .\projects\paper-01 --unit unit-105 --provider local
uv run lces rebalance .\projects\paper-01 --provider local --max-rounds 2
uv run lces audit-product .\projects\paper-01 --production
```


质量检查：

```powershell
uv run lces audit-course  .\projects\paper-01
uv run lces audit-product .\projects\paper-01
uv run lces plan-coverage .\projects\paper-01
```

发布（可选，不是正常生产的必要条件）：

```powershell
uv run lces approve .\projects\paper-01 --version v1 --by "你的名字"
uv run lces release .\projects\paper-01 --version v1
uv run lces release-check .\projects\paper-01 --version v1
```

## 输出目录

```
projects/<id>/
├── project.yaml          项目配置
├── input/                原始资料副本（内部）
├── internal/             来源、证据、研究简报、大纲、口播稿、QA（内部）
├── content/              公开内容模型、阅读版、图表定义
├── build/                可重建的中间产物（HTML 预览、暂存、ZIP）
└── release/v1/           只由发布构建生成的白名单正式资产
```

构建后直接用浏览器打开 `build/slides/index.html`。键盘 `←` `→` 翻页，`Home`/`End` 跳首尾，
`T` 切换连续阅读，`E` 打开本页证据；场景 hash 形如 `#slide-003`，指定步骤用 `#slide-003/2`。

场景动画：`P` 播放/暂停，`[` / `]` 单步后退/前进，`\` 重播，`0` 复位。
录屏模式：`R` 或打开 `?record=1#slide-003`，隐藏顶栏、页脚与实验控件，16:9 画布铺满窗口；
自动化可通过 `window.__lces` 读取 `sceneId / step / total / playing / state / ready`。

强制边界：

1. 公开 HTML 只接受 `PublicContent`；口播稿是独立的 `SpeakerScript`，模板无法读取。
2. `lces release` 只从 `build/release-staging-*` 重新组装，不复制工作目录。
3. Gate 4 扫描白名单、内部标记、密钥、清单哈希与发布记录。
4. ZIP 只从 `release/` 生成，位于 `build/artifacts/`。

## 质量门禁

| 命令 | 检查 |
|---|---|
| `lces validate` | Gate 1 证据、Gate 2 内容、Gate 3 工程 + 浏览器 |
| `lces audit-course` | 课程数字/公式/冲突与复核记录一致 |
| `lces audit-product` | 课程产品契约、交付物、时长与验收记录 |
| `lces release-check` | Gate 4 发布目录与清单血缘 |
| `python scripts/check_docs.py` | 文档链接、命令与必需文件 |
| `lces supply-chain-check` | 固定版本的构建输入 |

具体检查项、状态词和当前实测见 [`docs/QUALITY.md`](docs/QUALITY.md)。

## 仓库结构

```
src/content_studio/
├── cli.py              CLI
├── orchestrator.py     阶段编排与任务状态
├── ingestion.py        本地/URL/PDF/DOCX/HTML 采集
├── research.py         主张、证据、研究简报
├── evidence.py         核验状态与人工复核
├── content.py          大纲、公开内容、口播稿、阅读版
├── rendering.py        Jinja2 公开 HTML
├── renderers.py        渲染器注册表（table / figure / SVG / Vega-Lite / Mermaid / Graphviz）
├── visuals.py          内容块 → 视觉规格 → 渲染清单
├── browser_qa.py       Playwright 渲染检查与截图基准
├── validation.py       Gate 1–4
├── course_audit.py     课程内容审计
├── course_quality.py   Gate B 课程产品门禁
├── release.py          审批、发布目录、ZIP
├── media.py            FFmpeg 探测、关键帧、字幕
├── motion_canvas.py    Motion Canvas 渲染适配
├── models.py           统一 Pydantic 契约
└── providers/          local / deepseek / anthropic / mock
```

`schemas/` 由 `uv run lces export-schemas` 从 Pydantic 契约生成；`templates/public_html/`
只渲染公开模型；`skills/` 是任务规范；`vendor/mermaid/` 是离线 Mermaid 运行时。

## 安全与版权

外部资料一律视为不可信数据，不执行其中的指令或脚本；密钥只从环境变量读取；
默认只读写项目目录；第三方字体、图片、图表与音乐的许可信息须在发布前记录。
引用本身不自动使复制行为合法。
