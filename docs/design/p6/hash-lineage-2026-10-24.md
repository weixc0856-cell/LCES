# 哈希口径说明（P6，2026-10-24）

本文件解释核验包中出现的三类 SHA-256，避免把“原始 HTML / 抽取文本 / 规范化文本”混为一谈。

| 对象 | 位置 | SHA-256 | 说明 |
|---|---|---|---|
| 原始输入 HTML | `projects/attention-is-all-you-need/input/source-001-attention-is-all-you-need.html` | `fe1288e9c6f8322156429ab44bf5ced203155f8ecc7ea9fe6cfd125872c72a3b` | 下载/保存的原始 HTML 字节；source registry 记录同一哈希 |
| 抽取文本 | `internal/sources/source-001.txt` | `c27a7d19619add42f30e61303d0b7e658a55d783b7353b1eb088e6243ba12c7d` | UTF-8 文本文件字节；台账、locator、课程审计都基于它 |
| 证据包 `source_text_sha256` | `02-evidence/*.json` | `c27a7d19619add42f30e61303d0b7e658a55d783b7353b1eb088e6243ba12c7d` | **P6 修订后与抽取文本字节哈希一致**；修复前误用了解码/换行规范化后的字符串哈希 |
| 证据包 `excerpt_sha256` | `02-evidence/*.json` | 每个包不同 | 摘录字符串按 UTF-8 编码后的哈希；摘录本身是从抽取文本切出的原始切片 |
| 构建 HTML | `build/slides/index.html`、`build/reading_edition.html` | `05f6a1068b61…`、`78934d5891b7…` | 构建产物的文件字节哈希；Gate B 的 `content_version` 包含它们 |
| 复核记录 | `internal/qa/structured_evidence_review.json` | `1060f13413171616…` | 8 条记录的文件字节哈希 |
| 计时 WAV | `var/timing/narration.wav` | `f0cae6195c3bf1609e84badbe9d004aafdbf171be2fad6c2f3833af95b6919a9` | TTS 原始音频；`timing_evidence.json` 绑定此哈希 |
| 计时 MP3（试听副本） | `var/timing/narration.mp3` | `20516f37d055c00df20d2f8d12b2b6a210399d36ee589a1f7bf2588660763b2e` | 64 kbps 试听副本；时长与 WAV 相同（1197.62 秒），不作为原始计时证据 |

## 规范化规则

- `utils.normalize_quote()` 只用于**引文匹配**（大小写、空白、引号/破折号等排版差异），
  **不用于**任何存储哈希。
- 文件哈希一律对文件字节计算；不经过换行转换、Unicode 规范化或 JSON 重新序列化。
- 证据包摘录是从抽取文本按字符位置切出的原始切片；切片内的数学/引文痕迹保留。

## 重建命令

```powershell
Get-FileHash .\projects\attention-is-all-you-need\input\source-001-attention-is-all-you-need.html -Algorithm SHA256
Get-FileHash .\projects\attention-is-all-you-need\internal\sources\source-001.txt -Algorithm SHA256
Get-FileHash .\projects\attention-is-all-you-need\var\timing\narration.wav -Algorithm SHA256
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 .\projects\attention-is-all-you-need\var\timing\narration.wav
```

如果重建出的文本哈希与 `c27a7d19…` 不同，说明来源文本被改动，旧 locator、审计和审核包都需要重做。
