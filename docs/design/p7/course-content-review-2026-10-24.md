# P7 课程内容审读（14 节）

日期：2026-10-24  
对象：`projects/attention-is-all-you-need`，课程契约 `1.1`（draft）  
方法：逐节阅读 `content/public_content.json` 与 `content/reading_edition.json`，对照
`internal/claims.json`、`internal/evidence_ledger.csv` 与原文 `internal/sources/source-001.txt`；
以 `lces audit-course` 的确定性结果作为数值/公式/渲染的底稿。

> 本文件是工程与研究侧的审读记录，不是人工签署。所有 `conclusion` 仍为 `pending`。

## 1. 逐节结论

| 节 | 主题 | 证据覆盖 | 主要保留意见 |
|---|---|---|---|
| slide-001 | 问题与代价 | claim-001/004/018/023 | “并行收益取决于硬件”是课程解释，已标注 |
| slide-002 | Post-LN 与三处注意力路由 | claim-004/005/007/008/015/033 | Post-LN 顺序由 guard 锁定；掩码的 −∞ 实现细节属标准做法 |
| slide-003 | 缩放点积注意力与方差 | claim-006/034，证据 evidence-048 | 方差推导按脚注展开，课程标注为推导而非新结论 |
| slide-004 | 多头注意力 | claim-006/007 | “多头更好”已限定为 Table 3 的经验结果 |
| slide-005 | 位置编码与旋转矩阵 | claim-009/035 | 旋转矩阵是课程推导，已在正文明确说明 |
| slide-006 | FFN、嵌入与权重共享 | claim-008/016 | √d_model 的量纲解释是课程解释 |
| slide-007 | 复杂度与 Table 1 | claim-010–013/026 | n < d 条件由 guard 锁定 |
| slide-008 | 训练配置与 Noam | claim-024/025/030/031/032/036 | 标签平滑的 PPL/BLEU 取舍有 Table 3 支撑 |
| slide-009 | Table 2 与成本 | claim-002/003/018/019/027/030 | 41.0/41.8 并列披露，未裁决 |
| slide-010 | Table 3 消融 | claim-019/028/036 | **(C) 行按原表列序转录，列语义需人工确认** |
| slide-011 | Table 4 句法分析 | claim-020/021/029 | 单一数据集、单一任务的边界已写明 |
| slide-012 | 来源口径 | claim-001/003/018/019 | 版本与位置逐项列出 |
| slide-013 | 局限与成本 | claim-014–018/020/021/030 | 成本列是训练 FLOPs，不是推理成本 |
| slide-014 | 总结与检查 | 综合 | 检查题为自测，不替代学习者试测 |

## 2. P6 遗留问题的处理状态

| 编号 | P6 结论 | P7 状态 | 证据 |
|---|---|---|---|
| F-01 | 口播超参数无证据（major） | **已修复** | evidence-035/036/037、claim-024/025；新增 `number_coverage` 门禁扫描口播数字 |
| F-02 | 幻灯片缺 512/2048（minor） | **已修复** | slide-002 明确写出；claim-008/033 绑定 |
| F-03 | 位置编码“无梯度”表述无依据（minor） | **已修复** | slide-005 改为作者假设 + Table 3 (E)；guard `relative-position-hypothesis` |
| F-04 | 未写 arXiv v7（minor） | **已修复** | 课程统一写 `arXiv:1706.03762v7`；Table 2 标题带版本 |
| F-05 | 部分检查答案过短（advisory） | 改善 | 14 个检查均含 rationale；仍属人工判断 |
| F-06 | TTS 时长不是学习者时长（验收项） | **未解决** | `05-learner-trial` 仍未执行；不得用 TTS 代替 |
| F-07 | 截图与旧基线不同（advisory） | **预期变化** | 新 deck 使 10 张截图全部变化；新基线待人工确认 |

## 3. 新增的实质性风险

1. **Table 3 的 (C) 行**：原文表格列多、行内换行，`N` / `d_model` / `d_ff` 三组变体按列序转录。
   数值本身来自 `source-001:b0051`，但“哪一列对应哪个变体”需要人工逐格确认；这是本轮最需要人读的地方。
2. **计时期望失效**：口播稿已改写，`timing_evidence.json` 对应的音频与脚本哈希不再匹配。
   Gate B 因此返回 `blocked`（`timing_matches_script`），这是正确状态，不是缺陷；重新录制后再验收。
3. **阅读版与幻灯片共享区块**：阅读版 = 幻灯片区块 + 深度补充，因此部分段落重复。
   这是“阅读版必须更详细”的代价；若产品要求零重复，应改为只写阅读版正文。
4. **SVG 是课程重绘**：`architecture.svg` 与 `attention-flow.svg` 按论文 Figure 1/2 的结构重绘，
   不是原文图片；图中文字与配色由课程维护。

## 4. 未验证项（不得写成结论）

- 长序列外推：论文未做实验，课程只保留“作者假设”。
- 跨任务泛化：仅 WMT 翻译与 WSJ 句法分析。
- Table 3 列语义：(C) 行待人工确认。
- 学习者效果：没有真实学习者数据；TTS 时长只证明朗读长度。
- 视觉可读性：自动检查通过不等于人工视觉确认。
