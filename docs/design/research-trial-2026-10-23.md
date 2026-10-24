# P0-B2.1 真实研究试跑验收报告

日期：2026-10-23  
对象：`projects/attention-is-all-you-need`  
模型：`Qwen3-Coder-30B-A3B-Instruct-Q4_K_M`（llama.cpp / SYCL / CPU-MoE 48 层 / 32K）  
代码状态：本次运行使用 P0-B2 分节研究实现；下文“运行后修复”的项目不适用于本次结果。

## 1. 结论

| 层次 | 结果 |
|---|---|
| 输入流程 | **PASS**：62/62 区块各发送一次，无截断，3 次调用全部 `finish_reason=stop` |
| 过程可追踪性 | **PASS**（有保留）：调用窗口、区块、usage、request id 均有记录；阶段级 usage 只记录最后一次调用（已修复），任务状态停留在 `RESEARCHING`（未修复） |
| 研究结构 | **PASS**：24 条 claim / 24 条 evidence，ID 与引用关系有效，0 条证据因未知来源被丢弃 |
| 研究内容 | **FAIL**：核心机制、消融与局限大量漏提；19/24 条摘录不是原文逐字片段；至少 2 条主张存在误提 |
| 是否进入 P0-B3 | **否**。先修正研究提取与证据治理，并用下一次试跑验证 |

这不是“模型多写几条 claim”的问题。真实运行暴露的是：**输入完整，但模型没有把关键内容提取出来，并且把改写当成了原文摘录。**

## 2. 运行记录

| 项目 | 值 |
|---|---|
| provider / model | `local` / `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M` |
| 运行时间 | 2026-10-23 11:38:57 → 11:59:29 UTC（20 分 32 秒） |
| 源文本 | 43,616 字符 |
| SourceMap | 62 个区块 |
| 调用次数 | 3 |
| 输入 / 输出 tokens | 19,761 / 6,954（合计 26,715） |
| `finish_reason` | 3 次均为 `stop` |
| claims / evidence | 24 / 24（key claims 5） |
| 丢弃证据 | 0 |
| 合并主张数 | 未记录（字段在本次运行后才加入） |
| 非逐字摘录数 | 未记录（检查在本次运行后才加入） |

运行窗口（本次实现按 20,000 字符预算打包，未限制章节数）：

| # | 区块 | 字符 | 章节 |
|---|---|---|---|
| 1 | b0000–b0038 | 19,396 | Abstract–§3.3（23 个章节标签） |
| 2 | b0039–b0056 | 19,887 | §3.4–§6.3 |
| 3 | b0057–b0061 | 9,825 | References |

## 3. 结构验收（PASS）

- 62 个区块全部且仅发送一次；无缺失、无重复、无未知区块 ID。
- 24 条证据均指向真实存在的 claim 与 source；没有悬空引用。
- 3 次调用均正常结束，没有截断、超时或 JSON 修复失败。
- 每个窗口的 `chunk_ids`、章节、页码、模型、usage、`finish_reason`、`request_id` 都写入了 `research_analysis.json`。
- 试跑前的旧研究产物已快照到 `var/pre-p0b2-baseline/`；本报告引用的是本次运行产物。

## 4. 内容验收（FAIL）

### 4.1 覆盖：核心内容大量漏提

24 条主张中，**10 条（42%）是参考文献条目**，对课程没有教学价值。剩余 14 条集中在摘要、嵌入、位置编码、复杂度、优化器、正则化和两个结果指标上。

以下关键内容没有对应主张或证据：

- Scaled Dot-Product Attention 的公式与数值含义（§3.2.1）
- Multi-Head Attention 的拆分、拼接与投影（§3.2.2）
- Encoder/Decoder 堆叠与子层连接（§3.1）
- Table 1 的复杂度对比（只有一条概括性复杂度主张）
- Table 3 的模型变体与消融（§6.2）
- 训练数据、硬件与训练时间表（§5.1/§5.2）
- 结论与局限（§7；论文没有独立 Limitations 章节，但课程必须归纳并标注为课程解释）

