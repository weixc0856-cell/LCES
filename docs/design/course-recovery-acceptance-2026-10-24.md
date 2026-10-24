# LECS 课程恢复与重新验收（P4，2026-10-24）

对象：`projects/attention-is-all-you-need`  
任务：`LECS — Course Recovery & Release Requalification`  
结论：**课程内容与证据关联已恢复到可审计状态（6/8 项完成）；发布仍被人工签署与审批阻断（2/8 项只能由人完成）。
`release/v1` 保留为历史版本，不覆盖、不撤回。**

> 本报告只记录实际执行过的命令与产物。AI 没有、也不会代替人工签署；
> 八条 `conclusion` 全部保持 `pending`。课程审计通过只证明列出的检查项成立，不是课程事实的最终背书。

## 一、执行结果

| 命令 | 结果 |
|---|---|
| `lces build` | 5 节课程重建成功（3 个公式块、1 个复杂度表） |
| `lces audit-course` | **passed**：blocker=0, major=0, advisory=0，课程版本 `a646938f6e8016eb` |
| `lces validate` | **exit 0**：Gate 1 warn、Gate 2 warn、Gate 3 warn，无阻断 |
| `scripts/validate-review-record.py` | 8/8 链接有效；`pending human conclusions: 8/8` |
| `lces release-check --version v1` | exit 1：`decision=blocked`（签署、冲突确认、资产版本） |
| `lces release --version v2` | exit 1：`human approval for v2 is missing`（未创建 `release/v2`） |

### 推送基线

- 分支：`feat/course-content-audit-release-gate`，提交 `5bdeafe603bff74f373ba0a602f408e21f186adc`
  （本地与 `origin` 一致）。
- 干净工作树 `git worktree add --detach ../LECS-pushed-p4 5bdeafe`：
  568 passed / 49 skipped，ruff、format（118 files）、mypy（52 files）全部通过。
- 在推送提交上复跑真实课程：审计仍为 `passed`（`a646938f6e80`，0/0/0），
  `release-check v1` 仍为 `decision=blocked`（8 条 pending、冲突未确认、v1 资产过期）。
- 课程工作区 `projects/` 按仓库策略不进入提交；本报告、审计报告和复核记录是入库的可追溯产物。

产物：

- `content/public_content.json`（5 节，含公式与解释）
- `content/reading_edition.json`（5 节，与幻灯片一一对应）
- `content/outline.json`（5 节，evidence_ids 已改为全局 ID）
- `internal/speaker_script.json` / `.md`（5 节口播稿）
- `internal/claims.json`（20 条，claim-001/002/003 已修复）
- `internal/evidence_ledger.csv`（同一批证据，未新增、未复制）
- `internal/qa/course_content_audit.json`（课程版本 `a646938f6e8016eb`）
- `docs/design/course-content-audit-2026-10-24.json`（归档副本）
- `docs/design/course-content-audit-pre-recovery-2026-10-24.json`（恢复前审计，保留历史）
- `docs/design/structured-evidence-review-2026-10-24.json`（8 条复核记录）

## 二、P4-A：主张与证据台账修复

问题：`claim-001/002/003` 没有台账证据，而同一事实在 `claim-017`、`claim-022` 下已有证据。
这是同一轮研究被拆成两批 claim 编号后留下的重复与漂移。

处理方式：**合并重复主张、改挂真实证据，不复制证据行、不新增虚构引用。**

| 主张 | 处理 | 证据 |
|---|---|---|
| `claim-001` 完全基于注意力、摒弃循环/卷积 | 保留；`evidence-033`（结论段引文）从 `claim-022` 改挂 | `partially_supports`（引文只提循环层，未提卷积） |
| `claim-002` 28.4 BLEU | 补上 `Transformer (big)` 限定；`evidence-024`（§6.1 引文）从 `claim-017` 改挂 | `supports` |
| `claim-003` EN-FR 41.8 | 改写为冲突感知：arXiv Table 2/摘要 41.8，§6.1 正文/NeurIPS Table 2 41.0；`evidence-021`（Table 2 行）与 `evidence-026`（3.5 天）从 `claim-017` 改挂 | `supports` |
| `claim-017` / `claim-022` | 与 claim-002 / claim-001 重复，删除 | 证据已改挂，不丢失 |

