# LECS P5 — 课程产品资格验收（2026-10-24）

对象：`projects/attention-is-all-you-need`  
任务：`LECS — Course Product Qualification`  
**最终结论：NO-GO。Gate B 自动化检查通过，但契约未批准、课程产品验收未签署；Gate A 8/8 待人工；
Gate C 发布审批未开始。`release/v1` 保持历史版本，不覆盖、不撤回。**

> 本报告按 P5 任务单的十节格式记录。自动化审计通过只证明规则集覆盖的检查项；
> 讲解是否清晰、学习者是否理解，仍由人工试听、学习检查与课程产品验收决定。
> 本轮没有签署任何证据记录，没有 `approve`，没有 `release`。

## 一、本轮完成的产品与工程变更

| 变更 | 结果 |
|---|---|
| 课程产品契约 | `internal/plan/course_contract.json`：20 分钟目标、8 个学习目标、8 个模块、交付物、计时规则、Gate B 人工项；状态 `draft`，等待产品负责人批准 |
| 学习检查块 | 新增 `CheckBlock`（问题/答案/依据），课程模板渲染为可展开的“学习检查”；schema 已导出 |
| Gate B 实现 | `course_quality.py` + `lces audit-product`：契约、目标不降标、目标覆盖、模块、公式/检查/阅读/口播交付物、计时证据、视觉 QA、人工验收、内容哈希绑定 |
| Gate B 人工入口 | `lces approve-course-contract` 与 `lces accept-course`；只接受真实 `--by`，AI 没有被调用 |
| 课程内容重构 | 从 5 节扩展到 8 节，覆盖问题、架构、缩放点积注意力、多头、位置编码、复杂度、实验、局限；3 个公式、2 个表格、10 个学习检查 |
| 证据整改 | 27 条非逐字摘录全部有处置：20 条替换为来源原文切片并标 `verified_normalized`，7 条归类为表格/公式结构化证据；`evidence_quotes_in_source` 从 warn 变为 pass |
| claim-001 拆分 | claim-001 收窄为“取代循环层”；新增 claim-023“完全摒弃卷积”，配 `evidence-034`（摘要逐字引文） |
| 计时证据 | `scripts/measure-narration-timing.py` 用 Windows SAPI（Huihui）+ FFprobe 实测完整口播 **19.96 分钟** |
| 发布门禁 | Gate 4 增加 `course_product_current`、`course_product_qualified`、`course_product_human_pending`；无契约项目报 `not_run`，不冒充通过 |

## 二、课程实际交付内容与学习目标覆盖

| 模块 | 时间目标 | 学习目标 | 公式/表格/检查 |
|---|---|---|---|
| slide-001 论文要解决的问题 | 2 min | 并行化与长距离依赖；出发点与代价 | 1 个检查 |
| slide-002 Transformer 总体架构 | 3 min | 编码器—解码器数据流；残差/归一化/掩码 | 1 个检查 |
| slide-003 缩放点积注意力 | 4 min | Q/K/V、缩放、softmax、输出形状 | 公式 + 1 个检查 |
| slide-004 多头注意力 | 2 min | 投影、拼接、W^O 维度；动机边界 | 公式 + 1 个检查 |
| slide-005 位置编码 | 1 min | 正弦/余弦构造；动机与证据边界 | 公式 + 1 个检查 |
| slide-006 复杂度与并行性 | 3 min | 复杂度/顺序操作/路径长度；n<d 条件 | 表 + 1 个检查 |
| slide-007 翻译实验与消融 | 3 min | 27.3/28.4；41.0/41.8；25.8/26.4 是 dev | 表 + 1 个检查 |
| slide-008 局限与学习检查 | 2 min | 结论边界；综合检查 | 3 个检查 |

- 8 个学习目标全部映射到实际章节，且每章正文长度超过 Gate B 的实质内容阈值。
- 3 个公式块均与已复核转录在 `latex-tokens/v1` 规范化后一致。
- 学习检查共 **10 个**，每个都有问题、答案和依据；尚未由真实学习者作答（见第五节）。

## 三、证据整改统计与待人工记录

27 条非逐字摘录的处置（逐条明细见
[`evidence-remediation-2026-10-24.json`](evidence-remediation-2026-10-24.json)）：

| 处置 | 数量 | 说明 |
|---|---|---|
| `relocated` | 20 | 替换为来源文本的真实切片，保留抽取产生的数学/引文痕迹；`quote_status=verified_normalized` |
| `structural` | 7 | 表格行或公式转录，改由结构化证据/复核记录检查，不再按引文比较 |
| `not_relocated` | 0 | — |

- `evidence_quotes_in_source` 当前为 **pass**：25 条引文可在来源中找到；9 条表格/公式证据按结构检查。
- `claim-001` 已拆分为 claim-001（取代循环层）+ claim-023（摒弃卷积），后者配真实摘要引文；
  `key_claims_have_evidence=pass`，但两条都仍需人工核验。
- 八条结构化复核记录仍为 **8/8 pending**；41.0/41.8 未正式裁决。Gate A 未通过。

## 四、实际时长与计时方法

- 方法：**TTS 完整口播**（Windows SAPI `Microsoft Huihui Desktop`），音频写入
  `var/timing/narration.wav`，用 FFprobe 读取时长。
