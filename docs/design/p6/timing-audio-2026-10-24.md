# 计时音频说明（P6，2026-10-24）

`timing_evidence.json` 记录的是 **TTS 完整口播**，不是人类讲者录音，也不是学习者完成时长。

| 文件 | 大小 | SHA-256 | 时长 | 用途 |
|---|---|---|---|---|
| `var/timing/narration.wav` | 52,815,222 bytes | `f0cae6195c3bf1609e84badbe9d004aafdbf171be2fad6c2f3833af95b6919a9` | 1197.62 s = 19.96 min | 原始计时证据；`timing_evidence.json` 绑定此哈希 |
| `var/timing/narration.mp3` | 9,581,758 bytes | `20516f37d055c00df20d2f8d12b2b6a210399d36ee589a1f7bf2588660763b2e` | 1197.62 s = 19.96 min | 64 kbps 试听副本，随核验包提供 |

机器可读记录：[`timing-audio-2026-10-24.json`](timing-audio-2026-10-24.json)。

## 复核方法

```powershell
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 .\07-audits\timing-audio\narration.mp3
```

（核验包内路径以包内实际位置为准。）

## 边界

- 人工课程验收的 `--timing-confirmed` 仍必须由真人执行；试听 MP3 可以作为确认依据之一。
- 学习者完成课程的时长必须单独记录，不能使用本音频的 19.96 分钟代替。
- MP3 是转码副本；若需要审计原始字节，使用 WAV 及其哈希。
