# Motion Canvas P2.4 计划：P2 全量验收

日期：2026-10-23
基线：`main` @ `f98df74`（P2.3 A–E 全部合并；CI run `39902414995` 五 job 绿）
本文件只做范围、审计与批次划分；实现按批提交，不把多个批次混在一个 PR。

## 1. 范围

P2.4 = **P2 全量验收**，覆盖三件事：

1. **MC-04 自动视觉检查**（每次真实渲染）：不再只验证 PNG 结构/尺寸/解码，
   还要判断画面是否实际有内容（空白帧、退化为纯色背景）。
2. **分模板视觉基线与差分**：同一模板跨构建比较，按模板标定阈值；差异是
   `warn`/`fail` 分开记录，不用一个全局百分比冒充门槛。
3. **可复现性与人工验收留档**：同一环境连续两次构建的字节一致率与视觉差异
   实测记录；人工验收的审阅人、日期、抽看帧与结论写入机器可读文件。

非目标：

- 不新增场景模板或内容能力（多场景、字幕仍在 P2 之外）；
- 不做跨 OS/跨 GPU 的字节级承诺（Level 3 只记录实测）；
- 不把自动指标当作人工验收的替代；
- 不进入 P2.4 之外的 Remotion/Manim 评估。

## 2. 现状审计

| 位置 | 现状 | 缺口 |
|---|---|---|
| `frame_manifest.verify_frame_manifest` | 重新哈希、PNG 结构、尺寸、场景跨度、路径越界、FFmpeg 解码 | 只证明帧“是有效 PNG”，不证明画面有内容 |
| `video_qa.verify_video_against_manifest` | ffprobe 帧数/分辨率/时长/解码 | 同上，纯结构性 |
| `media.probe_media` | 时长、流、关键帧抽检 | 关键帧仅供人工看，无判定 |
| `browser_qa` | 公开 HTML 截图基准（字节比较） | 与视频画面无关 |
| Gate 3 | 动画媒体存在、构建提交标记 | 无视觉项 |
| Gate 4 | 视频解码、音频、字幕时间轴 | 无视觉项 |
| 人工验收 | 发布审批记录了审批人 | 没有“画面已看过”的结构化记录 |

结论：**当前没有任何自动检查能发现“渲染出 300 帧纯黑 PNG 但结构合法”**。
这正是 MC-04 要补的洞。

## 3. MC-04 自动检查设计

### 3.1 采样

- 只分析构建窗口内的帧：跳过开头 1.0 s（淡入）与结尾 0.5 s（淡出/停留）；
- 在该窗口内等距采样最多 9 帧（含首尾）；
- 采样帧解码交给系统 FFmpeg（`-vf scale=160:-1,format=gray -f rawvideo -`），
  不引入 Pillow/OpenCV；采样数固定，子进程开销可控。

### 3.2 指标（在 Python 内计算，可单测）

对每张降采样灰度图（约 160×90）：

| 指标 | 定义 | 用途 |
|---|---|---|
| `background_share` | 直方图众数占比 | 识别纯色画面 |
| `foreground_ratio` | 与众数亮度差 > 24 的像素占比 | 文字/图形是否出现 |
| `edge_ratio` | 水平或垂直梯度 > 40 的像素占比 | 结构是否存在 |

**空白判定**：`foreground_ratio < 0.002` 且 `edge_ratio < 0.001`。
阈值是初始标定值，按模板记录在 `visual_profiles.py`，不是统一生产门槛；
误报/漏报与人工复核结果写入验收记录。

**例外**：模板声明的静态卡（纯色标题卡）通过 profile 的
`allow_blank=True` 放行；淡入淡出由采样窗口排除，不靠放宽阈值。

### 3.3 集成与证据

- 渲染适配器在 FrameManifest 校验通过后、编码前执行；
- 任一采样帧判定为空 → `qa_failed`，不编码、不发布，旧视频保持不变；
- 结果写入 `build/motion/<id>/visual_qa.json`；生产构建同时写
  `internal/qa/visual_qa.json`，进入 `visual_assets.json` 的产物哈希；
- 报告记录：采样帧索引、每帧三项指标、所用 profile 与阈值、判定结果。

## 4. 分模板基线与差分（P2.4-B）

- 基线来源：同一模板、同一工具链、同一分辨率下的一次已验收渲染；
- 基线存放于 `internal/qa/visual_baselines/<template>-<width>x<height>.json`
  （只存采样帧指标与帧哈希，不存整段视频）；
- 构建时若存在匹配基线：逐采样帧比较指标偏差与灰度图差分比例；
  超阈值记 `warn`（不阻断），并写入报告；无基线记 `NOT_RUN`；