字符串级检查（只能说明是否出现过，不等于语义正确）：

| 关键项 | 是否出现 |
|---|---|
| 28.4 BLEU | 是 |
| 41.8 BLEU | 是 |
| Table 2 | 是（摘要/§6.1 语境） |
| Table 1 | **否** |
| Table 3 | **否** |
| multi-head | **否** |
| scaled dot-product | **否** |
| positional encoding | 是 |
| complexity | 是 |
| limitation | **否** |

### 4.2 证据忠实度：5/24 逐字匹配

按现有 `evidence_quotes_in_source` 归一化规则（空白、大小写、Unicode 标点、零宽字符）：

- 逐字匹配：5 条（evidence-001–004、011）
- 未匹配：19 条
- 无法核对：0 条

分类如下：

| 类别 | 数量 | 说明 |
|---|---|---|
| 参考文献条目 | 10 | 内容基本忠实，但格式与原文不完全一致；本身不应成为教学 claim |
| 数学/表格/公式排版差异 | 5 | `d_model`、LaTeX 残片、表格重排导致不是连续原文片段 |
| 引用标记/标点截断 | 2 | 摘录省略了原文的 `[12]` 等标记或空格，导致字符串不等 |
| **归类错误（非原文）** | 1 | evidence-014：论文 §5.4 只命名 Residual Dropout 与 Label Smoothing；模型把嵌入/位置编码上的 dropout 写成并列的 “Positional Encoding Dropout”，且摘录不是原文连续片段 |
| 证据与主张不一致 | 1 | evidence-006：主张说乘以 `sqrt(d_model)`，摘录写成 “by d_model”，缺少平方根 |

这说明检查器并没有“误伤”全部 19 条：其中至少 1 条是实质虚构，1 条与主张矛盾；其余多数是“改写后当成摘录”，同样违反研究约束。

### 4.3 误提（Misrepresentation）

1. **claim-010 把 Transformer (big) 的结果说成整个模型的结果。**
   原文 §6.1 与 Table 2 区分 Transformer (base) 27.3 / 38.1 与 Transformer (big) 28.4 / 41.8。claim-010 只写“Transformer 模型取得新的最先进性能”，没有限定 big 变体。这正是评审文档警告的“模型变体泛化”。

2. **claim-014 把嵌入/位置编码上的 dropout 写成并列的第三种命名类型。**
   原文 §5.4 说 “We employ three types of regularization during training: Residual Dropout ... Label Smoothing ...”，随后在 Residual Dropout 段落中说明也会对嵌入与位置编码的和施加 dropout。模型把这部分改写成 “Positional Encoding Dropout” 并与前两者并列，既不是原文命名，摘录也不是连续原文。

3. **claim-006 的证据与主张不一致。**
   主张正确（权重乘以 `sqrt(d_model)`），但摘录写成 “by d_model”。如果读者只核对摘录，会得到错误结论。

### 4.4 证据断链（Broken Linkage）

- 19/24 条摘录不是原文连续片段；其中 1 条与主张矛盾（evidence-006）。
- 10 条参考文献 claim 的 locator 是区块 ID（`source-001:b0057` 等），不是章节或页码；这些 claim 本身也不应存在。
- 核心机制章节（§3.2.1、§3.2.2、§3.2.3）没有任何证据行；模型实际读到了这些区块（窗口 1），但没有提取。

### 4.5 重复与过度合并

- 本次运行没有重复丢弃证据（`dropped_evidence=0`）。
- `merged_claims` 字段尚未加入，无法定量；从 claim 列表看，没有完全重复的语句。
- 真正的问题是**低价值内容占比过高**（10/24 参考文献），而不是重复。

## 5. 原因分析

