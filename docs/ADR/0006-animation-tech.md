# ADR 0006: 动画技术复用 Motion Canvas 适配层

对应 SAD-001 §12 ADR-004。状态：Accepted。

## 背景

仓库已经存在 Motion Canvas 适配层与完整验收链：`motion_canvas.py` 渲染器、
`frame_manifest.py` 帧清单、`encode.py`/`video_qa.py` 编码校验、`visual_qa.py`
自动视觉检查、`visual_baseline.py` 基线、`visual_acceptance.py` 人工验收、
`motion/` 下的 Node 驱动与离线镜像、supply-chain 审计。PRD §6.3 明确要求
"先审计并复用，不能重新实现一套重复的动画引擎"。

## 备选方案

1. Manim 作为主引擎：数学动画强，但与现有 HTML 课件、口播时间轴、离线验收链
   没有集成，且会引入第二套渲染与依赖审计。
2. Remotion：许可证与商业使用需单独评估；当前没有收益证据。
3. 纯 CSS/SVG 手写动画：可控但无法承载逐帧渲染、帧清单与视频交付。
4. 复用 Motion Canvas 适配层（当前），Manim 仅作为经 ADR 批准的补充渲染器。

## 决定

- Motion Canvas 是唯一的逐帧动画生产路径；模板 `title`/`flow`/`compare` 已进入生产注册表。
- 渲染器必须走 `Renderer` 接口：输入 `SceneContract`，输出 `RenderResult` + 帧清单 +
  编码报告，失败不覆盖上一份有效产物。
- 平台限定 Linux（WSL2 或 CI）；Windows 原生不在验收范围内。
- 任何新模板或新引擎都必须通过 `tests/test_motion_canvas*.py` 的同一组契约、
  故障注入与离线测试。

## 后果

- 正面：帧/视频/清单/视觉证据可独立复核；CI 有 `--network none` 证据。
- 负面：需要 Node 24.22.1、Chromium 与 FFmpeg；单场景渲染是主要耗时项
  （P3-B：1 s/10 s/60 s 场景约 7.8/17.4/66.5 s）。
- 监测点：若课程需要 Motion Canvas 难以表达的数学推导，另立 ADR 评估 Manim，
  并补齐同样的离线与帧级验收。

## 证据

已归档的实现日志中的 Motion Canvas P1–P3 行与对应 CI run id；
`tests/test_motion_canvas*.py`、`tests/test_encode.py`、`tests/test_visual_*.py`。

## 回滚

移除 `motion_canvas.renderer` 的生产注册即可退回 HTML 课件；已发布的视频与清单
仍可独立验证。不得删除帧清单与编码报告。
