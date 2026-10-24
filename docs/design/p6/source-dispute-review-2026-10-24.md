# 来源级争议与核心主张核查（P6-B，2026-10-24）

对象：`projects/attention-is-all-you-need`  
本地来源：`internal/sources/source-001.txt`（arXiv HTML，`https://arxiv.org/html/1706.03762v7`，SHA-256
`fe1288e9…72a3b`）  
外部对照：既有研究核验记录引用 NeurIPS 2017 PDF（Table 2、§6.1、§3.5）；**本轮没有重新下载 PDF**。

> 状态含义：**来源已核对** = 本地原文与记录逐条对照过；**待人工裁决** = 需要真实审核者决定；
> **未解决** = 当前材料不足以确认。来源核对不是人工签署，也不自动改变任何 `conclusion`。

## B1. EN–FR Big：41.0 与 41.8

### 来源事实

- 本地 arXiv v7 **Table 2 行**（`source-001:b0048`）：
  `Transformer (big) / 28.4 / 41.8 / 2.3⋅10^19`。EN-FR 列是 **41.8**。
- 本地 arXiv v7 **摘要**（`source-001:b0026`）：
  “On the WMT 2014 English-to-French translation task, our model establishes a new single-model
  state-of-the-art BLEU score of **41.8** after training for 3.5 days on eight GPUs…”。
- 本地 arXiv v7 **§6.1 正文**（`source-001:b0050`）：
  “On the WMT 2014 English-to-French translation task, our big model achieves a BLEU score of
  **41.0**, outperforming all of the previously published single models…”。
- 既有研究核验记录（`review-table2-big-enfr-conflict.research_verification`）：
  NeurIPS 2017 proceedings Table 2 与 §6.1 为 **41.0**，source locator “Table 2, p.7; §6.1”。

### 课程表述

- `slide-007` 表格两行：`41.0`（§6.1 / NeurIPS Table 2）与 `41.8`（arXiv Table 2 / 摘要）。
- `slide-007` warning：“41.0 与 41.8 并存，不是四舍五入……采用 41.0 作为 Table 2 口径，
  同时保留 arXiv Table 2 与摘要的 41.8；不取平均、不静默择一”。
- 阅读版与口播稿使用同一口径。

### 判断依据

冲突是真实存在的，且**同一份 arXiv v7 内部**（Table 2 与 §6.1）就不一致，不是课程转录错误。
课程没有把两个数值合并，也没有把 41.8 写成 §6.1 的结果。

### 建议修订

1. 课程与审核包把“本地 arXiv 版本”明确写成 **arXiv:1706.03762v7**，避免读者误以为任意 arXiv 版本。
2. 在 conflict 记录的 `basis` 中写清“Table 2 口径 = 41.0；arXiv v7 Table 2/摘要 = 41.8”。
3. 不修改课程中的两个数值；不增加“哪个是作者真实意图”的断言。

### 尚待人工决定

- 审核者是否接受“课程采用 41.0、披露 41.8”的口径。
- 是否独立复核 NeurIPS PDF（本轮未重新下载）。
- 冲突记录的 `pass` 必须由真实审核者使用 `--conflict-ack` 签署。

**状态：来源已核对；待人工裁决。**

## B2. claim-001 与 claim-023：取代循环层 vs 摒弃卷积

### 来源事实

- `claim-001`（收窄后）：“完全基于注意力机制，取代了编码器—解码器架构中常见的循环层。”
  证据 `evidence-033`（§7 Conclusion）：
  “In this work, we presented the Transformer, the first sequence transduction model based
  entirely on attention, replacing the recurrent layers most commonly used in encoder-decoder
  architectures with multi-headed self-attention.”
- `claim-023`（拆分后）：“完全摒弃卷积操作。”
  证据 `evidence-034`（`source-001:b0026`，摘要）：
  “We propose a new simple network architecture, the Transformer, based solely on attention
  mechanisms, dispensing with recurrence and convolutions entirely.”

### 课程表述

- `slide-001`：“完全基于注意力机制……不再使用循环或卷积。”
- `slide-002`：编码器/解码器子层均为注意力与前馈网络，没有卷积层。

### 判断依据

拆分为两条后，各自都有直接引文支持；“entirely / solely” 对应“完全”，没有超出原文。
此前把“取代循环层”和“摒弃卷积”绑在一条上、只用循环层引文，确实属于部分支持。

### 建议修订

- 保持拆分；在汇总表与课程口径中不要把两条重新合并成一条“完全基于注意力”。
- 两条主张仍需人工核验；`key_claims_have_evidence=pass` 只表示结构上有证据。

### 尚待人工决定

两条主张的 `verification_status` 由真实审核者确认；AI 复核不能替代。

**状态：来源已核对；待人工核验。**

## B3. 三个公式

### 来源事实与课程表述