- 新模板、Node/驱动/FFmpeg 版本变化时，基线必须重新建立并记录原因。

## 5. 可复现性实测（P2.4-C）

在同一环境连续渲染同一场景两次：

1. 逐帧 SHA-256 一致率（Level 3 字节级）；
2. 采样帧的视觉差分（像素变化比例）；
3. 记录环境（Node、Chromium、FFmpeg、lockfile 哈希）与两次构建的 `build_id`。

结论只对被测环境有效；不写成跨环境承诺。CI 增加一个手动触发或独立 job
执行两次渲染并上传报告，避免让每次 PR 都付双倍渲染成本。

## 6. 人工验收记录（P2.4-D）

- 新增 `lces accept-visual`：参数为项目、模板、审阅人、抽看帧路径/索引、
  结论（`pass`/`fail`）、备注；写入 `internal/qa/visual_acceptance.json`；
- 自动检查只能把资产标为 `failed`，不能把人工验收标为 `pass`；
- 发布门禁：使用新模板或工具链版本变化后的首次发布必须有对应的
  `visual_acceptance` 记录；其余情况按抽样要求记录（先告警，再决定阻断）。

## 7. 批次与完成条件

| 批次 | 内容 | 完成条件 |
|---|---|---|
| P2.4-A 自动视觉 QA | 采样、三项指标、profile、`qa_failed`、`visual_qa.json` | 纯黑/纯色帧被拒绝；正常 `title`/`flow`/`compare` 通过；真实渲染回归 |
| P2.4-B 基线与差分 | 基线记录、匹配规则、`warn` 报告 | 有基线/无基线/NOT_RUN 三种路径；不误报阻断 |
| P2.4-C 可复现性实测 | 双构建 job、字节一致率与视觉差分报告 | 报告可独立复核；结论限定环境 |
| P2.4-D 人工验收与门禁 | `accept-visual`、发布门禁、全局 P1/P2 门禁复核 | 记录可追溯；五个 CI job 绿；P2 全量验收表收口 |

每批独立提交、独立 CI 证据；A 批先行。

## 8. 验收门禁（草案）

| ID | 验收项 | 说明 |
|---|---|---|
| P2.4-GATE-01 | 空白/纯色帧被自动拒绝 | 真实构建负向用例 + 单测 |
| P2.4-GATE-02 | 正常模板不误报 | 真实 `title`/`flow`/`compare` 渲染 |
| P2.4-GATE-03 | 视觉证据可追溯 | `visual_qa.json` 进入资产哈希与 Gate 4 |
| P2.4-GATE-04 | 基线与差分按模板记录 | warn/NOT_RUN 语义正确 |
| P2.4-GATE-05 | 可复现性实测留档 | 双构建报告 + 环境记录 |
| P2.4-GATE-06 | 人工验收不可被自动替代 | 记录 schema + 门禁测试 |
| P2.4-GATE-07 | 全量回归 | P1/P2.1/P2.2/P2.3 测试与五 job |

## 9. P2.4-A 实施记录（本机；CI 待执行）

**实现**

- `src/content_studio/visual_qa.py`：采样窗口（跳过首 1.0 s、尾 0.5 s，最多 9 帧）、
  灰度三项指标（背景众数占比、前景比例、边缘比例）、按模板 profile；
  空白判定为 `foreground < 0.002` 且 `edge < 0.001`。
- 适配器在 FrameManifest 校验后、编码前执行；任一采样帧判空 → `qa_failed`，
  不编码、不替换旧视频。报告写入 `build/motion/<id>/visual_qa.json`，生产构建
  同时写 `internal/qa/visual_qa.json` 并进入 `visual_assets.json` 的产物哈希。
- 测试替身通过显式 `visual_check=False` 关闭检查；生产与真实 E2E 始终开启。
- `collect-motion-evidence.py` 现在把 `visual_qa.json` 收入证据 artifact。

**本机验证**

- `uv run pytest` → **401 passed, 39 skipped**；ruff / format / mypy 全绿。
- 新增测试：`tests/test_visual_qa.py` 11 项（纯色/有内容/短缓冲/采样窗口/
  profile/解码失败/序列化），`tests/test_motion_canvas.py` 2 项集成
  （空白报告阻断且保留旧视频；通过时写入 QA 证据）。
- 离线镜像 `sha256:9eb62bd0…53ac`，`--network none`：**13 passed / 0 failed**
  （25.9 s）；负控制失败；证据审计 0 findings。
