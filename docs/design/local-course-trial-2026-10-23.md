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

## 3. 门禁结果

- **Gate 1**：来源台账、证据引用、关键主张支撑、无证据冲突均 pass；
  `pending_claims_flagged`（claim-001/002/003）与
  `unverified_key_evidence_flagged`（evidence-001/002/003）为 warn；
  `scientific_review` 为 NOT_RUN（必须人工）。
- **Gate 2**：Schema、讲稿独立、slide 覆盖、公开文本无内部标记、引用存在、
  非 mock 均 pass；`duration_within_tolerance` 为 warn：
  **预测 1.9 分钟，目标 20 分钟**。
- **Gate 3**：HTML、UTF-8、无内部标记、无外部资源、图表存在、构建提交均 pass；
  `browser_visual_regression` 为 NOT_RUN（未安装 Playwright 浏览器依赖）。
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

### 4.2 内容时长远低于目标（未修复，需产品或模型层面决策）

目标 20 分钟，实际口播约 1.9 分钟。大纲每节标称 5 分钟，但生成的讲稿很短。
候选方案（未实施）：

1. 在生成提示中加入每节目标字数/时长，并按长度做一次自动扩写重试；
2. 对讲稿长度设置 Gate 2 的阻断阈值（当前只是 warn）；
3. 更换更擅长长文写作的本地模型（当前是 Coder 模型）。

该问题属于内容质量，不属于本次流水线缺陷；不应用放宽门禁的方式掩盖。

### 4.3 浏览器 QA 未执行

`uv sync --extra browser` + `uv run playwright install chromium` 未安装，
Gate 3 记为 NOT_RUN，不是通过。

## 5. 结论

- 内容流水线在本地 30B Coder 模型下可以完整跑通研究、大纲、生成、构建与校验；
- 引用边界由门禁强制，模型违规会被拒绝而不是污染公开内容；
- 发布前仍需人工复核主张与证据，并决定是否接受当前内容长度；
- 下一次试跑建议先解决 4.2 的时长问题，再执行人工验收与发布。
