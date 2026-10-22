# Motion Canvas 接入技术设计与验收规格

状态（2026-10-22 第二轮评审后）：

- 架构方向：**通过**
- P0 可行性验证：**GO（仅 Linux，2026-10-22）**，run `39750119050`
  （离线渲染 + 契约测试 10/10）；详见 `docs/design/motion-canvas-spike.md`
- P1 运行范围：**Linux only**，本地使用 WSL2（Ubuntu 24.04）；Windows 原生
  在入口显式拒绝（`unsupported_platform`），需新的 P0 才能纳入
- 环境所有权：WSL / Node / 浏览器 / FFmpeg 由用户维护；LCES 不自动安装。
  P1 只做版本检查，不符即 `environment_unavailable`
- 正式编码 / 注册表接入：P1 可在 Linux 范围开始；生产 `renderers/` 仍暂缓到
  P1 通过相同门禁
- Remotion：**暂不启动**
- Graphviz 真实渲染：**CI 已验收（2.43.0，14/14）**；本机 Windows 16.1.0
  安装受策略限制，待人工执行，见 `docs/design/graphviz-acceptance.md`

本文只做技术设计与验收定义，不包含实现代码。

## 0. 整改追踪

| 编号 | 内容 | 状态 |
|---|---|---|
| A1 | 替换 MC-01 反例；补零帧与整数溢出测试 | **本轮已修订** |
| A2 | 冻结时间轴与转场语义 | **本轮已修订** |
| A3 | P0 决策门槛（GO / CONDITIONAL_GO / NO_GO） | **本轮已修订** |
| A4 | 验证真实驱动协议（官方 headless 或 UI 就绪/完成信号） | P0 实验 |
| A5 | 断网渲染与负控制证据 | P0 实验 |
| A6 | 1080p/30fps/10s 资源基线 | P0 实验 |
| A7 | FrameManifest | **本轮已定义**，P1 实现 |
| A8 | 取消/失败产物隔离与原子发布 | **本轮已定义**，P1 实现 |
| A9 | 三级可复现性与视觉 QA 修订 | **本轮已修订** |
| A10 | Registry 接口契约与完成判定统一 | **本轮已定义**，P1 对齐 |
| A11 | 供应链、浏览器身份、路径与子进程隔离 | 部分本轮补充，P2 闭环 |
| A12 | Graphviz 真实渲染验收 | 独立跟踪，未闭环 |

## 1. 结论与已拍板决策

Motion Canvas 适合作为 LCES 的矢量动画后端（场景化流程演化、架构示意、算法步骤、动态标注），
不替代静态 SVG / Mermaid / Graphviz，也不作为通用视频编辑器。

| # | 决策 | 结论 |
|---|---|---|
| 1 | Node.js | **Node 24 LTS 为主验证版本**（当前 24.22.1）；Node 22 LTS（当前 22.23.4）仅作兼容性对照。最终锁定精确版本、npm 版本、OS/架构 |
| 2 | 联网边界 | 接受"安装/准备期联网、渲染期离线"；离线验收必须**断网执行**并留存证据与负控制 |
| 3 | Playwright 驱动编辑器 | 仅作为**受控适配层**；不得用固定等待、猜测按钮或静默重试伪造成功；UI 变化显式失败 |
| 4 | 人工抽检 | **必须，分层执行**：原型阶段每个模板人工验收；生产阶段对新模板、版本变化和高风险任务抽检 |
| 5 | 首批模板 | 先 `title`、`flow`、`compare`；`code-walkthrough` 在前三者验收通过后加入 |

## 2. 官方依据与证据记录

核查日期：2026-10-22。

