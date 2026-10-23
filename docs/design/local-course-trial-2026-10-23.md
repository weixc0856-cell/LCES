# 本地课程试跑记录（2026-10-23）

目的：用课程开发用的本地模型跑一遍真实项目，验证内容流水线在真实模型下
是否可用，并记录暴露的问题。对象是 `projects/attention-is-all-you-need`
（源文档：`input/source-001-attention-is-all-you-need.html`，43,615 字符）。

## 1. 运行环境

| 项目 | 值 |
|---|---|
| 模型 | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M`（llama.cpp，SYCL，CPU-MoE 48 层） |
| 上下文 | 32768 tokens，`--parallel 1` |
| LCES provider | `local`，`.env` 固定模型别名 |
| 预算 | `LCES_LOCAL_PROMPT_CHAR_BUDGET=20000` |
| 平台 | Windows 11；Motion Canvas 不在本试跑范围内（Linux-only） |

模型由 LCES 侧按 `start_server.bat` 的等价参数启动，未依赖交互菜单；
`lces models` 显示 `模型固定: …（已加载）`，`--test` 最小生成通过。

## 2. 阶段结果

| 阶段 | 结果 | 耗时（本地时间） |
|---|---|---|
| research | 通过：6 条主张、6 条证据（定位 Abstract） | 18:04–18:08（约 4 分钟） |
| outline | 通过：3 个章节，含学习目标、要点、证据引用 | 18:08–18:10（约 2 分钟） |
| generate（第一次） | **失败**：`public content cites unknown source ids: evidence-001…006` | 18:10–18:12 |
| generate（修复后） | 通过：3 个 slide、讲稿、阅读版 | 18:13–18:16（约 3.5 分钟） |
| build | 通过：`build/slides/index.html`、`reading_edition.html` | < 1 分钟 |
| validate | Gate 1 warn、Gate 2 warn、Gate 3 partial；详见下节 | < 1 分钟 |

本地模型用量（`lces usage`，来自 `stage_runs` 实记录）：
4 次调用，输入 9,541 tokens，输出 3,119 tokens，1 次失败，合计 633 秒。
未配置价格，成本记为未核算。

调用口径：成功 3 次、失败 1 次（失败原因是公开内容引用校验，不是 provider
错误）；失败后修改提示词重跑恢复，未做自动重试。633 秒是模型调用耗时之和，
阶段耗时还包含资料拼装、校验与落盘，两者不能直接相减；本次没有并行调用，
因此也不存在耗时的并发重叠。失败的一次调用同样消耗了输入 tokens。

## 3. 门禁结果

- **Gate 1**：来源台账、证据引用、关键主张支撑、无证据冲突均 pass；
  `pending_claims_flagged`（claim-001/002/003）与
  `unverified_key_evidence_flagged`（evidence-001/002/003）为 warn；
  `scientific_review` 为 NOT_RUN（必须人工）。
- **Gate 2**：Schema、讲稿独立、slide 覆盖、公开文本无内部标记、引用存在、
  非 mock 均 pass；`duration_within_tolerance` 为 warn：
  **预测 1.9 分钟，目标 20 分钟**。
- **Gate 3**：HTML、UTF-8、无内部标记、无外部资源、图表存在、构建提交均 pass；
  安装 Playwright 1.64.0 + Chromium 后，浏览器检查实际执行：10 个页面/视口
  全部加载成功、无 JavaScript 错误、资源全部加载、无横向溢出；
  `browser_visual_regression` 为 warn（截图与上一版内容的基准不同，需人工确认）。
- **Gate 4 / 发布**：未执行人工审批；`release/v1` 已存在，需要 `--force`
  或新版本号。发布仍需要人工复核 6 条主张与证据。

## 4. 发现与处理

### 4.1 公开页误用内部证据编号（已修复）

第一次 generate 失败：模型把 `evidence-001…006` 写进了公开 slide 的
`source_ids`。门禁按契约拒绝，未写入公开内容。修复：

- `PUBLIC_SYSTEM` 明确 `source_ids` 只能是 `source-xxx`，禁止内部编号；
- 用户提示把证据台账标为“仅供理解”，并列出可选 source_id；
- 阅读版规则同步；
- 新增测试：提示词必须包含该约束；`evidence-xxx` 仍会被门禁拒绝。

修复后重跑成功，三个 slide 的 `source_ids` 均为 `source-001`。

### 4.2 内容时长远低于目标（保留 warn，不自动扩写）

目标 20 分钟，实际口播约 1.9 分钟。大纲每节标称 5 分钟，但生成的讲稿很短。
判断：这是当前硬件与模型的能力边界，优先保证输出质量，不通过自动扩写或放宽
门禁制造“时长达标”的假象。Gate 2 继续保持 warn，若要接近目标时长，应由课程
设计补充推导、示例与讲解，或改用更擅长长文的模型；两者都需要单独评估。

### 4.3 浏览器 QA（已执行）

安装 `uv sync --extra browser` 与 `uv run playwright install chromium` 后重跑：

- 10 个页面/视口（slides 与阅读版 × desktop / 16:9 HD / QHD / UHD / mobile）
  全部加载成功，无 JavaScript 错误，图片与资源全部加载，无横向溢出；
- `browser_visual_regression` 为 warn：截图与上一版内容的基准不同。这是内容
  变化导致的预期差异，需要人工确认后更新基准，不能当作通过；
- 截图位于 `internal/qa/screenshots/`，基准位于 `internal/qa/baselines/`。

### 4.4 引文真实性（本批新增自动检查）

试跑后逐条核对：6 条证据摘录都能在源文档文本中逐字找到，定位分别为
Abstract（4 条）、3.2.2（多头注意力）、3.5（位置编码）。为把这项人工核对
固化为门禁，Gate 1 新增 `evidence_quotes_in_source`：把摘录与来源文本做
空白/大小写/Unicode 标点归一化后比较。本次试跑该检查为 pass。

收口时按“不能静默放行”补强：

- 找不到的摘录 → warn 并列出 evidence id；
- 缺少摘录、来源文本不可用、摘录短于 12 个归一化字符 → 明确记为
  “无法核对”并列出 evidence id，不再跳过；
- 测试覆盖：逐字匹配、空白/大小写、Unicode 引号、相似但不同的文本（必须失败）；
- 公开 `source_ids` 增加结构校验（`^source-[a-z0-9-]+$` + 台账成员校验），
  提示词负责引导，程序负责守边界。

## 5. 结论

- 内容流水线在本地 30B Coder 模型下可以完整跑通研究、大纲、生成、构建与校验；
- 引用边界由提示词 + 结构校验双重强制，模型违规会被拒绝而不是污染公开内容；
- 引文存在性已自动核对（6/6 通过），但“证据是否支持主张”仍需人工科学审查；
- 浏览器 QA 已实际执行：加载、JS、资源、溢出全部通过，视觉基准差异待人工确认；
- 发布暂不批准：需人工复核 6 条主张与证据、确认视觉基准，并按新版本号审批。

状态定义：

| 项目 | 状态 |
|---|---|
| 端到端试跑 | 完成 |
| 引文文本存在性 | 试跑样例通过与门禁测试；CI 覆盖 |
| 科学内容审查 | 待人工（`lces review-claims`） |
| 浏览器视觉验收 | 自动检查通过；基准差异待人工确认 |
| 正式发布 | 暂不批准 |

下一步不增加功能，也不立即重跑模型：先完成人工审阅、视觉基准确认与版本审批，
再判断该流程能否稳定复用于下一篇论文。