结果：`lces validate` 的 `key_claims_have_evidence` 从 fail 变为 **pass**；`claims_parse` 显示 20 条主张；
证据台账仍是 33 行，没有新增行。`outline.json` 的 `evidence_ids` 也从窗口局部 ID 改为全局 ID。

## 三、P4-B：课程内容与技术解释恢复

`content/public_content.json` 从 3 节恢复为 5 节，并重建 HTML：

| 内容 | 恢复情况 |
|---|---|
| 缩放点积注意力 | 公式 + Q/K/V、d_k/d_v、缩放项、softmax 行归一化、输出为 V 加权和；明确“权重不是人类语义重要性” |
| 多头注意力 | 两行公式 + 每头投影维度、拼接、`W^O` 维度、`h=8`、`d_k=d_v=d_model/h=64`、子空间动机 |
| 位置编码 | 正弦/余弦公式 + 位置/维度符号、波长几何级数；明确外推是作者解释而非实验结论 |
| 28.4 BLEU | 明确 `Transformer (big)`、WMT 2014 EN-DE、newstest2014；同时给出 base 27.3 |
| Table 3 | base 25.8 / big 26.4，明确 EN-DE 开发集 newstest2013、`BLEU (dev)`、未列值继承 base 行 |
| 复杂度与局限 | 编码器/解码器 N=6、残差+层归一化、FFN 512/2048、O(n²·d) 与 O(1) 顺序操作、长序列成本与泛化边界 |

位置编码公式此前从未复核。P4 新增第 8 条复核记录 `review-formula-positional`
（paper-014，`source-001:b0040`，§3.5），转录、符号、维度与外推限制均已记录，
AI 实质复核为 `consistent`，人工签署仍为 `pending`。

**覆盖矩阵与实际内容的边界：** `course_master.json` 仍是 25 个教学单元的蓝图，
当前生成课程是 5 节精读，不是 25 单元的完整课程。Gate 2 的
`coverage_matrix_complete` 检查的是**规划**（必需要素在蓝图中有单元），不是“生成内容已实现全部单元”。
本报告不把该检查当作内容覆盖证明；要声称完整覆盖，需要按 P0-B3 生成 25 个单元，
本轮没有重开 P0-B3。详见“已知限制”。

## 四、P4-C：41.0 / 41.8 来源冲突

课程现在采用并披露以下口径：

- 讨论 **Table 2 / §6.1** 时使用 **41.0**（NeurIPS 2017 会议版 Table 2 与正文）。
- 同时披露本地 arXiv 版本的 **Table 2 与摘要为 41.8**。
- 不取平均、不静默择一；正文、表格、讲义、幻灯片与口播稿使用同一口径。
- 冲突记录仍为 `source_conflict`，`conflict_acknowledged=false`；正式裁决与签署待人工完成。
  人工 `pass` 必须带 `--conflict-ack` 并在 basis 中写明采用 41.0 的理由。

## 五、P4-D：正式人工签署（未完成，且不应由 AI 完成）

八条记录全部 `pending`。AI 实质复核（`reviewer_kind=ai`）已独立记录，
但它不是、也不会被写成签署。以下命令必须由真实审核者在核对原文后执行
（示例，不代填姓名与日期）：

```powershell
uv run lces review-evidence .\projects\attention-is-all-you-need `
  --review-id review-table2-base-27.3 --by "<审核者>" --conclusion pass `
  --basis "<核对 Table 2 base 行与 newstest2014 口径后的依据>"

# 冲突项必须显式确认口径
uv run lces review-evidence .\projects\attention-is-all-you-need `
  --review-id review-table2-big-enfr-conflict --by "<审核者>" --conclusion pass `
  --conflict-ack --basis "采用 §6.1/NeurIPS Table 2 的 41.0；arXiv Table 2/摘要 41.8 已在课程中披露"
```

其余五条：`review-table2-big-ende-28.4`、`review-table3-big-26.4`、
`review-table3-base-25.8`、`review-formula-attention`、`review-formula-multihead`、
`review-formula-positional`。对无法独立确认的记录，应保留 pending 或使用
`needs_revision` / `blocked`，不要为了清空待办而批量通过。

签署完成后：

```powershell
uv run lces approve .\projects\attention-is-all-you-need --version v2 --by "<发布负责人>" `
  --notes "P4 恢复后复核"
