# 结构化证据复核清单（2026-10-24，2026-10-24 实质复核修订）

对象：`projects/attention-is-all-you-need`  
结构化数据：`docs/design/structured-evidence-review-2026-10-24.json`  
正式状态：**全部待人工复核**。

> 记录分三层，互不冒充：
> 1. `research_verification`：外部来源核验，`verified` 只表示“与权威原文一致”；
> 2. `substantive_review`：AI 实质复核，`reviewer_kind` 固定为 `ai`，永远不是签署；
> 3. `reviewer` / `reviewed_at` / `conclusion`：正式人工签署。
>
> `quote_status=verified_structured` 是程序定位状态，是第四种含义，同样不能与以上三层混用。

## 一、八条复核记录

| # | review_id | 论文要素 | 来源 / 区块 | 复核主张 | 程序状态 | 研究核验 | AI 实质复核 | 人工签署 |
|---|---|---|---|---|---|---|---|---|
| 1 | `review-table2-base-27.3` | paper-025 | `source-001:b0048`；Table 2 | base EN-DE newstest2014 = **27.3** | `needs_review / column_semantics_unverified` | `verified` | `consistent`（转录+主张） | **pending** |
| 2 | `review-table2-big-ende-28.4` | paper-025 | `source-001:b0048`；Table 2 | big EN-DE newstest2014 = **28.4** | `needs_review / column_semantics_unverified` | `verified` | `partial`（转录一致；claim-002 未写 big） | **pending** |
| 3 | `review-table2-big-enfr-conflict` | paper-025 | `source-001:b0048`；Table 2 | 41.0 / 41.8 **来源冲突（未裁决）** | `needs_review / column_semantics_unverified` + `source_conflict` | `source_conflict` | `consistent`（冲突建模正确） | **pending** |
| 4 | `review-table3-big-26.4` | paper-027 | `source-001:b0051`；Table 3 | big BLEU (dev) EN-DE newstest2013 = **26.4** | `needs_review / column_semantics_unverified` | `verified` | `consistent` | **pending** |
| 5 | `review-table3-base-25.8` | paper-027 | `source-001:b0051`；Table 3 | base BLEU (dev) EN-DE newstest2013 = **25.8** | `needs_review / table_row_span_too_wide`（旧源图原因） | `verified` | `consistent` | **pending** |
| 6 | `review-formula-attention` | paper-007 | `source-001:b0033`；§3.2.1 | Eq. (1) 缩放点积注意力 | `needs_review / formula_semantics_manual` | `verified` | `consistent` | **pending** |
| 7 | `review-formula-multihead` | paper-009 | `source-001:b0035`；§3.2.2 | 多头注意力两行公式 | `needs_review / formula_semantics_manual` | `verified` | `consistent` | **pending** |
| 8 | `review-formula-positional` | paper-014 | `source-001:b0040`；§3.5 | 正弦/余弦位置编码公式 | `needs_review / formula_semantics_manual` | `verified` | `consistent` | **pending** |

AI 复核者是 `claude-code (AI substantive review; Opus 5)`。它不写 `reviewer`，不写
`reviewed_at`，也不改 `conclusion`；`review-evidence-ai` 的审计行带
`layer=ai_substantive_review` 与 `conclusion_unchanged`。

## 二、P0 实质复核发现：区块指针必须修正

复核发现原记录的部分 `chunk_id` 指向旧版 source map：

- Table 2 的 Transformer 两行在**当前** source map 中位于 `source-001:b0048`，
  原记录写的是 `b0050`。`b0050` 只含 §6.1 正文（41.0）。区块 `b0048` 的 section 标签
  仍是 `5.4 Regularization`，这是切块跨节造成的标签漂移，不是内容错误。
- Table 3 的行数据位于 `source-001:b0051`，原记录写的是 `b0052`（`b0052` 是 §6.2
  正文与 Table 4）。
- 摘要的 41.8 位于 `b0026`；§6.1 正文的 41.0 位于 `b0050`。
- 两条公式的区块（`b0033`、`b0035`）原本正确。

因此，原记录里的程序状态是对旧 source map 计算的结果，**不能当作今天的可复现结论**。
本次只修正指针对应关系与主张范围，没有把任何记录提升为 `verified_structured`。

## 三、来源冲突：41.0 / 41.8 的完整口径

- 本地来源（arXiv 抽取，`source-001`）：**Table 2 行 = 41.8**，**摘要 = 41.8**，
  **§6.1 正文 = 41.0**。冲突存在于原始材料内部，而不是错误转录。
- NeurIPS 2017 会议版（外部核验）：**Table 2 与 §6.1 = 41.0**。
- 课程若描述 Table 2 或 §6.1，应使用 **41.0**；若引用摘要，可以写 **41.8**，但必须在
  同一教学单元披露另一数值和冲突来源。