| 事实 | 依据 | 性质 |
|---|---|---|
| 版本 3.17.2，MIT | npm registry：core / 2d / ffmpeg / create 一致 | 官方元数据 |
| Node 要求 "16 or greater" | <https://motioncanvas.io/docs/quickstart> | 官方文档 |
| Node 24.22.1（Krypton）、22.23.4（Jod）均在 LTS 线 | <https://nodejs.org/en/about/previous-releases> | 官方发布记录 |
| 项目创建 `npm init @motion-canvas@latest` | Quickstart | 官方文档 |
| 模板脚本只有 `dev: vite`、`build: tsc && vite build` | 仓库 `packages/template/package.json` | 源码观察 |
| 渲染为编辑器 RENDER → 逐帧写 `/output`，再用 FFmpeg 合成 | <https://motioncanvas.io/docs/rendering> | 官方文档 |
| `@motion-canvas/ffmpeg` 自带 FFmpeg 二进制 | npm 依赖 `@ffmpeg-installer/ffmpeg` | 官方元数据 |
| 未见稳定 headless API/CLI | 当前官方文档与源码调查 | **阶段性结论**，每次升级重新验证 |

证据保存要求（A2 评审补充）：

1. 保存核查日期、精确版本、官方 URL；
2. 保存 npm registry 元数据（版本、许可证、依赖、tarball integrity）；
3. 文档与源码引用使用 tag/commit，不只链接会变化的 `main`；
4. 明确区分"官方承诺""源码观察""P0 实验结论"，不把阶段性结论写成永久事实；
5. 每次升级 Motion Canvas / Node / 驱动时重新核查并更新本节。

P0 必须回答的未知项：

1. 3.17.2 是否存在官方支持、可稳定调用的 headless 入口；
2. 若驱动编辑器：就绪、完成、取消、异常、超时的**确定性信号**；
3. 是否依赖 Vite dev server、端口与浏览器版本；
4. `npm ci` 的离线复用条件；
5. 字体、颜色空间、PNG/WebP 编码一致性；
6. 1080p/30fps/10s 样例的耗时、内存、磁盘峰值。

## 3. 定位与边界

适用：技术课程中的流程演化、系统架构示意、算法步骤、动态标注；由结构化场景契约驱动的可重复动画。

明确不做：

- 通用视频编辑器；
- 让模型直接编写并执行任意 TypeScript；
- 取代静态图表渲染器；
- 未经评审采用 fork（Revideo）或 alpha 包作为生产依赖；
- 第二套浏览器或第二套编码逻辑。

## 4. 集成架构与依赖策略

### 4.1 进程边界

```text
LCES (Python)
  VisualAsset / SceneContract
        │  校验 + 路径约束 + 构建 ID + 哈希
        ▼
  RendererRegistry
        │  environment → input → estimate → render → collect → validate
        ▼
  motion_canvas.renderer (Python adapter)
        │  JSON/文件契约、超时、取消、日志、退出码
        ▼
  独立 Node.js 工程（锁定依赖、提交 lockfile、node_modules 不入库）
        │  帧序列（PNG）写入构建专属临时目录
        ▼
  LCES 系统 FFmpeg（唯一编码入口）+ ffprobe 校验
        ▼
  FrameManifest + 输出视频 + VisualAsset 清单 + QA 结果
```

原则：**不把 LCES 核心执行环境改成 Node.js**。Node 工程是被调度的子进程。

### 4.2 依赖矩阵

| 依赖 | 版本策略 | 说明 |
|---|---|---|
| Node.js | 主：24.22.1；对照：22.23.4 | `.nvmrc` + `engines` 双重声明；`engines` 不强制，必须由安装脚本与运行时硬门禁 |
| npm | 随 Node 锁定并记录 | 只用 `npm ci`；提交 `package-lock.json` |
| `@motion-canvas/core` / `2d` | 精确 3.17.2 | 不使用 `^` |
| 渲染驱动 | P0 决定 | 官方 headless > Playwright 驱动编辑器 > 暂缓 |
| 浏览器 | 复用 Playwright Chromium | 记录实际版本、可执行文件来源、启动参数 |
| FFmpeg | 系统 FFmpeg | **不使用 `@motion-canvas/ffmpeg`** |
| `node_modules` | 不入库 | 安装期需网络、渲染期离线 |