1. **窗口过大、章节过多。** 窗口 1 包含 39 个区块、23 个章节标签，模型把注意力放在摘要和少量可读段落上，跳过了公式与架构细节。评审文档要求“分节研究”，本次实现只做到了“按预算打包”，没有做到“按章节聚焦”。
2. **参考文献被当成教学内容。** 第三个窗口专门研究 References，产出 10 条无教学价值的 claim，浪费了 1 次调用和 42% 的输出。
3. **数学/表格文本抽取噪声大。** HTML 文本含零宽字符、上下标展开和 LaTeX 残片；模型倾向改写而不是逐字复制，现有提示词没有逐窗口强制校验。
4. **缺少生成时的逐字校验。** 现有 `evidence_quotes_in_source` 只在 Gate 1 事后告警，研究阶段仍然接受非逐字摘录，并把它们写成正式 evidence。
5. **模型能力与任务不匹配（待对照验证）。** `Qwen3-Coder` 是代码模型；本次在公式、表格和限定条件上表现不佳。不能仅凭一次运行断定模型不行，但足以要求下一次试跑做模型对照。

## 6. 运行后已完成的修复

这些修复不改变本次运行结果，但决定下一次试跑的条件：

| 修复 | 位置 |
|---|---|
| 参考文献、致谢、作者单位不再进入研究窗口，并记录为 `excluded_chunks` | `research.py` |
| 窗口按章节变化聚焦：默认最多 2 个连续章节段、达到最小字符量后换窗；真实论文的计划从 3 个大窗口变为约 5 个 7–9k 字符窗口 | `research.py` |
| 提示词新增：公式/表格是重点、摘录必须连续可见、数值必须带 base/big 等变体、不得提取参考文献 | `research.py` |
| 研究阶段逐窗口检查摘录是否在窗口原文中；非逐字证据写入 `notes` 并计入 `non_verbatim_evidence` | `research.py` |
| 引用归一化统一到 `utils.normalize_quote`，剥离零宽字符；Gate 1 与分析脚本共用 | `utils.py` / `validation.py` |
| 每个阶段累计所有模型调用的 usage，不再只记录最后一次 | `providers/base.py` / `orchestrator.py` |
| `merged_claims`、`non_verbatim_evidence`、`excluded_chunks` 写入研究记录 | `research.py` |
| 只读验收工具 | `scripts/analyze-research-trial.py` |

## 7. 验收判定

| 检查项 | 本次结果 |
|---|---|
| 区块处理完整性 | PASS |
| 研究请求可追踪性 | PASS（阶段 usage 与任务状态问题已记录） |
| 结构有效性 | PASS |
| 关键论文要素 | **FAIL** |
| 关键事实准确性 | **FAIL**（claim-010、claim-014、evidence-006） |
| 证据链 | **FAIL**（5/24 逐字匹配） |
| 截断与失败 | PASS |
| 重复与过度合并 | 无法判定（字段缺失）；低价值参考文献占比 42% |

## 8. 下一步

1. 用修复后的代码重跑同一模型（第二次试跑），对比：关键章节覆盖、逐字摘录率、参考文献占比、非逐字证据数、关键事实错误。
2. 若第二次试跑仍无法覆盖 §3.2.1/§3.2.2、Table 3 与局限，则不要用该模型承担研究；按评审文档的路由表，改用 `Qwen3-30B-A3B-Instruct-2507` 或云端模型做研究，本地模型只承担边界清晰的单元初稿与确定性检查。
3. 在进入 P0-B3 之前，至少满足：
   - 关键论文要素在 `PaperMap` 中有证据或明确 `not_found`；
   - 关键 claim 的摘录逐字匹配率达到可接受阈值（阈值需由第二次试跑校准）；
   - 不再出现 Base/Big 混淆或虚构分类；
   - 参考文献不产生教学 claim。
4. 修复任务状态语义：`--only research` 成功后不应停留在 `RESEARCHING`；阶段 usage 汇总已修复，任务状态仍是 P0-B3 的可观测性项。

## 9. 第二次试跑（修复后）——运行失败

修复后按同一模型启动第二次试跑（2026-10-23 12:06:55 → 12:34:01 UTC，27 分 06 秒），阶段以
`ProviderError: local request timed out after 2 attempts` 失败，未写入新的研究产物；第一次试跑的
记录仍保留在项目中。