- 真实 title 渲染的采样帧全部 `pass`：9 帧（30…284），
  `foreground_ratio` 1.69–1.76%，`edge_ratio` 1.88–2.02%，
  对比阈值 0.2% / 0.1%，余量约 8–19 倍。阈值仍按模板标定，B 批再用基线复核。

**A 批 CI 证据（run `39910802614`，commit `9c3d89e`）**：五个 job 全绿。

- `motion-canvas-p1`：JUnit 19/0/0（66.1 s）；`motion-canvas-offline`：
  JUnit 13/0/0（35.4 s）。
- 真实渲染的采样指标（阈值 0.2% / 0.1%）：
  - `title` 1920×1080：前景 1.61–1.76%，边缘 1.88–2.04%；
  - `title` 640×360：前景约 7.5%，边缘约 9.6–9.8%；
  - `flow` 640×360：前景 14.2%，边缘 4.6%；
  - `compare` 640×360：前景 9.1%，边缘 11.0%。
  全部 `pass`，没有误报。
- artifact 已下载到 `var/ci-run-a/`（git 忽略）并独立复核；`visual_qa.json`
  同时出现在构建目录与 `internal/qa` 证据中。
- PR #23 合并后，`main` @ `d0ae97f` 的 CI run `39910895396` 五 job 全绿。
## 10. P2.4-B 实施记录（本机 + CI）

**实现**

- `src/content_studio/visual_baseline.py`：
  - 基线路径按模板、画布尺寸与帧率区分：
    `internal/qa/visual_baselines/<template>-<w>x<h>-<fps_num>_<fps_den>.json`；
  - 基线保存采样帧索引、前景/边缘指标与逐帧 SHA-256，不保存像素；
  - `compare_baseline` 返回 `missing` / `matched` / `drifted`；
    指标偏差超过 0.01（绝对比例）或采样索引变化记 `drifted` 并给出警告；
    只有字节哈希不同、指标一致时为 `matched` 且 `byte_identical=false`；
  - 漂移只告警，不阻断构建。
- 渲染集成：视觉检查通过且存在项目目录时比较基线，把结果写入
  `visual_qa.json` 的 `baseline` 块，并在 diagnostics 记录警告。
- 新增 `lces visual-baseline <project> --template <t> [--note ...]`：
  把当前通过视觉检查的构建登记为基线；拒绝未知模板、失败报告或缺失证据。

**本机验证**

- `uv run pytest` → **412 passed, 39 skipped**；ruff / format / mypy 全绿。
- 新增测试：`tests/test_visual_baseline.py` 9 项（路径、缺失、匹配、字节漂移、
  指标漂移、采样索引变化、失败报告拒绝、CLI 写入、未知模板）；
  `tests/test_motion_canvas.py` 2 项集成（匹配被记录；漂移告警但仍发布）。
- 离线门禁不受影响：没有基线文件时报告 `missing`。

**B 批 CI 证据（run `39911682016`）**：五个 job 全绿；
`motion-canvas-p1` JUnit 19/0/0、`motion-canvas-offline` 13/0/0。
真实渲染的 `visual_qa.json` 中
`baseline.status = missing`（该构建未登记基线），语义正确。
artifact 已下载到 `var/ci-run-b/`（git 忽略）并复核。

## 11. P2.4-C 实施记录（本机；实测 job 待触发）

**实现**

- `src/content_studio/reproducibility.py`：逐帧 SHA-256 一致率、采样视觉指标
  最大偏差、环境信息（LCES/Python/Node/Motion Canvas/Playwright/FFmpeg 与
  `package-lock.json` 哈希）；报告写明“仅限同一环境”，不作跨 OS 承诺。
- `tests/test_motion_canvas_reproducibility.py`：只有 `LCES_MC_REPRO=1` 时运行；
  同一场景渲染两次（不同 `build_id`），比较 FrameManifest 与 `visual_qa.json`，
  写出 `LCES_REPRO_OUT` 指定的报告。**不断言字节一致**，只记录实测值。
- CI：`workflow_dispatch` 新增 `reproducibility` 布尔输入；`motion-canvas-p1`
  job 在该输入为真时多跑一次双渲染，并把报告纳入 `motion-canvas-p1-evidence`。
  普通 PR 不付双倍渲染成本。
- `scripts/ci-local.sh render` 支持 `LCES_MC_REPRO=1` 时追加同一测量。

**本机验证**

- 单元测试 6 项：一致/不一致/零帧比较、视觉偏差、状态不一致、报告字段。
- 真实双渲染只能在 Linux + 固定工具链执行；本机 Windows 跳过。

**未执行**：实测 job。C 批在真实双渲染报告产生前不得记为 PASS。
