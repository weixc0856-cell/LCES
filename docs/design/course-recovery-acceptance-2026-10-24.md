# LECS 课程恢复与重新验收（P4，2026-10-24）

对象：`projects/attention-is-all-you-need`  
任务：`LECS — Course Recovery & Release Requalification`  
**当前验收结论：工程机制基本通过；课程产品验收未通过；正式发布资格未满足（NO-GO）。**
`release/v1` 保留为历史版本，不覆盖、不撤回。

> **自动化内容审计 `passed` 只表示审计规则集覆盖的数值、公式、冲突披露没有发现问题，
> 不等于课程达到交付标准。** 本报告把证据审核（Gate A）、课程产品验收（Gate B）和发布审批
> （Gate C）分开记录；Gate A/B/C 互不替代。
>
> 八条证据记录的 `conclusion` 全部保持 `pending`；AI 没有、也不会代替人工签署。
> 课程工作区 `projects/` 不进入 git，`course_version` 只能证明审计与本地文件一致，
> 不能仅凭远端提交重建该课程版本。

## 一、执行结果

| 命令 | 结果 |
|---|---|
| `lces build` | 5 节课程重建成功（3 个公式块、2 个表格） |
| `lces audit-course` | **自动化内容审计 passed**：blocker=0, major=0, advisory=0，课程版本 `b4019062089e` |
| `lces validate` | **exit 0**：Gate 1 warn、Gate 2 warn、Gate 3 warn，无阻断（预计 2.8 分钟 / 目标 20 分钟；视觉基线与旧版不同） |
| `scripts/validate-review-record.py` | 8/8 链接有效；`pending human conclusions: 8/8` |
| `lces release-check --version v1` | exit 1：`decision=blocked`（签署、冲突确认、资产版本） |
| `lces release --version v2` | exit 1：`human approval for v2 is missing`（未创建 `release/v2`） |

### 推送基线与课程版本

- 代码分支：`feat/course-content-audit-release-gate`；本轮报告入库的代码起点为
  `5bdeafe603bff74f373ba0a602f408e21f186adc`，其后还有 P4 修正、模板与文档提交。
- 干净工作树 `git worktree add --detach ../LECS-pushed-p4 5bdeafe`：
  568 passed / 49 skipped，ruff、format（118 files）、mypy（52 files）全部通过。
- **课程版本不能由 git 提交重建**：`projects/` 被 `.gitignore` 排除，当前课程版本
  `b4019062089e` 只对应本机文件哈希。代码回归在干净工作树完成，课程审计在本机完成，
  两者不能互相冒充。
- 在推送提交上复跑真实课程：审计 `passed`（`b4019062089e`，0/0/0），
  `release-check v1` 仍为 `decision=blocked`。

产物：

- `content/public_content.json`（5 节，含公式与解释）
- `content/reading_edition.json`（5 节，与幻灯片一一对应）
- `content/outline.json`（5 节，evidence_ids 已改为全局 ID）
- `internal/speaker_script.json` / `.md`（5 节口播稿）
- `internal/claims.json`（20 条，claim-001/002/003 已修复）
- `internal/evidence_ledger.csv`（同一批证据，未新增、未复制）
- `internal/qa/course_content_audit.json`（课程版本 `b4019062089e`）
- `docs/design/course-content-audit-2026-10-24.json`（归档副本）
- `docs/design/course-content-audit-p4-first-pass-2026-10-24.json`（P4 首轮通过版，保留历史）
- `docs/design/course-content-audit-pre-recovery-2026-10-24.json`（恢复前审计，保留历史）
- `docs/design/structured-evidence-review-2026-10-24.json`（8 条复核记录）
- `templates/public_html/course.html.j2`（表格单元格增加 `overflow-wrap:anywhere`，修复移动端 28px 溢出）

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

**边界：** `key_claims_have_evidence=pass` 只说明每条关键主张至少有支持或部分支持的证据，
不等于主张已被完整证明。`claim-001` 的 `evidence-033` 只明确提到循环层，“摒弃卷积”仍缺直接引文；
该主张的人工核验应保持 pending，或拆成两个可独立核对的主张。

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

根据审查意见，本轮又修正了以下技术表述（`b4019062089e`）：

- 第 1 节不再泛称“训练成本显著低于同类模型”，改为“当时最佳模型的一小部分（论文摘要 / §6.1 口径）”。
- 第 2 节补充 Q/K/V 与输出的形状流转：长度为 n 时 Q/K 为 n×d_k、V 为 n×d_v、分数矩阵 n×n、输出 n×d_v。
- “单头平均会抑制”改为论文的机制说明，并明确它不是对所有任务的实验保证。
- 位置编码波长改为“论文描述成几何级数（约从 2π 到 10000·2π，端点取决于 d_model 与维度索引）”。
- 复杂度一节补充“n 小于 d 时自注意力比循环层更快”的比较条件。
- 第 4 节增加 Table 2 结果表（base/big、任务数据、BLEU、口径），并修复移动端表格溢出。
- 第 5 节增加“消融 / 泛化 / 局限分别回答什么”的引导。