- 本次已使用：参考文献排除、按章节聚焦的 5 个窗口、提示词规则 8–10、非逐字摘录标记。
- 直接原因：本地模型约 12 t/s；单次请求在 300 秒读取超时前已生成约 3,700 tokens，服务端在
  约 8,741 tokens 时被客户端取消；重试再次超时，阶段显式失败。
- 这不是静默降级：阶段状态为 `FAILED`，错误写入 `stage_runs`，没有把半截结果当成研究完成。
- 修复：本地请求超时调整为 900 秒；研究阶段输出上限设为 4,096 tokens（新增
  `LCES_RESEARCH_MAX_OUTPUT_TOKENS`，orchestrator 取它与 `LCES_MAX_OUTPUT_TOKENS` 的较小值）。
- 第三次试跑已按上述参数启动，结果待补。

这说明“32K 上下文”不等于“可以在 5 分钟内生成任意长度的结构化结果”；每阶段输出预算和请求超时
必须按本地模型速度配置，而不能沿用云端默认值。

### 第三次试跑：输出截断

第三次试跑（12:34:42 → 12:51:22 UTC）以
`OutputTruncatedError: local stopped at the output budget (finish_reason=length)` 失败。
服务端在 4096 tokens 处正好停止（约 330 秒，12.4 t/s），说明该窗口要求的内容超过研究输出上限。

- 这是正确行为：截断结果没有被当成研究完成，阶段显式失败。
- 修正：研究输出上限提高到 6144；提示词增加每窗口最多 10 条 claim / 10 条 evidence /
  10 个 paper_elements，并要求超出时优先保留公式、实验、结果、消融与局限。
- 第四次试跑已按该配置启动。

三次失败依次暴露了三种不同问题：参考文献占比过高（内容）、300 秒超时（速度）、4096 输出截断
（预算）。它们都不是“模型答错”的单一问题，说明本地研究流程需要按窗口预算、超时和输出结构共同
约束，而不能只调一个参数。

## 10. 第四次试跑：覆盖改善，证据纪律仍未达标

第四次试跑（12:52:00 → 13:10:55 UTC，18 分 55 秒）成功完成：5 次调用全部 `stop`，
20,355 输入 / 12,392 输出 tokens，阶段 usage 已正确汇总。参考文献 7 个区块被排除，
55 个可教学区块全部且仅发送一次。

### 10.1 改善

- claim 从 24 条增加到 40 条，参考文献 claim 从 10 条降为 0。
- 核心内容进入研究结果：编码器/解码器结构、6 层堆叠、缩放点积注意力、多头注意力、
  因果掩码、前馈网络、位置编码、复杂度、Table 1/2/3、beam search、成分句法分析、结论。
- 字符串检查中 Table 1、Table 3、multi-head、scaled dot-product 均首次出现。
- `excluded_chunks`、`merged_claims=0`、`non_verbatim_evidence=25` 均已记录。
- 5 个窗口分别为 28、7、7、10、3 个区块；窗口 1 仍包含目录/前置内容，但正文覆盖明显改善。

### 10.2 仍未通过的部分

| 问题 | 证据 |
|---|---|
| 逐字摘录率仍低 | 40 条中 15 条逐字匹配（37.5%），25 条被标记为非逐字；表格重排、省略号、截断句子仍存在 |
| 变体泛化仍存在 | claim-030 / claim-031 写“Transformer 达到 28.4 / 41.8”，证据来自 Transformer (big)，未限定 base/big |
| 正则化归类错误仍在 | claim-029 仍写成“残差 dropout、标签平滑、位置编码 dropout”三种并列类型；摘录只到前两项 |
| 主张分类不可靠 | 40 条全部标为 `fact`，其中包含推断性表述；37 条标为 key，重要性区分失效 |
| locator 不规范 | 25 条证据把区块 ID（`source-001:b00xx`）当作 locator；分析脚本无法映射到章节 |
| 局限仍缺失 | 论文没有独立 Limitations 章节；课程必须把归纳内容标为课程解释，不能伪装成论文原文 |

因此，**覆盖问题已从“严重不足”改善到“方向可用”，但证据纪律仍是失败项**。
`coverage_matrix_complete=PASS` 只说明蓝图覆盖，不说明这次研究产出的证据可信。

