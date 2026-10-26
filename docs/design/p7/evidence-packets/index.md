# 证据审核包索引

- project: `attention-is-all-you-need`
- review file sha256: `d258c3edcc2ce55c5f1c27ceee8dcfa083e484f3d5a388f921120549054a9758`
- source-001 sha256: `c27a7d19619add42f30e61303d0b7e658a55d783b7353b1eb088e6243ba12c7d`

| review_id | 主张 | 结论 | 审核包 |
|---|---|---|---|
| `review-table2-base-27.3` | Transformer (base) 在 WMT 2014 EN-DE newstest2014 测试集上：BLEU 27.3（Table  | `pending` | [review-table2-base-27.3.json](review-table2-base-27.3.json) |
| `review-table2-big-ende-28.4` | Transformer (big) 在 WMT 2014 EN-DE newstest2014 测试集上：BLEU 28.4（Table 2 | `pending` | [review-table2-big-ende-28.4.json](review-table2-big-ende-28.4.json) |
| `review-table2-big-enfr-conflict` | Transformer (big) EN-FR BLEU 存在未裁决的来源冲突：本地 arXiv 源 Table 2 行 = 41.8、摘要 | `pending` | [review-table2-big-enfr-conflict.json](review-table2-big-enfr-conflict.json) |
| `review-table3-big-26.4` | Table 3 big 行：WMT 2014 EN-DE 开发集 newstest2013 的 BLEU (dev) = 26.4 | `pending` | [review-table3-big-26.4.json](review-table3-big-26.4.json) |
| `review-table3-base-25.8` | Table 3 base 行：WMT 2014 EN-DE 开发集 newstest2013 的 BLEU (dev) = 25.8（同值也 | `pending` | [review-table3-base-25.8.json](review-table3-base-25.8.json) |
| `review-formula-attention` | Scaled Dot-Product Attention（Eq. 1）：Attention(Q,K,V)=softmax(QK^T/√d_k | `pending` | [review-formula-attention.json](review-formula-attention.json) |
| `review-formula-multihead` | Multi-Head Attention（§3.2.2）：MultiHead(Q,K,V)=Concat(head_1,…,head_h)W | `pending` | [review-formula-multihead.json](review-formula-multihead.json) |
| `review-formula-positional` | 位置编码（§3.5）：PE_{(pos,2i)}=sin(pos/10000^{2i/d_model})；PE_{(pos,2i+1)}=c | `pending` | [review-formula-positional.json](review-formula-positional.json) |
| `review-formula-postln` | Post-LN 残差结构：LayerNorm(x + Sublayer(x))；所有子层与嵌入层输出 d_model=512。 | `pending` | [review-formula-postln.json](review-formula-postln.json) |
| `review-formula-variance` | 点积方差：若 q、k 分量独立且均值 0、方差 1，则 Var(q·k)=d_k；缩放后回到 1。 | `pending` | [review-formula-variance.json](review-formula-variance.json) |
| `review-formula-ffn` | 逐位置前馈网络：FFN(x)=max(0, xW_1+b_1)W_2+b_2；输入输出 d_model=512，内层 d_ff=2048。 | `pending` | [review-formula-ffn.json](review-formula-ffn.json) |
| `review-formula-noam` | Noam 学习率：lrate=d_model^{-0.5}·min(step^{-0.5}, step·warmup_steps^{-1.5 | `pending` | [review-formula-noam.json](review-formula-noam.json) |
| `review-table2-rows` | Table 2 对照行：ByteNet 23.75；Deep-Att+PosUnk 39.2；GNMT+RL 24.6/39.92；Conv | `pending` | [review-table2-rows.json](review-table2-rows.json) |
| `review-table3-ablation` | Table 3 在 EN-DE 开发集 newstest2013 的 BLEU (dev)：base 25.8；单头 24.9（低 0.9） | `pending` | [review-table3-ablation.json](review-table3-ablation.json) |