**覆盖矩阵与实际内容的边界：** `course_master.json` 仍是 25 个教学单元的蓝图，
当前生成课程是 5 节精读，不是 25 单元的完整课程。Gate 2 的
`coverage_matrix_complete` 检查的是**规划**（必需要素在蓝图中有单元），不是“生成内容已实现全部单元”。
本报告不把该检查当作内容覆盖证明；要声称完整覆盖，需要按 P0-B3 生成 25 个单元，
本轮没有重开 P0-B3。详见“已知限制”。

## 三·补：课程产品验收（Gate B）未通过

自动化内容审计（Gate A 的规则子集）通过，不代表课程产品验收通过。当前产品状态：

| 项目 | 现状 | 判定 |
|---|---|---|
| 目标时长 | 预计 **2.8 分钟**（按 4.2 字/秒估算，不是实测音视频时长） | 目标 20 分钟，**未达标** |
| 教学完整性 | 5 节覆盖公式、结构、结果、消融与局限 | 是短篇导读的密度，不是 20 分钟精读课 |
| 学习检查 | 没有练习、自测或学习任务 | 缺失 |
| 实际呈现 | 只有静态 HTML；没有实际录音/视频计时 | 未验收 |
| 视觉基线 | 10 张截图与旧基线不同 | 待人工确认 |
| 目标受众 | 具备 Python 与基础深度学习背景 | 内容深度与该受众的 20 分钟预期不匹配 |

产品负责人需要在两条路径中选择，不能靠填充文字凑时长：

1. **保持 20 分钟精读课**：按 25 单元蓝图补齐讲解、示例、公式推导、实验解读、学习检查，
   用实际录音/渲染计时重新验收。
2. **正式降级为短篇导读**：修改 `project.yaml` 的 `target_duration_minutes`，在标题、
   描述和发布说明中明确这是导读而非完整精读课，并重新冻结受众与学习目标。

在该决策完成前：**NO-GO，不审批 `release/v2`。**

## 三·补二：Gate A / Gate B / Gate C

| Gate | 回答的问题 | 当前状态 |
|---|---|---|
| A 证据事实审核 | 原文、数字、公式、定位与主张关联是否准确？ | 8/8 人工 `pending`，41.0/41.8 冲突未裁决 → **未通过** |
| B 课程产品验收 | 是否达到受众、教学目标、完整性、时长与呈现质量？ | **未通过**（2.8 分钟 / 目标 20 分钟；无实测音视频；视觉基线待确认） |
| C 发布审批 | 最终资产是否与已验收内容一致并获得授权？ | **未开始**（`release/v2` 未创建；`release/v1` blocked） |

Gate A 通过不自动使 Gate B 通过；Gate B 通过也不自动使 Gate C 通过。

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

其余六条：`review-table2-big-ende-28.4`、`review-table3-big-26.4`、
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
  `b4019062089ee6eaaa2375be0dbe1217a14688afca4398c20ea4036778bfcb0d`，
  绑定 4 个文件的 SHA-256，旧报告没有复用。首轮 `a646938f6e80` 的报告单独保留。
- `lces validate` 通过（Gate 1 warn / Gate 2 warn / Gate 3 warn，无阻断）；
  新增的 Table 2 结果表在 mobile 视口曾产生 28px 横向溢出，已通过
  `templates/public_html/course.html.j2` 的 `overflow-wrap:anywhere` 修复并复验。
- `release/v1` 仍被拒绝：8 条签署 pending、冲突未确认、v1 资产不是当前被审计版本。
- `release/v2` 在创建前被拒绝：缺少人工审批。没有生成任何 `release/v2` 目录。

## 七、P4 验收清单（8 项）

| # | 条件 | 状态 | 证据 |
|---|---|---|---|
| 1 | claim-001/002/003 的证据缺口已真实修复 | **完成（结构）** | 主张合并与证据改挂；`key_claims_have_evidence=pass`；claim-001 仅部分支持，仍需人工确认 |
| 2 | 两条公式恢复，位置编码公式完成正式复核 | **部分完成** | 公式与解释已恢复；第 8 条记录已建，正式人工复核仍 pending |
| 3 | 28.4 的模型规模及数据集语境完整 | **完成** | big + EN-DE + newstest2014；base 27.3 同页 |
| 4 | 41.0 / 41.8 冲突已裁决、披露并完成签署 | **部分完成** | 课程口径与披露完成；正式裁决与签署 pending |
| 5 | 八条记录的正式人工审核状态完整且可追溯 | **未完成** | 8/8 pending；AI 复核独立记录 |
| 6 | 课程审计报告与最终内容 SHA-256 一致 | **完成** | `b4019062089e…`，4 个文件哈希绑定 |
| 7 | 最终发布资产通过全部门禁与负向回归测试 | **未完成** | v1 blocked；v2 未创建（缺签署与审批）；负向测试全绿 |
| 8 | 旧版 v1 的保留、撤回或勘误决定已记录 | **完成** | 保留为历史版本并标记不符合现行门禁；不覆盖、不撤回 |

