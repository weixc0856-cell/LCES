# 视觉审核表（2026-10-24）

状态：**待人工审核**。10 个视口均通过自动化加载/JS/资源/溢出检查；截图与旧基线不同，未自动批准新基线。

| 页面 | 视口 | 截图 | SHA-256（前 12） | 自动化 | 人工结论 |
|---|---|---|---|---|---|
| slides | desktop | `internal/qa/screenshots/slides-desktop.png` | `3e66830097bf` | load/JS/资源/溢出 pass；基线 warn | **pending** |
| slides | mobile | `internal/qa/screenshots/slides-mobile.png` | `aa2165793bb4` | load/JS/资源/溢出 pass；基线 warn | **pending** |
| slides | hd_16_9 | `internal/qa/screenshots/slides-hd_16_9.png` | `758046a50d20` | load/JS/资源/溢出 pass；基线 warn | **pending** |
| slides | qhd_16_9 | `internal/qa/screenshots/slides-qhd_16_9.png` | `e5b63dd3da5c` | load/JS/资源/溢出 pass；基线 warn | **pending** |
| slides | uhd_16_9 | `internal/qa/screenshots/slides-uhd_16_9.png` | `e9b811ffb30b` | load/JS/资源/溢出 pass；基线 warn | **pending** |
| reading | desktop | `internal/qa/screenshots/reading-desktop.png` | `1fed76a06f72` | load/JS/资源/溢出 pass；基线 warn | **pending** |
| reading | mobile | `internal/qa/screenshots/reading-mobile.png` | `70977b71cc04` | load/JS/资源/溢出 pass；基线 warn | **pending** |
| reading | hd_16_9 | `internal/qa/screenshots/reading-hd_16_9.png` | `fe6a50221107` | load/JS/资源/溢出 pass；基线 warn | **pending** |
| reading | qhd_16_9 | `internal/qa/screenshots/reading-qhd_16_9.png` | `f70c25696c6e` | load/JS/资源/溢出 pass；基线 warn | **pending** |
| reading | uhd_16_9 | `internal/qa/screenshots/reading-uhd_16_9.png` | `7c413bf58d93` | load/JS/资源/溢出 pass；基线 warn | **pending** |

审核者需确认：公式可读性、表格/代码换行、引用展示、移动端布局，并在确认后更新基线。