uv run lces release .\projects\attention-is-all-you-need --version v2
uv run lces release-check .\projects\attention-is-all-you-need --version v2
```

## 六、P4-E：重新审计、构建与发布判定

- 课程内容变更后已重新构建、重新审计；审计 `course_version` 为
  `a646938f6e8016eb54d5a9cf54977af3cc97ec391b8deca31d676270b32fc22b`，
  绑定 4 个文件的 SHA-256，旧报告没有复用。
- `lces validate` 通过（Gate 1 warn / Gate 2 warn / Gate 3 warn，无阻断）。
- `release/v1` 仍被拒绝：8 条签署 pending、冲突未确认、v1 资产不是当前被审计版本。
- `release/v2` 在创建前被拒绝：缺少人工审批。没有生成任何 `release/v2` 目录。

## 七、P4 验收清单（8 项）

| # | 条件 | 状态 | 证据 |
|---|---|---|---|
| 1 | claim-001/002/003 的证据缺口已真实修复 | **完成** | 主张合并与证据改挂；`key_claims_have_evidence=pass`；无新增/复制证据行 |
| 2 | 两条公式恢复，位置编码公式完成正式复核 | **完成（签署待人工）** | 5 节内容含 3 个公式块；`review-formula-positional` 已记录，人工 pending |
| 3 | 28.4 的模型规模及数据集语境完整 | **完成** | big + EN-DE + newstest2014；base 27.3 同页 |
| 4 | 41.0 / 41.8 冲突已裁决、披露并完成签署 | **部分完成** | 课程口径与披露已完成；正式签署待人工（需 `--conflict-ack`） |
| 5 | 八条记录的正式人工审核状态完整且可追溯 | **未完成（人工）** | 8/8 pending；AI 复核独立记录 |
| 6 | 课程审计报告与最终内容 SHA-256 一致 | **完成** | `course_version=a646938f6e80…`，4 个文件哈希绑定 |
| 7 | 最终发布资产通过全部门禁与负向回归测试 | **未完成（依赖 5）** | v1 blocked；v2 缺审批；负向测试全绿 |
| 8 | 旧版 v1 的保留、撤回或勘误决定已记录 | **完成** | 保留为历史版本并标记不符合现行门禁；不覆盖、不撤回 |

## 八、已知限制（本轮未解决）

1. **人工签署 8/8 未完成。** 这是发布放行的唯一硬阻断之一；AI 不能代签。
2. **人工审批缺失。** `release/v2` 需要在签署后由发布负责人执行 `lces approve`。
3. **27 条证据摘录非逐字。** `evidence_quotes_in_source` 为 warn：这些是早期模型改写的摘录，
   台账中已标注，但没有逐条重新定位。下一步可用确定性 locator 重新生成这些行，而不是继续保留 warn。
4. **蓝图与生成内容规模不一致。** `course_master.json` 是 25 单元蓝图，当前课程是 5 节精读；
   Gate 2 的覆盖检查只证明蓝图完整，不证明生成内容覆盖全部单元。
5. **时长警告。** 预计 2.7 分钟，项目目标 20 分钟；目标值对应 25 单元蓝图，当前课程未达到。
6. **程序状态不可复现。** 表格行的 `program_status` 仍是旧 source map 的历史值；本轮没有提升任何状态。
7. **视觉基线未更新。** Gate 3 `browser_visual_regression` 为 warn，10 张截图与旧基线不同，
   需要人工确认新内容后再更新基线。

## 九、release/v1 处置

按“保留历史、不静默覆盖”的原则：

- `release/v1` 保持原样，作为历史发布资产。
- 已记录其不符合现行门禁：41.8 未披露 41.0、位置编码公式只显示偶数维且与复核转录不一致、
  资产与当前审计版本不一致。
- 不在本轮撤回或下架；是否发布勘误由发布负责人决定。
- 恢复后的版本使用 **v2**，在人工签署与审批完成后构建，不覆盖 v1。

## 十、结论

- **工程机制**：通过（568+ 测试、ruff、format、mypy；新增审计与门禁负向测试）。
- **课程内容**：已恢复到可审计状态；8 项检查中 6 项完成，2 项等待人工。
- **发布资格**：继续阻断。`release/v1` 不放行，`release/v2` 尚未创建。
- **P0-B3**：保持关闭；本轮没有扩展证据状态模型，也没有引入 LangGraph。

下一步只有人工动作：八条签署、必要时处理冲突口径、审批 v2、确认视觉基线；
完成后再运行一次 `release` 与 `release-check`，并把结果追加到本报告。