- 原记录只写了“NeurIPS Table 2/§6.1 = 41.0；arXiv 摘要 = 41.8”，漏掉了
  **本地 arXiv Table 2 也是 41.8**。本次已补全。
- 冲突记录 `conflict_status=source_conflict`；人工结论若为 `pass`，必须
  `conflict_acknowledged=true`，并在 basis 中写明课程采用哪个口径。

## 四、公式研究核验摘要

### Scaled Dot-Product Attention（paper-007）

- 原文：§3.2.1 公式 (1)（`source-001:b0033`）；NeurIPS PDF pp.3–4。
- 转录：`Attention(Q,K,V)=softmax(QK^T/sqrt(d_k))V`。
- 符号：Q/K/V；`d_k` 为 key/query 维度，`d_v` 为 value 维度。
- 维度检查：Q,K 为 `d_k`；V 为 `d_v`；`QK^T` 为 n×n；softmax 每行和为 1；输出加权 V。
- 推导检查：定义式，不是推导；`sqrt(d_k)` 缩放控制点积方差。
- 限制：softmax 权重不是人类语义的重要性；课程是否展示该公式由课程内容审计检查。

### Multi-Head Attention（paper-009）

- 原文：§3.2.2（`source-001:b0035`）；NeurIPS PDF p.4。
- 转录：`MultiHead(Q,K,V)=Concat(head_1,...,head_h)W^O`；`head_i=Attention(QW_i^Q,KW_i^K,VW_i^V)`。
- 符号：`h` 头数；`W_i^Q/W_i^K/W_i^V` 各头投影；`W^O` 输出投影。
- 维度检查：`W_i^Q,W_i^K: d_model×d_k`；`W_i^V: d_model×d_v`；`W^O: h·d_v×d_model`。
- 推导检查：逐头投影、并行注意力、拼接、输出投影；base 模型 `h=8`、`d_k=d_v=d_model/h=64`。
- 限制：课程必须解释设计目的和维度；只展示公式不代表读者理解。

### 位置编码（paper-014，2026-10-24 补充）

- 原文：§3.5（`source-001:b0040`）；NeurIPS PDF p.6。
- 转录：`PE_{(pos,2i)}=sin(pos/10000^{2i/d_model})`；`PE_{(pos,2i+1)}=cos(pos/10000^{2i/d_model})`。
- 符号：`pos` 位置，`i` 维度索引，`d_model` 模型维度；编码维度与词嵌入相同。
- 推导检查：定义式；波长从 2π 到 10000·2π 按几何级数变化。
- 限制：论文只论证该设计“有助于”外推，没有给出超长序列实验；这是作者解释，课程必须如此标注。
- 这一条不在 stage B 的两窗口候选批次中，是 P4 恢复课程时按原文补充的；程序状态保持
  `needs_review`，AI 复核已记录，人工签署仍为 `pending`。

## 五、复核规则

1. **研究核验 ≠ 人工签署。** `research_verification.research_finding=verified` 不能自动把
   `conclusion` 改为 `pass`；`reviewed_by_human` 仍为 `false`。
2. **AI 实质复核 ≠ 人工签署。** `substantive_review` 只能记录 AI 的对照结论；写入命令不
   接受 `reviewer_kind=human`，也不修改 `conclusion`。
3. **程序定位 ≠ 事实核验。** `quote_status=verified_structured` 只表示结构定位；当前表格
   因列语义未证明，实际保持 `needs_review`。
4. **人工签署必须包含**：`reviewer`、`reviewed_at`、`conclusion`、`basis`；缺失任意一项拒绝写入。
5. **冲突必须先披露。** `source_conflict` 记录的 `pass` 需要 `conflict_acknowledged=true`，
   并在 basis 中写明采用 Table 2 还是摘要口径。
6. **不得自动解决冲突。** 不允许按多数来源、模型置信度或最新抓取内容覆盖 41.0/41.8。
7. **局部 ID** `evidence-00x` 只在窗口内唯一；关联台账必须使用
   `source_id + chunk_id + locator`。

## 六、状态汇总

| 项目 | 研究核验 | AI 实质复核 | 人工结论 |
|---|---|---|---|
| Table 2 base 27.3 | verified | consistent | pending |
| Table 2 big EN-DE 28.4 | verified | partial（claim 链接范围） | pending |
| Table 2 big EN-FR 41.0/41.8 | source_conflict | consistent（冲突未裁决） | pending |
| Table 3 big 26.4 | verified | consistent | pending |
| Table 3 base 25.8 | verified | consistent | pending |
| 缩放点积公式 | verified | consistent | pending |
| 多头公式 | verified | consistent | pending |
| 位置编码公式 | verified | consistent | pending |

**P0-B3 保持关闭。** 八条记录的研究核验、AI 实质复核和人工签署仍然分离；课程内容是否
使用这些证据、是否披露冲突，由课程内容审计（`internal/qa/course_content_audit.json`）
单独检查。发布门禁在人工签署完成前拒绝发布。
