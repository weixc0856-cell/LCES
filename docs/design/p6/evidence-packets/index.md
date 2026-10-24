# 证据审核包索引

- project: `attention-is-all-you-need`
- review file sha256: `1060f134131716167e99649daf34ebbb8bef8a887d5c99aa9f4667bbbcb0d7ea`
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
