# 来源哈希口径（P7）

同一份来源在链路上有三个不同的字节对象。核验包与审计报告分别引用它们；把三者混用会造成“信源同一性”置疑。

| 字段 | 字节对象 | 当前值 |
|---|---|---|
| `raw_archive_sha256` | 下载/归档的原始文件字节（`input/source-001-attention-is-all-you-need.html`） | `fe1288e9c6f8322156429ab44bf5ced203155f8ecc7ea9fe6cfd125872c72a3b` |
| `extracted_txt_sha256` | 抽取后的 UTF-8 文本（`internal/sources/source-001.txt`） | `c27a7d19619add42f30e61303d0b7e658a55d783b7353b1eb088e6243ba12c7d` |
| `normalized_locator_sha256` | 文本经 `normalize_quote`（引号、破折号、不可见字符、空白、大小写）后的匹配视图 | `ef336e70ed1409b9e2c6b7bf746d697f4af91fd9186fcd16ecac9fb9de6a6f11` |

## 重建规则

1. 原始归档：`sha256sum input/source-001-attention-is-all-you-need.html`。
2. 抽取文本：`lces ingest` 用 HTML 解析器把每个 `<math>` 子树折叠成一个可读的内联 token（优先 TeX annotation，否则用空格连接子节点），再写 `internal/sources/source-001.txt`；对该文件取字节哈希。
3. 规范化视图：对第 2 步的文本调用 `content_studio.utils.normalize_quote`，再取 UTF-8 字节哈希。引用定位器只在这个视图上比较。

`source_map.json` 同时保留旧字段 `sha256`（历史含义为原始归档字节），新代码写入时四个字段一致可查。

## 未执行的迁移

P7 修复了抽取器，但**没有**原地重写 `source-001.txt`。原因：重写会改变全部 chunk 偏移，而现有 37 条 P6 证据中只有 4 条记录了 chunk id，其余 33 条无法机械重锚；静默重写会削弱而非加强可追溯性。迁移需要单独执行并逐条人工复核，已列入未完成项。
