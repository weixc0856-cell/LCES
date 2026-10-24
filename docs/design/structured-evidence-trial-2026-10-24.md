# 结构化公式/表格证据验收报告（阶段 B）

日期：2026-10-24  
对象：`projects/attention-is-all-you-need`  
模型：`Qwen3-Coder-30B-A3B-Instruct-Q4_K_M`  
脚本：`scripts/trial-quote-locator.py`  
原始记录：`var/quote-locator-stage-b2/report.md`、`var/structured-evidence-retrial/report.md`

## 0. 正式状态

**阶段 B 正式记录为：结构化证据机制验收通过（受限能力）；语义事实验收待完成；P0-B3 继续关闭。**

- 程序能证明：定位、结构、行/数值同区块、符号规范化匹配、审计字段完整。
- 程序不能证明：列归属、公式代数、论文主张为真。
- **外部研究核验已完成**（NeurIPS 2017 原始 PDF / arXiv 摘要）：7 条记录中 6 条
  `research_finding=verified`，Table 2 的 EN-FR 为 `source_conflict`（NeurIPS 41.0 vs arXiv 摘要 41.8）。
- **人工签署仍全部 pending**：`reviewed_by_human=false`，`conclusion=pending`；
  研究核验不会自动改变人工状态。见
  [`structured-evidence-review-2026-10-24.md`](structured-evidence-review-2026-10-24.md) 与
  `structured-evidence-review-2026-10-24.json`。
- 在人工事实核验完成前，不开发表格/公式解析器，也不放行 P0-B3。

## 1. 结论

| 层次 | 结果 |
|---|---|
| 契约与校验机制 | **PASS**：公式/表格使用独立结构化字段；公式永不自动通过；表格行/跨度只作结构检查 |
| Table 2 数值 | **程序结构检查通过、列语义未验证；研究核验已完成**：base 27.3、big EN-DE 28.4 与原始 PDF 一致；big EN-FR 为 41.0/41.8 来源冲突，不能整体判 pass → `needs_review` |
| Table 3 数值 | **程序结构检查、研究核验已完成**：big 26.4、base 25.8 与 Table 3 一致；程序仍因列语义/跨度过宽保持 `needs_review` |
| 公式 | **研究核验已完成、程序不自动通过**：2 条公式与原文 Eq. (1)/§3.2.2 一致；人工结论仍 pending |
| 表格证据自动通过 | **0**：严格列语义规则生效后，不再仅凭“同行 + 跨度”标记 `verified_structured` |
| 跨区块/无效 ID/公式自动通过 | **0** |
| 是否进入 P0-B3 | **否**。需人工确认列语义与公式；见 `structured-evidence-review-2026-10-24.md` |

## 2. 运行记录

- 2 次调用（A：§3.2.x；B：§6/§6.1/§6.2）
- A：81.1 秒，4,793 输入 / 1,045 输出 tokens
- B：185.7 秒，5,018 输入 / 2,377 输出 tokens
- 合计：266.8 秒，9,811 / 3,422 tokens；全部 `finish_reason=stop`
- SourceMap 与源文本快照已写入 `var/quote-locator-stage-b2/`

## 3. 散文证据

| 窗口 | 候选 | exact | normalized | needs_review | rejected |
|---|---|---|---|---|---|
| A | 1 | 1 | 0 | 0 | 0 |
| B | 6 | 2 | 0 | 4 | 0 |
| 合计 | 7 | 3 | 0 | 4 | 0 |

- A 的注意力函数定义逐字定位成功。
- B 的 “base model surpasses all previous models at a fraction of the cost” 与
  “compatibility function may be beneficial” 两条逐字定位成功。
- 其余 4 条是长句/表格旁叙述，未能在单一区块内逐字定位，进入 `needs_review`。

## 4. 结构化证据

原始运行：6 条结构化候选（2 公式 + 4 表格），4 条表格 `verified_structured`。  
加入行跨度检查（`MAX_TABLE_ROW_SPAN = 120`）后：3 条 `verified_structured`，3 条 `needs_review`。  
进一步加入严格列语义规则后：**0 条 `verified_structured`，6 条 `needs_review`**。行标签与数值同区块
只是结构检查，不等于列语义；表格证据不再仅凭共现/跨度自动通过。

| 类型 | candidate | 状态 | 字段 | 源切片 |
|---|---|---|---|---|
| table | evidence-001 | needs_review | paper-025；Transformer (base model)；BLEU；27.3；base | `Transformer (base model)` / `27.3`（`column_semantics_unverified`） |
| table | evidence-002 | needs_review | paper-025；Transformer (big)；BLEU；41.8；big | `Transformer (big)` / `28.4` / `41.8`（列语义未验证） |
| table | evidence-005 | needs_review | paper-027；big；BLEU；26.4；big | `big` / 6 / 1024 / 4096 / 16 / 0.3 / 300K / 4.33 / 26.4（列语义未验证） |
| table | evidence-004 | needs_review | paper-027；base；BLEU；25.8；base | 跨度超过 120 字符（`table_row_span_too_wide`） |
| formula | evidence-002 | needs_review | paper-007；Attention(Q,K,V)=softmax(QK^T/√d_k)V；Q,K,V,d_k | `3.2.1 ...` 内容区块 |
| formula | evidence-003 | needs_review | paper-009；MultiHead(...)=Concat(...)W^O；Q,K,V,W^O | `3.2.2 ...` 内容区块 |