- 实测：**1197.62 秒 = 19.96 分钟**；目标 20 分钟；口播稿 5,283 字。
- 证据：[`timing-evidence-2026-10-24.json`](timing-evidence-2026-10-24.json) 记录
  `method=tts_readthrough`、脚本 SHA-256、音频 SHA-256、语音名称与生成时间。
- 边界：TTS 是**实测音频**，但不是人类讲者的最终录音；Gate B 接受它作为计时证据，
  人工课程验收仍必须确认计时项（`--timing-confirmed`）。

## 五、学习检查结果

- 已交付 10 个检查题，覆盖：循环为何不能并行、解码掩码、缩放作用、多头维度、
  位置编码必要性、n>d 是否一定更慢、25.8/26.4 的数据集、41.8 的核对方法、
  注意力计算过程、并行度与计算量的区别。
- 每个检查都有答案与依据，模板以 `<details>` 折叠，避免直接泄题。
- **尚未由真实学习者作答**；没有学习结果数据。Gate B 只检查题目存在与完整，
  不把“有题”当成“学习者已理解”。

## 六、桌面与移动端视觉验收

- Gate 3：10 个页面/视口组合加载成功，无 JavaScript 错误，无横向溢出；
  新增的 Table 2 结果表在 mobile 视口曾溢出 28px，已用 `overflow-wrap:anywhere` 修复。
- 10 张截图与旧基线不同（内容已重构），`browser_visual_regression` 为 warn；
  必须由人工确认新内容后再更新基线，不能把新截图直接当作正确答案。

## 七、测试与审计结果

| 检查 | 结果 |
|---|---|
| `pytest` | **582 passed, 49 skipped**（新增 `tests/test_course_quality.py` 14 个测试） |
| `ruff check` | passed |
| `ruff format --check` | 121 files formatted |
| `mypy src` | passed（53 文件） |
| `lces build` | exit 0 |
| `lces validate` | exit 0（Gate 1 warn、Gate 2 warn、Gate 3 warn） |
| `lces audit-course` | **passed**，课程版本 `7bf523070d26`，0/0/0 |
| `lces audit-product` | **needs_human_review**，blocker=0，human=2 |
| `lces release-check v1` | exit 1：`decision=blocked` |
| 证据复核校验 | 8/8 链接有效；8/8 人工结论 pending |

Gate B 的内容版本：`249d2f580996a0da`（契约、内容、阅读版、大纲、口播稿与构建 HTML 的哈希绑定）。

## 八、Gate A / Gate B / Gate C 独立状态

| Gate | 状态 | 依据 |
|---|---|---|
| **A 证据事实审核** | **未通过** | 8/8 人工 `pending`；41.0/41.8 未裁决；AI 复核不能替代签署 |
| **B 课程产品验收** | **needs_human_review** | 自动化 blocker=0；契约 `draft` 未批准；课程验收记录缺失；TTS 计时与视觉需人工确认；学习者结果缺失 |
| **C 发布审批** | **未开始 / blocked** | `release/v2` 未创建；`release/v1` 资产过期、签署未完成；没有 `approve` |

Gate A 通过不会自动使 B 通过；B 通过也不会自动使 C 通过。

## 九、已知限制与下一步

1. **契约未批准。** 需要产品负责人运行 `lces approve-course-contract --by <name>`；
   本轮保持 `target_duration_minutes=20`，没有降标。
2. **课程产品验收未签署。** 需要真实验收人确认计时、视觉与学习检查后运行 `lces accept-course`。
3. **证据 8/8 未签署。** 冲突项需 `--conflict-ack` 并写明 41.0 口径。
4. **学习者结果缺失。** 10 个检查题尚未由目标学习者完成；这属于真实课程产品验收，不能由规则替代。
5. **TTS 计时不是人类录音。** 19.96 分钟是完整 TTS 口播实测；若最终交付使用真人讲者，需要重新计时。
6. **视觉基线待更新。** 10 张截图与旧基线不同，需人工确认。
7. **蓝图与内容的规模仍有差距。** `course_master.json` 是 25 单元蓝图，本轮 8 节课程覆盖论文核心，
   但不等同于 25 个单元全部实现；Gate 2 的覆盖检查只证明规划完整。
8. **课程工作区不进入 git。** `projects/` 被忽略，内容版本不能由远端提交重建；本报告、
   契约、审计与计时记录是入库的可追溯产物。
9. **程序状态不可复现。** 表格行的 `program_status` 仍保留旧 source map 的历史原因，未提升。

## 十、最终结论

- **工程机制**：通过。Gate B 已从报告文字变成可执行检查，并有正向/负向测试。
- **证据层**：27 条摘录已全部处置，引文检查通过；但八条记录仍需人工签署，Gate A 未通过。
- **课程产品层**：8 节、5,283 字口播、19.96 分钟实测、3 个公式、10 个学习检查；
  自动化 Gate B blocker=0，但契约与人工验收未完成，**Gate B 未通过**。
- **发布层**：**NO-GO**。`release/v1` 不放行，`release/v2` 不创建。
- **P0-B3**：保持关闭；没有扩展证据状态模型，没有引入 LangGraph。

下一步只有人工与产品动作：批准契约、完成八条证据签署、确认计时/视觉/学习检查、
由真实学习者完成检查题，然后重新运行 `audit-product`、`approve`、`release`、
`release-check`。在这些完成前，最终状态保持 **NO-GO**。