| 公式 | 来源 | 课程转录 | 检查 |
|---|---|---|---|
| 缩放点积注意力 | §3.2.1 Eq. (1)，`b0033`：`Attention(Q,K,V)=softmax(QK^T/√d_k)V` | `slide-003` LaTeX | `latex-tokens/v1` 规范化后一致；解释覆盖 Q/K/V、d_k/d_v、缩放、softmax 行归一化、输出 n×d_v |
| 多头注意力 | §3.2.2，`b0035`：`MultiHead=Concat(head_1,…,head_h)W^O`；`head_i=Attention(QW_i^Q,KW_i^K,VW_i^V)` | `slide-004` LaTeX | 规范化后一致；解释覆盖投影维度、拼接、W^O、h=8、d_k=d_v=64 |
| 位置编码 | §3.5，`b0040`：`PE_{(pos,2i)}=sin(pos/10000^{2i/d_model})`；奇数维 `cos` | `slide-005` LaTeX | 规范化后一致；解释覆盖偶数/奇数维、几何级数、外推限制 |

### 判断依据

三条转录与原文逐项一致；课程解释没有把 softmax 权重说成人类重要性，也没有把位置编码的
外推说成已由实验证明。多头的“单头平均会抑制”被表述为论文的机制说明，而不是普遍实验结论。

### 建议修订

- 无需修改公式。位置编码可继续使用 `PE_{(pos,2i)}` 的下标写法。
- 建议在课程脚注保留“公式转录与语义复核分开”的说明。

### 尚待人工决定

三条公式记录的 `conclusion` 仍为 `pending`，需要真实审核者签署。

**状态：来源已核对；待人工签署。**

## B4. Table 2 / Table 3 的行列、模型与数据集

### 来源事实

- Table 2（`b0048`）：`Transformer (base model) / 27.3 / 38.1 / 3.3⋅10^18`；
  `Transformer (big) / 28.4 / 41.8 / 2.3⋅10^19`。列为 EN-DE / EN-FR BLEU 与训练成本；
  表题说明测试集是 newstest2014。
- §6.1（`b0050`）：big EN-DE 28.4；big EN-FR 41.0；3.5 天、8 块 P100。
- Table 3（`b0051`）：base 行 25.8、big 行 26.4；表注说明指标是 EN-DE 开发集
  newstest2013 的 BLEU (dev)；未列出的取值继承 base 行；解码用 beam search，无 checkpoint averaging。

### 课程表述

- `slide-007`：base 27.3、big 28.4（EN-DE/newstest2014）；EN-FR 41.0/41.8 冲突；
  Table 3 base 25.8、big 26.4，明确 `BLEU (dev)`、EN-DE、newstest2013。
- 课程没有把 Table 3 写成测试集结果，也没有把 41.8 写成 §6.1 的结果。

### 判断依据

模型规模、语言方向、数据集和指标均匹配；41.0/41.8 的版本冲突已单独处理。
程序仍将 Table 2/3 标记为 `column_semantics_unverified`，因此最终确认需要人工看原表。

### 建议修订

- 建议在 Table 2 表题中写明 newstest2014（课程正文已写，表题可再明确）。
- 建议在 Table 3 表题中写明“BLEU (dev), newstest2013”（正文已写）。

### 尚待人工决定

Table 2/3 的行列语义与脚注由真实审核者确认；冲突项按 B1 处理。

**状态：来源已核对；待人工确认列语义。**

## B5. 课程中的其他事实性表述

| 表述 | 来源事实 | 课程位置 | 判断 |
|---|---|---|---|
| 训练成本是当时最佳模型的一小部分 | 摘要“a small fraction of the training costs of the best models”；§6.1 base 模型“at a fraction of the training cost” | slide-001、口播 | 有来源，表述限定为“论文摘要/§6.1 口径”，可接受 |
| 3.5 天、8 块 P100 | §6.1（`b0050`）；evidence-026 | slide-007、口播 | 有证据行 |
| 标签平滑 0.1、dropout 0.1/0.3 | §5.4 Regularization（`b0047`）、§6.1（`b0050`）；evidence-023 | 口播 | 有部分证据行 |
| Adam beta1=0.9、beta2=0.98、eps=1e-9、warmup 4000、EN-FR P_drop=0.1 | §5.3 Optimizer、§6.1（`b0050`）存在原文；warmup 位于 `b0045`/`b0046` 附近（section 标签有漂移），但**证据台账没有对应行** | 口播 | **证据链缺口**：课程说了台账未覆盖的具体数值 |
| 句法分析 92.7 F1；Dyer 93.3 | Table 4；evidence-031、evidence-032 | slide-005/008、口播 | 有证据行；“接近”表述准确 |

### 建议修订

- 为 §5.3 的优化器设置与 EN-FR 的 `P_drop=0.1` 增加真实证据行（从原文切片）和对应 claim；
  或从口播稿删除这些具体数值，避免“课程有、台账无”的缺口。
- 本轮不代填证据；这是 P6-C 的 F-01。

### 尚待人工决定

是否保留这些超参数细节；若保留，先补证据链再由人工核验。

**状态：已发现缺口；待整改与人工核验。**

## 总结

| 项目 | 来源核对 | 人工裁决/签署 |
|---|---|---|
| 41.0 / 41.8 冲突 | 完成 | **pending** |
| claim-001 / claim-023 | 完成 | **pending** |
| 三个公式 | 完成 | **pending** |
| Table 2 / Table 3 行列 | 本地原文核对完成 | **pending**（列语义） |
| 优化器/EN-FR dropout 细节 | **证据链缺口** | 待整改 |

本轮没有裁决任何冲突，没有修改任何 `conclusion`，也没有把 AI 核对写成人工签署。