### 4.1 结构检查通过、但未自动通过

- **Table 2 的 base/big 数值**：row label 与 value 在同一区块、跨度 ≤120 字符，摘录由程序从原文切片；
  但 `column_label=BLEU` 不足以证明 27.3 属 EN-DE、41.8 属 EN-FR，因此保持 `needs_review`。
- **Table 3 的 big 行**：字段与数值行在同一区块、跨度小，结构成立；列位与省略列语义未验证。
- **公式未自动通过**：两条公式都是 `needs_review`；`unicode-math/v1` 规范化只用于匹配和记录，
  不构成代数验证。

### 4.2 收紧前后

- 初始运行 4 条表格 `verified_structured`。
- 加入 `MAX_TABLE_ROW_SPAN=120` 后，`base/25.8`（表题叙述到数值跨度过宽）改为 `needs_review`，剩 3 条。
- 加入严格列语义规则后，剩余 3 条也改为 `needs_review`：程序只能证明“行标签与数值同区块”，
  不能证明列与值的对应关系。
- 这是一次有意的收紧：不允许把字符串共现或跨度小当成完整行列语义验证。

## 5. 仍然存在的语义缺口

1. **列/语言对应没有程序化验证。** Table 2 的 big 行同时包含 28.4（EN-DE）与 41.8（EN-FR）；结构化字段的 `column_label` 是 “BLEU”，不是 “EN-FR”。程序只能证明 41.8 与 big 行同区块，不能证明它对应英法列。必须人工确认。
2. **短行标签仍有歧义。** Table 3 的 “big” 是真实数值行的一部分，但 “base” 也可能出现在表题/叙述中；跨度检查降低了风险，但不能完全消除。
3. **公式符号表示不一致。** `√d_k`、`\sqrt{d_k}`、`d_k` 在源文本中形态不同；一条公式因此报 `formula_symbols_not_found`。这不是数学错误，但需要人工复核；公式始终不自动通过。
4. **Table 3 的列/变体语义**仍未核验；只确认了行内的行标签与数值同区块。

## 6. 验收判定

| 检查项 | 结果 |
|---|---|
| 公式自动通过 | 0（正确） |
| 表格行标签+数值同区块 | 3 条结构成立，1 条跨度过宽；全部因列语义未验证而 `needs_review` |
| 无效 ID / 跨区块拼接通过 | 0 |
| Table 2 base/big 数值可追溯 | 是（程序切片） |
| Table 2 列/语言对应 | 未自动验证，待人工 |
| Table 3 行/列语义 | 行结构部分成立；列语义全部待人工 |
| 公式语义 | 待人工 |
| P0-B3 | 继续关闭 |

## 7. 下一步

1. **人工复核**：7 条全部 `needs_review`，按 [`structured-evidence-review-2026-10-24.md`](structured-evidence-review-2026-10-24.md)
   逐条填写 `reviewer / reviewed_at / conclusion / basis`；不得用程序结构检查或研究核验代替事实签署。
2. **来源冲突**：Table 2 big EN-FR 的 41.0/41.8 必须先拆分并披露；课程描述 Table 2 用 41.0，
   描述摘要只能报告 41.8 并说明冲突。人工 `pass` 需要 `--conflict-ack`。
3. **列语义**：要求 `column_label` 使用表头原文（EN-DE / EN-FR），并在同一区块中核验；或者明确把列对应留给人工。
4. **公式表示**：`unicode-math/v1` 仅用于匹配；原表达式保留，公式语义仍人工复核。
5. **Table 3 口径**：当前跨度检查只接受数值行；表格旁结论句不作为单元格证据。
6. 以上完成后重跑阶段 B；只有关键 Table 2/3 证据和公式复核都通过，才考虑 P0-B3。

## 8. 产物

- 结构化校验：[`src/content_studio/structured_evidence.py`](../src/content_studio/structured_evidence.py)
- 试跑脚本：[`scripts/trial-quote-locator.py`](../../scripts/trial-quote-locator.py)
- 重验脚本：[`scripts/revalidate-structured-evidence.py`](../../scripts/revalidate-structured-evidence.py)
- 原始报告：`var/quote-locator-stage-b2/report.md`
- 跨度收紧重验：`var/structured-evidence-retrial/report.md`
- 严格列语义重验：`var/structured-evidence-retrial-strict/report.md`
- 人工复核清单：[`docs/design/structured-evidence-review-2026-10-24.md`](structured-evidence-review-2026-10-24.md)
- 结构化复核记录：[`docs/design/structured-evidence-review-2026-10-24.json`](structured-evidence-review-2026-10-24.json)
- 复核校验脚本：[`scripts/validate-review-record.py`](../../scripts/validate-review-record.py)
- 复核写回 CLI：[`src/content_studio/structured_review.py`](../src/content_studio/structured_review.py)；`lces review-evidence`