### 10.3 运行后修复

- **locator 归一化**：证据 locator 若等于窗口内区块 ID，合并时自动替换为该区块的章节
  （或页码），不再把内部区块编号写进证据定位。
- **提示词新增规则 12–14**：每窗口 key claim 不超过 3 条；结果数值必须带 base/big 限定；
  摘录不得使用省略号、表格拼接、补写或把段落中的不同应用改写成新的并列类别。
- **研究 checkpoint**：每完成一个窗口写入 `internal/research_checkpoint.json`，后续窗口
  失败不会丢失已完成窗口的记录。

这些修复需要下一次试跑验证，不能据此宣称研究质量已经通过。

### 10.4 路由建议

同一模型三次失败/一次部分成功说明：Coder 30B 能读出论文结构，但**不能稳定遵守逐字摘录、
变体限定和类别归纳约束**。不建议再用相同配置重复整篇试跑。下一步应在相同窗口和门禁下做一次
受控对照：

- `Qwen3-30B-A3B-Instruct-2507`（本地，已存在于模型目录）；
- 或云端研究模型（若允许外传材料）。

对照指标沿用本报告：逐字摘录率、非逐字证据数、base/big 限定、key claim 比例、核心要素覆盖、
每窗口耗时与 tokens。只有在证据纪律通过后才进入 P0-B3 的单元生成。

第五次试跑已切换为 `Qwen3-30B-A3B-Instruct-2507-Q4_K_M`，使用相同的 5 个窗口、提示词规则
11–14、6,144 输出上限和 900 秒超时；结果待补。

## 11. 第五次试跑：Instruct 对照

第五次试跑切换到 `Qwen3-30B-A3B-Instruct-2507-Q4_K_M`，使用相同窗口、提示词规则 11–14、
6,144 输出上限和 900 秒超时（13:13:48 → 13:48:46 UTC，34 分 58 秒）。

| 指标 | 第四次（Coder） | 第五次（Instruct） |
|---|---|---|
| 调用 / 可教学区块 | 5 / 55 | 5 / 55 |
| 输入 / 输出 tokens | 20,355 / 12,392 | 28,146 / 16,164 |
| claims / evidence | 40 / 40 | 22 / 33 |
| 无证据 claim | 0 | **3**（claim-001/002/003，均为摘要关键主张） |
| 丢弃证据 | 0 | **8**（证据引用了不存在的 claim） |
| 逐字摘录 | 15/40（37.5%） | **4/33（12.1%）** |
| 非逐字证据 | 25 | 29 |
| key claim 比例 | 37/40（92%） | 14/22（64%） |
| 主张类型 | 40 fact | 20 fact / 2 inference |
| base/big 限定 | 错误/缺失 | **正确**（claim-017 big、claim-018 base） |
| 正则化归类 | 错误 | **正确**（claim-019） |
| locator | 区块 ID（运行后修复） | 章节/表格名，映射生效 |
| 阶段 usage 汇总 | 正确 | 正确 |

### 11.1 结论

两个本地模型形成互补，但都没有达到研究阶段的证据要求：

- **Coder**：引用链路更好、逐字率更高，但变体限定和类别归纳错误，key/type 标注几乎失效。
- **Instruct**：变体与类别更准确、locator 更规范，但逐字率更低，并且出现 8 条证据丢弃、3 条关键
  摘要主张无证据——这在结构上比 Coder 更差。

根本问题不是“哪个模型更会写”，而是**让模型自由生成 `source_excerpt` 再把改写当摘录**这一
机制本身不可靠。继续换模型只会改变失败比例，不会让证据逐字可信。

### 11.2 路由决定

1. **不使用任一本地模型作为研究证据的生产者。** Coder 保留给代码/结构类任务；Instruct 可用于
   后续单元初稿，但研究证据必须来自更可靠的机制。
2. **首选云端研究模型**（DeepSeek / Anthropic），前提是完成评审文档要求的云端准入：密钥、
   地区、数据条款、预算、失败语义。当前 `.env` 未配置云端密钥，所以暂不能执行。