供应链要求：

1. `npm ci` 依赖 lockfile 中的 integrity 校验，不接受 `npm install` 改写锁文件；
2. 审核直接与传递依赖的许可证和已知安全风险，记录审计日期与结果；
3. `setup-motion-canvas.ps1` 必须幂等：版本不匹配时**失败**，不自动升级 Node、不重写锁文件；
4. 记录浏览器身份与启动参数，不只写"Playwright Chromium"。

### 4.3 浏览器与编码职责

1. Motion Canvas 负责场景动画与逐帧生成。
2. LCES 负责调度、帧清单、帧数检查、构建溯源。
3. 系统 FFmpeg 负责唯一编码与媒体校验。
4. 记录编码器版本、完整参数、输入帧清单与输出哈希。
5. 更换编码方式必须独立评审，不得悄悄启用自带编码链。
6. 浏览器只由 Playwright 提供；渲染期禁止任何非本地网络请求。

## 5. 契约映射

### 5.1 `VisualAsset`

| 字段 | Motion Canvas 映射 |
|---|---|
| `asset_id` | 稳定 ID，例如 `anim-system-flow` |
| `asset_type` | `animation` |
| `source` | 结构化场景 JSON（`content/scenes/*.json`），不是生成的 TS |
| `renderer` / `renderer_version` | `motion_canvas.renderer` / 适配器版本 |
| `parameters` | 画布、`fps_num`/`fps_den`、总帧数、场景帧边界、seed、字体清单 |
| `dependencies` | lockfile 哈希、Node/npm、Chromium（版本+来源）、FFmpeg、驱动版本 |
| `output_paths` | FrameManifest、最终 mp4 |
| `output_hashes` | FrameManifest 哈希、mp4 哈希 |
| `status` | `pending` / `rendered` / `failed` / `skipped` |
| `qa_results` | 帧清单校验、空白帧、时长、ffprobe、关键帧 |
| `source_hash` | 场景 JSON sha256 |
| `build_id` | 构建批次 ID，与日志/截图关联 |

### 5.2 `SceneContract` → 时间轴与转场（A2）

| 契约字段 | 映射规则 |
|---|---|
| `duration_ms` | 场景**完整时长**（整数毫秒），包含转场时间 |
| `scene_id` | 工程内唯一标识 |
| `scene_type` | 受控模板（title / flow / compare；code-walkthrough 后续） |
| `source_asset_refs` | 仅允许 `content/` 下已登记资产 |
| `transition_in/out` | 首版 `cut` / `fade`；`slide` / `zoom` 显式 `invalid_input` |
| `narration_ref` / `subtitle_ref` | 引用透传，时间基准与最终编码时间轴一致 |
| `fallback_policy` | 默认 `fail`；`skip` / `placeholder` 写入 QA 结果 |

冻结的时间轴语义：

1. **所有转场都包含在场景 `duration_ms` 内**，转场不得隐式延长全片。
2. 帧 `f` 属于场景 `i`，当且仅当 `B_(i-1) <= f < B_i`（`B` 见 §5.3）。
3. `transition_out` 使用场景 `i` 的尾部帧；`transition_in` 使用场景 `i+1` 的头部帧。
4. 同一边界上两侧都声明非 `cut` 转场 → `invalid_input`，不猜测优先级。
5. `fade` 时长参数必须 `<= duration_ms`；超出 → `invalid_input`。
6. 音频、字幕与视频共用同一套帧边界；字幕超出 `[0, total_frames/fps]` 判 `qa_failed`。
7. 最终时长 = `total_frames / fps`；契约时长 = `Σ duration_ms`；容差 1 帧。

### 5.3 MC-01：时间轴与帧数分配算法（A1）

时间基准为整数毫秒，帧率为有理数，全部使用整数运算；**禁止浮点秒累加，禁止使用 Python `round()`**
（银行家舍入会在 `.5` 处产生与规范不同的结果）。