统计：**4 完成 / 2 部分 / 2 未完成**。发布放行条件不满足。

## 八、已知限制（本轮未解决）

1. **人工签署 8/8 未完成。** 这是发布放行的唯一硬阻断之一；AI 不能代签。
2. **人工审批缺失。** `release/v2` 需要在签署后由发布负责人执行 `lces approve`。
3. **27 条证据摘录非逐字。** `evidence_quotes_in_source` 为 warn：这些是早期模型改写的摘录，
   台账中已标注，但没有逐条重新定位。下一步可用确定性 locator 重新生成这些行，而不是继续保留 warn。
4. **蓝图与生成内容规模不一致。** `course_master.json` 是 25 单元蓝图，当前课程是 5 节精读；
   Gate 2 的覆盖检查只证明蓝图完整，不证明生成内容覆盖全部单元。
5. **时长警告。** 预计 2.8 分钟，项目目标 20 分钟；目标值对应 25 单元蓝图，当前课程未达到，
   也没有用实际录音/视频计时。
6. **程序状态不可复现。** 表格行的 `program_status` 仍是旧 source map 的历史值；本轮没有提升任何状态。
7. **视觉基线未更新。** Gate 3 `browser_visual_regression` 为 warn，10 张截图与旧基线不同，
   需要人工确认新内容后再更新基线。
8. **课程工作区未版本化。** `projects/` 被 `.gitignore` 排除，`course_version` 不能由远端提交重建；
   这是公开/私有边界的有意设计，但意味着发布审计必须与课程产物一同归档。
9. **claim-001 只被部分支持。** `evidence-033` 未覆盖“摒弃卷积”；在拆分主张或补证据前，
   不应把它当作完全成立。
10. **学习检查缺失。** 课程没有练习、自测或学习任务，产品验收不能只靠内容审计。

## 九、release/v1 处置

按“保留历史、不静默覆盖”的原则：

- `release/v1` 保持原样，作为历史发布资产。
- 已记录其不符合现行门禁：41.8 未披露 41.0、位置编码公式只显示偶数维且与复核转录不一致、
  资产与当前审计版本不一致。
- 不在本轮撤回或下架；是否发布勘误由发布负责人决定。
- 恢复后的版本使用 **v2**，在人工签署与审批完成后构建，不覆盖 v1。

## 十、整改清单（0/6 已完成）

| # | 整改项 | 状态 |
|---|---|---|
| 1 | 修复证据完整性：拆分或补证 claim-001、重新定位 27 条非逐字摘录、确认 locator 与列语义 | 未开始 |
| 2 | 完成八条人工证据审核（冲突项单独裁决并写入口径） | 未开始（8/8 pending） |
| 3 | 重新定义课程交付标准：20 分钟精读课，或正式降级为短篇导读 | 待产品负责人决策 |
| 4 | 补齐教学内容：推导、示例、实验解读、章节衔接、学习检查 | 部分（技术表述已修正，深度与学习检查未补） |
| 5 | 验收实际呈现：实测时长、公式可读性、布局、视觉回归、引用展示 | 部分（移动端溢出已修；实测与视觉未完成） |
| 6 | 重新审计与发布判定：证据、课程、视觉、授权全部通过后再审批 | 未开始（依赖 1–5） |

## 十一、结论

- **工程层**：自动化测试、静态检查、证据隔离与门禁负向测试通过
  （568 passed / 49 skipped；ruff、format、mypy 通过）。这只证明机制按规则运行。
- **证据层**：8 条人工签署 pending；41.0 / 41.8 尚未完成正式人工裁决。
- **课程层**：内容已恢复到可审计状态，但**产品验收未通过**：
  预计 2.8 分钟 vs 目标 20 分钟；没有学习检查；没有实测音视频；视觉基线待确认。
- **发布层**：**NO-GO**。`release/v1` 不放行；`release/v2` 不创建。
- **版本管理**：v1 保留为历史资产；新版本须重新构建、重新审计、完成 Gate A/B/C 后再审批。
- **P0-B3**：保持关闭；不扩展证据状态模型，不引入 LangGraph。

下一步是人工与产品决策，不是把 `pending` 改成 `pass`。完成整改清单后重新运行审计与门禁，
并把新的课程版本、审计哈希和验收结论追加到本报告。