3. **若不使用云端，则改造证据提取方式**：模型只返回 `source_id` + `chunk_id` + 一段候选引文；
   程序在区块内做精确或受控定位，只有定位成功的片段才写成 `source_excerpt`；定位失败就把该
   evidence 标为 `needs_review`，不允许把改写当作原文。该方案需要在 P0-B3 之前单独验证。
4. **不进入 P0-B3 的单元生成。** 研究证据链仍未通过；先把证据提取机制修好，再冻结
   `CourseMaster` / `UnitDraft`。

### 11.3 环境状态

对照试跑期间 `llama-server` 加载的是 Instruct 模型，`.env` 的 `LCES_LOCAL_MODEL`
也临时指向它。对照结束后已停止该服务，并把 `.env` 恢复为原来的
`Qwen3-Coder-30B-A3B-Instruct-Q4_K_M`；这不是对研究路由的选型决定。最终模型路由需按 11.2
重新配置。

## 12. 本地证据定位器（P0-B2.2）

按评审决定，先实现本地证据定位器；云端研究路由暂缓，P0-B3 继续关闭。

### 12.1 机制

- `evidence_locator.py` 接收 `QuoteCandidate`（source、chunk、claim、候选文本），只在候选
  指定的区块内查找；不跨区块搜索，不跨区块拼接。
- 完全匹配 → `verified_exact`；仅排版归一化后匹配 → `verified_normalized`；找不到、歧义、
  过短 → `needs_review`；claim/source/chunk 无效 → `rejected`。
- 正式 `source_excerpt` 由程序从原文切片生成；模型返回的候选文本不会直接进入台账。
- 只有 `verified_exact` / `verified_normalized` 进入 `evidence_ledger.csv`；其余连同原因写入
  `internal/qa/quote_audit.json`。
- 不做模糊通过：数学符号改写、表格重排、省略号、跨区块拼接都不会被接受。
- `EvidenceRecord` 新增 `chunk_id` 与 `quote_status`；研究记录包含每次调用的 `quote_audit`
  计数和合并后的审计摘要。

### 12.2 两个窗口的验证设计

- 窗口 A：§3.2.1 Scaled Dot-Product Attention + §3.2.2 Multi-Head Attention。
- 窗口 B：§6.1 Machine Translation + §6.2 Model Variations。
- 使用同一源文件、同一 SourceMap、同一模型与输出配置；不修改项目研究产物，报告写入
  `var/quote-locator-trial/`。
- 验证脚本：[`scripts/trial-quote-locator.py`](../../scripts/trial-quote-locator.py)。

### 12.3 验收口径

| 指标 | 要求 |
|---|---|
| 正式证据原文可定位率 | 100%（由切片机制保证） |
| 跨区块拼接 | 0 |
| 无效 claim/source/chunk 通过 | 0 |
| 数学/数值改写通过 | 0 |
| base/big 限定丢失通过 | 0 |
| 未定位候选 | 全部显式进入 `needs_review` / `rejected` |
| 四个目标小节关键要素 | 逐项人工核对 |
| 主张—证据语义支持 | 独立人工审查，不能由字符串匹配代替 |

结果已补：[`docs/design/quote-locator-trial-2026-10-24.md`](quote-locator-trial-2026-10-24.md)。
定位器安全性通过（0 跨区块、0 无效 ID、0 数学改写通过），但 18 条候选中仅 6 条逐字定位，
关键公式与 Table 2/3 证据未定位；结论是继续修源文本/区块归属/证据类型，不进入 P0-B3。

## 13. 产物位置

- 本次运行快照：`var/research-run1/`（git 忽略）
- 本次运行记录：`projects/attention-is-all-you-need/internal/research_analysis.json`
- 逐条 claim/evidence 评审：`var/research-review.md`（git 忽略）
- 引文差异诊断：`var/quote-diagnostics.md`（git 忽略）
- 只读汇总工具：[`scripts/analyze-research-trial.py`](../../scripts/analyze-research-trial.py)