定义：

- 场景 `i` 时长 `d_i`（整数毫秒，`d_i > 0`）；
- 累计时长 `C_i = Σ(j≤i) d_j`，`C_0 = 0`；
- 累计帧边界
  `B_i = (2 * C_i * f_n + 1000 * f_d) // (2000 * f_d)`（半值向上，全整数）；
- 场景帧数 `frames_i = B_i - B_(i-1)`；
- 全片帧数 `total_frames = B_n`。

约束与校验：

1. `frames_i >= 1`；累计边界相减得到 0 帧 → `invalid_input`，**不得静默补成 1 帧**。
2. 禁止逐场景独立取整后相加；必须用累计边界相减。
3. `expected_s = total_frames * f_d / f_n`；`contract_s = C_n / 1000`；
   `abs(expected_s - contract_s) <= f_d / f_n`（1 帧）。
4. ffprobe 实测时长与 `expected_s` 容差 **1 帧**；超出即 `frame_mismatch`。
5. 编码前帧清单数量必须等于 `total_frames`，尺寸一致。
6. 整数安全：Python 使用任意精度整数；其它实现必须校验乘法溢出，
   并对时长、fps、帧数设上限（建议 `total_frames <= 1_000_000`，`duration_ms <= 3600_000`）。

P0 实测补充（2026-10-22）：

- Motion Canvas 的 `shared.range` 在 `project.meta` 中以**秒**存储，UI 以**帧**显示；
- 10 s @ 30 fps 使用全范围会输出 **302** 帧；把 range end 设为帧 299
  （秒值 `299/30`）后输出 **300** 帧，与 MC-01 一致；
- 因此 LCES 必须根据 MC-01 计算 `total_frames`，显式写入
  `range = [0, (total_frames - 1) / fps]`，并在编码前校验帧数；
- 该结论需要测试覆盖：range 换算、+1/−1 帧边界、全范围与显式范围对比。

**反例（已替换）**：30 fps，三个连续场景各 50 ms。

| 计算方式 | 每段帧数 | 总帧数 |
|---|---|---|
| 每段独立 `round(1.5)` | 2 / 2 / 2 | **6** |
| 累计边界相减 | 2 / 1 / 2 | **5** |

累计边界：`B_1 = round(1.5) = 2`，`B_2 = round(3.0) = 3`，`B_3 = round(4.5) = 5`。
因此帧数为 `2, 1, 2`，总帧数 5，`Σ frames_i = B_n` 必须成立。

容差边界说明：该示例的最终时长为 `5 / 30 = 166.67 ms`，契约时长 `150 ms`，
相差 `16.67 ms`，**恰好等于一帧**，因此按 `<= 1 帧` 的规则通过。
这属于容差边界，不是典型情况：

- 测试必须覆盖"恰好 1 帧"（通过）与"超过 1 帧"（`frame_mismatch`）两侧；
- 不允许把该示例当作"50 ms 场景可以放心使用"的依据；
- 若产品要求更严格，可在模板层增加最小场景时长（例如 >= 100 ms），
  但该策略必须显式配置并写入输入校验，不能由渲染器临时决定。

测试要求：

- 上表作为确定性单元测试；
- 属性测试：对随机场景序列，`sum(frames_i) == B_n`，且所有 `frames_i >= 1`；
- 零帧场景（30 fps、10 ms）→ `invalid_input`；
- `30000/1001` 与 30 fps 的时长核对；
- 容差两侧：恰好 1 帧通过，`1 帧 + 1 ms` 失败；
- 大时长/异常 fps 的溢出保护。

### 5.4 FrameManifest（A7）

帧目录本身不是证据；必须生成版本化清单：

```json
{
  "schema_version": "1.0",
  "build_id": "build-20261022-001",
  "asset_id": "anim-system-flow",
  "fps_num": 30000,
  "fps_den": 1001,
  "width": 1920,
  "height": 1080,
  "format": "png",
  "total_frames": 90,
  "scenes": [
    {"scene_id": "scene-001", "start_frame": 0, "end_frame": 30},
    {"scene_id": "scene-002", "start_frame": 30, "end_frame": 60}
  ],
  "frames": [
    {"index": 0, "path": "frames/000000.png", "sha256": "...", "width": 1920,
     "height": 1080, "decodable": true}
  ]
}
```

完整性校验：序号从 0 连续且数量等于 `total_frames`；每帧路径在构建目录内；
哈希匹配；宽高一致；可解码；场景边界连续且覆盖全片；清单自身哈希写入
`VisualAsset.output_hashes`。

## 6. 适配器接口与驱动协议

### 6.1 接口契约（A10）

以 LCES 现有 `Renderer` 协议为准，下表只补充 Motion Canvas 的**额外契约**，
不另建平行接口。

| 钩子 | 契约 |
|---|---|
| `check_environment` | 结构化结果：依赖项、实际版本、期望版本、缺失项、修复建议；不只返回 bool |
| `validate_input` | **纯校验**：不启动渲染、不创建最终输出、不修改项目状态 |
| `estimate_resources` | 预估值 + 单位 + 计算依据 + 置信度（`rough` / `measured`） |
| `render` | 返回 `build_id`、阶段、日志与证据路径、退出结果；异常带错误码 |
| `cancel` | 取消确认、进程树终止、临时产物保留、正式输出不产生 |
| `collect_outputs` | 只收集本次构建产生、且写入 FrameManifest 的文件 |
| 输出校验 | 由现有注册表统一调用 `validate`；Motion Canvas 不另设第二套校验入口 |
| `get_diagnostics` | 脱敏后的错误码、阶段、退出码、版本、证据路径 |

### 6.2 MC-02：Playwright 驱动协议

仅在 P0 证明没有可靠 headless API 时启用。状态机：

```text
launch → ready → configured → rendering → completed
                                  ├→ failed
                                  ├→ cancelled
                                  └→ timeout
```

进入 `completed` 必须同时满足（三项独立条件，不是"两个信号"）：

1. 驱动报告渲染操作完成（来自固定版本编辑器的显式状态）；
2. FrameManifest 校验通过：每帧完整、可解码、数量与边界正确；
3. 子进程与浏览器无失败上报，且任务未被取消或超时。

规则：

- **就绪信号**必须来自锁定版本的显式 DOM 属性/全局 API/官方事件；找不到则本方案不通过。
- **禁止**固定 `sleep`、按坐标/文本猜测按钮、静默重试、以退出码 0 代替完成判定。
- **UI 变化**：选择器/属性与锁定版本不符 → `driver_protocol_mismatch`，立即失败。
- **超时**：就绪 `T1`、渲染 `T2 = max(基准, 帧数 × 单帧上限)`、总超时 `T3`；超时终止并保留证据。
- **证据**：每次状态转换记录截图、控制台错误、失败请求、URL、版本，写入 `internal/qa/` 并关联 `build_id`。

P0 实测信号（3.17.2，仅作受控适配层参考）：

| 状态 | 信号 |
|---|---|
| idle | `RENDER` 存在；无 `ETA:` |
| rendering | `Abort` 存在；body 含 `ETA: hh:mm:ss`；存在 `loading` 类；帧数增长 |
| completed | `Abort` 消失、`RENDER` 回来；帧数连续采样不变 |

采样注意：用 Playwright `locator(...).inner_text()` 轮询曾在 1.0 s 漏掉
`Abort`；改用 `page.evaluate` 读取 DOM 后稳定。body 级 `ETA` 正则可能残留，
完成判定不能只依赖“无 ETA”。

## 7. 失败状态、终态与产物隔离（A8）

| 错误码 | 触发条件 | 终态 |
|---|---|---|
| `environment_unavailable` | Node/依赖/驱动/FFmpeg 缺失或版本不符 | `failed` |
| `dependency_mismatch` | lockfile 哈希与安装不一致 | `failed` |
| `invalid_input` | 契约/模板/资产/字体/零帧场景 | `failed` |
| `driver_protocol_mismatch` | UI 与锁定版本不符 | `failed` |
| `render_timeout` | 超过 `T2/T3` | `failed` |
| `render_failed` | 非零退出或驱动异常 | `failed` |
| `cancelled` | 用户取消 | `cancelled` |
| `output_missing` | 未产生帧或视频 | `failed` |
| `frame_mismatch` | 帧数/时长偏差 > 1 帧 | `failed` |
| `output_corrupt` | PNG 不可解码、空白帧超阈值 | `failed` |
| `encode_failed` | FFmpeg 非零退出 | `failed` |
| `qa_failed` | ffprobe/字幕/视觉校验不符 | `failed` |

产物生命周期规则：

1. 本次构建的帧、未验证视频、临时编码结果只存在于**构建专属临时目录**。
2. 失败/取消后，部分产物**不得**进入正式输出或发布目录。
3. 最终 mp4 只有在编码、元数据、FrameManifest 与全部强制 QA 通过后，
   才能**原子性**移动到正式路径。
4. 旧构建的有效资产不得被失败的新构建覆盖。
5. 日志、截图、部分帧可保留用于诊断，但必须标记 `non-publishable`。
6. 临时目录设置保留期限、磁盘配额与清理策略，清理不得影响其它构建。
7. 同一任务只允许一个终态；错误码映射到 `failed` / `cancelled`，不得并存矛盾状态。

## 8. 安全与资源限制

- 子进程仅能读写构建临时目录与 `content/` 下已登记资产。
- 路径校验 = 规范化路径 + 文件系统边界：解析符号链接、Windows junction / reparse point，
  拒绝任何解析后落在工作区外的路径；不能只检查 `..`。
- 环境变量白名单；不继承无关密钥；子进程最小权限。
- 渲染期网络隔离采用可证明的操作系统级手段（防火墙规则/网络命名空间），
  **不以"浏览器日志没有请求"替代**；同时保留浏览器请求日志作为佐证。
- 模型不生成可执行 TypeScript；只生成受控场景 JSON。
- 资源上限必须量化：最大分辨率、最大帧数、最长运行时间、内存/磁盘配额；超限即失败。
- 日志脱敏：不含绝对用户路径、密钥、完整提示词。

## 9. 可复现性与视觉验收（A9）

### 9.1 三级承诺

| 级别 | 内容 | 要求 |
|---|---|---|
| Level 1 输入可追溯 | 场景 JSON、模板版本、lockfile、Node/npm、Chromium（版本+来源+参数）、字体、编码器参数、色彩空间/GPU 设置 | **必须** |
| Level 2 结构可复现 | 帧数、尺寸、场景边界、时长、元数据、文件清单符合契约；重复构建不改变结构约束 | **必须** |
| Level 3 内容可复现 | 字节级一致率与视觉差分 | **需实测**；只对已验证环境声明 |

Level 3 实测流程：同一环境连续构建 3 次 → 干净环境重复 → 分别记录逐字节一致率与视觉差分。
三次构建不能外推到跨 OS / 跨 GPU / 跨编码器版本。

### 9.2 MC-03：离线可复现测试

1. 准备阶段（允许联网）：安装精确 Node、`npm ci`、Playwright Chromium、确认 FFmpeg；
   记录版本与 lockfile 哈希。
2. 使用独立 npm 缓存目录（或清空缓存）完成准备。
3. 操作系统级断网（Windows 防火墙出站阻止；CI 网络命名空间），完整渲染一次。
4. 证据：浏览器请求仅 `file:` / `data:` / `blob:` / `localhost`；无 DNS/HTTP 外联；
   输出通过 FrameManifest 与 ffprobe 校验。
5. 负控制：断网状态下安装未缓存依赖必须失败。
6. 不得以"本机热缓存"作为离线证据。

### 9.3 MC-04：视觉验收

自动检查（每次构建）：

- FrameManifest 全部通过；
- 空白帧不能只靠方差：结合前景占用率、透明像素比例、边缘/结构差异，
  并允许模板声明例外（标题卡、纯色背景、淡入首帧）；
- 像素差分按模板分别标定；0.5% 仅作为初始实验值，不作为统一生产门槛；
- 记录误报、漏报与人工复核结果。

人工验收（分层）：

- 原型阶段每个模板逐个人工验收；
- 生产阶段：新模板、渲染器/Node/驱动/FFmpeg 版本变化、高风险任务、抽样构建；
- 记录审阅人、日期、抽看帧路径、结论；
- 失败：资产置 `failed`，禁止发布；修复后重新验收并保留旧记录。

## 10. 测试矩阵与通过门槛

| 类别 | 用例 | 通过标准 |
|---|---|---|
| 单元 | MC-01 边界、舍入、零帧、溢出、非法 fps/转场、字体白名单、路径越界 | 全部确定性断言通过 |
| 集成 | 最小动画真实导出、系统 FFmpeg 编码、ffprobe、FrameManifest | 至少一次真实导出全链路通过 |
| 驱动 | 就绪/完成/取消/超时/UI 不匹配 | 均进入预期状态并留证据 |
| 失败注入 | 缺 Node/依赖、lockfile 不匹配、非零退出、损坏 PNG、空白帧、FFmpeg 失败 | 证明失败产物不会被发布 |
| 安全 | 恶意场景 JSON、路径遍历/链接逃逸、外联尝试 | 被阻断或明确拒绝 |
| 离线 | MC-03 全流程 + 负控制 | 断网渲染成功，负控制失败 |
| 视觉 | MC-04 自动指标 + 人工记录 | 两类结果分别记录，不互相替代 |
| CI | 固定 Node + `npm ci` + Chromium + FFmpeg | 必需测试失败即 job 失败；只有明确列出的环境受限项可跳过 |

跳过规则：承担真实渲染验证职责的 CI job，缺少依赖必须**失败**，不得 `skip`；
只有通用单元测试环境可以合理跳过外部依赖集成测试。

## 11. 分阶段实施与 P0 决策门槛（A3）

### P0：可行性验证（时间盒，先于任何生产代码）

交付 `docs/design/motion-canvas-spike.md`，内容包括：

1. 精确 Node/npm、OS/架构、`npm ci` 结果、lockfile 哈希；
2. 驱动结论：官方 headless 是否存在；若用编辑器，给出就绪/完成/取消/超时信号；
3. MC-03 断网证据与负控制；
4. 1080p/30fps/10s 资源基线（耗时、内存、磁盘）；
5. MC-01 在真实导出上的帧数与时长核对；
6. 失败注入：缺依赖、超时、取消、损坏输出各一次；
7. 结论与设计调整建议。

决策门槛：

- `GO`：全部强制项通过 → 进入 P1。
- `CONDITIONAL_GO`：仅**非安全、非正确性**项未完成，且写明条件、负责人、期限。
  驱动信号、网络隔离、输出完整性、取消、资源上限**不允许**用 CONDITIONAL_GO 跳过。
- `NO_GO`：缺少可靠驱动信号、无法满足离线约束、无法可靠取消、资源成本不可接受。

### P1：最小可运行原型

进入条件：Linux-only 已确定。入口调用 `assertSupportedPlatform`，非 Linux 以
`unsupported_platform` 拒绝；本地使用 WSL2（Ubuntu 24.04），CI 使用 Linux
容器；Windows 原生不在范围。UI 契约测试与版本变更重跑 P0 的规则继续有效。
WSL 的 Node/npm/浏览器/FFmpeg 由用户维护，P1 只检查精确版本，不自动安装。

- `title` 模板，固定画布/帧率/时长；
- 帧序列 + FrameManifest + 系统 FFmpeg 编码；
- 通过帧数、尺寸、时长、关键帧检查；
- 连续构建 3 次，记录字节/视觉一致性。

### P2：接入 Renderer Registry

- 显式 `motion_canvas.renderer`，实现全部钩子；
- 环境检查、输入校验、资源估算、取消、输出收集、诊断；
- 资产契约写入 `visual_assets.json`；
- 失败不静默回退；
- 增加 `flow`、`compare` 模板；
- 完成供应链、路径与子进程隔离（A11）。

### P3：生产级测试

- 覆盖 §10 全部失败路径与 MC-01～MC-04；
- 损坏输出、重复构建、哈希记录；
- 完整测试集与 CI job。

### P4：验收后再评估 Remotion

- 先确认 Motion Canvas 的适用边界与真实交付质量；
- 不提前引入两套相似的视频生产管线；
- `code-walkthrough` 视需要加入。

## 12. 验收标准

### 12.1 强制门槛（未满足即不得发布）

- [ ] 驱动完成状态可确定（三项条件全部满足）；
- [ ] MC-01 时间轴正确，帧数与时长误差 ≤ 1 帧；
- [ ] MC-03 断网渲染通过，负控制成立；
- [ ] FrameManifest 完整、可校验；
- [ ] 失败/取消的产物不进入发布路径，终态唯一；
- [ ] 依赖、浏览器、编码器、字体可追溯；
- [ ] 系统 FFmpeg 是唯一编码入口；
- [ ] Motion Canvas 验收不替代 Graphviz 真实渲染验收。

### 12.2 待实测指标（不得预先写成保证）

- 视觉差分阈值（分模板标定）；
- 渲染耗时、内存峰值、磁盘峰值；
- 跨环境一致性（Level 3）；
- 字节级一致率。

## 13. 剩余问题与决策记录

已解决：Node 版本策略、联网边界、Playwright 边界、人工抽检分层、首批模板范围、
MC-01 反例、时间轴语义、FrameManifest、产物隔离、三级可复现性、P0 决策门槛。

仍未决，每项必须记录 **验证方法 / 证据文件 / 决策 / 决策日期**：

| # | 问题 | 验证方法 | 证据文件 | 决策 / 日期 |
|---|---|---|---|---|
| 1 | 是否存在显式就绪/完成信号 | P0 驱动实验 + CI 契约测试 | `motion-canvas-spike.md` §4/§11 | 受控 DOM 信号；contract.test.mjs 10/10（run `39750119050`）；非官方 API — 2026-10-22 |
| 2 | 视觉差分阈值 | P1 实测 | `internal/qa/` 报告 | 待定 |
| 3 | CI 断网实现方式 | P0 CI（`docker --network none`） | spike §7、run `39750119050` | **PASS**：300 帧、负控制失败、请求审计留存 — 2026-10-22 |
| 4 | 官方 headless API 的长期稳定性 | 每次升级复核 | 版本核查记录 | 当前未发现官方 headless 入口；每次升级重新核查 — 2026-10-22 |
| 5 | 场景模板字段冻结时间点 | P1 结束评审 | 本文件修订记录 | 待定 |

P0 总体决策（2026-10-22）：**GO（仅 Linux）**。硬门槛全部通过；P1 入口必须
调用 `assertSupportedPlatform` 拒绝非 Linux（`unsupported_platform`）。
本地开发使用 WSL2（Ubuntu 24.04）；Windows 原生支持需要新的 P0 与重新准入。
详见 `docs/design/motion-canvas-spike.md` §10/§11。

Graphviz 独立验收（A12）：CI 环境已用 Graphviz 2.43.0 完成真实 `dot`
渲染、SVG 校验、缺依赖错误与 14/14 测试；Windows 本地 16.1.0 仍待安装。
该验收不与本文档的 Motion Canvas 结论合并。
