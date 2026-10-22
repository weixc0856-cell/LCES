# Motion Canvas P1 实施计划与准入验收表

日期：2026-10-22
范围：P1（Linux / WSL2），`title` 最小原型。
前置：P0 结论 **GO（仅 Linux）**，CI run `39752667833`；详见
`docs/design/motion-canvas-spike.md`、`docs/design/MOTION_CANVAS.md`。

本文是 P1 的实施依据。它冻结接口决策，并记录每条验收的实际状态；
状态只有四种：`NOT_RUN`、`PASS`、`FAIL`、`BLOCKED`。
未执行的检查不得记为 `PASS`；CI job 的总体成功不得代替逐条断言。

**当前状态（2026-10-22）**：P1.1 已在 Linux CI 通过真实渲染
（run `39762458701`，commit `c9d31af`）；P1.2 已实现并通过 CI，FrameManifest
的 300 帧哈希、PNG 结构与整段解码已用独立脚本全量核验（run `39767972300`，
commit `cdce036`）；P1.3 已通过 CI 验收（run `39777983672`，commit `71f1bcc`）：
冒烟与生产配置都完成真实编码，独立复核的 `course.mp4` 与 FrameManifest
一致（30 帧 640×360 / 1.0 s；300 帧 1920×1080 / 10.0 s），Gate 4 真实视频
用例通过；P1.4 的故障矩阵、取消/超时回归与断网作业已通过 CI 验收
（run `39785216053`：两个 motion job 全绿，断网 artifact 已核对）。

**两种渲染配置**（不得混用）：

| 配置 | 画布 / 帧数 | 用途 | 验收项 |
|---|---|---|---|
| 冒烟 | 640×360 / 30 帧（1 s） | 每次 PR 的快速真实渲染 | P1-GATE-08 |
| 生产 | 1920×1080 / 300 帧（10 s @ 30 fps） | P1 的正式渲染规格 | P1-GATE-14 |

冒烟通过不等于生产规格通过；两者都在同一 CI job 中真实执行。

## 1. 冻结决策

| 决策 | 最终方案 | 落地位置 |
|---|---|---|
| Renderer 接入边界 | 实现现有 `Renderer` 协议，但**不注册**到 `default_registry()` | `motion_canvas.motion_canvas_registry()` |
| 场景输入契约 | `SceneContract.data` + `SceneSet.scenes`（顺序即时间轴） | `models.py` |
| 视频参数归属 | 画布、帧率、编码仍由 `VideoContract` 提供 | `models.py`、`motion_canvas._parse()` |
| Node 版本 | 严格 `24.22.1`；`engines` 只是声明，硬门禁在适配器 | `motion/package.json`、`motion_canvas.NODE_VERSION` |
| 发布策略 | 暂存 → 校验 → 原子替换；失败/取消不覆盖旧资产 | P1.3 |
| CI 准入 | 新增 push/PR 必过的真实渲染 job | `.github/workflows/ci.yml` `motion-canvas-p1` |

补充约束：

- `SceneSet` 只负责顺序与集合级约束，不重复定义帧率或分辨率。
- 场景内容只存在于 `SceneContract.data`；模板字段由 `validate_input()` 校验，
  不写死进模型。
- Motion Canvas 的 TS 场景文件由**固定模板 + JSON 转义**生成，模型不产出
  可执行 TypeScript。

## 2. 接口契约

### 2.1 `Renderer` 扩展（向后兼容）

```python
@dataclass(frozen=True)
class RenderResult:
    status: Literal["completed", "cancelled", "failed"] = "completed"
    html: str = ""
    build_id: str = ""
    artifacts: tuple[Path, ...] = ()
    manifest: Path | None = None
    message: str = ""


class Renderer:
    def render(self, spec, context) -> str | RenderResult: ...
    def validate(self, spec, html, context: RenderContext | None = None) -> list[str]: ...
    def environment_error_code(self) -> str: ...  # 默认 environment_unavailable
```

注册表规则：`status != "completed"` 一律拒绝；`cancelled` 映射
`RenderCancelled`，其余映射 `RenderError`；环境失败使用
`environment_error_code()`，因此非 Linux 得到 `unsupported_platform`。

### 2.2 时间轴（MC-01）

`src/content_studio/timeline.py`：

- 全整数：`B_i = (2*C_i*fps_num + 1000*fps_den) // (2000*fps_den)`；
- `scene_frames_i = B_i - B_(i-1)`，0 帧即 `invalid_input`，不静默补帧；
- `total_frames = B_n`，上限 1,000,000；单场景时长上限 3,600,000 ms；
- `range_seconds() = (total_frames - 1) / fps`（P0 实测的 +2 帧修正）。

### 2.3 失败码

唯一事实来源：`config/error_codes.json`。每条包含 `stage`、`terminal`、
`exit_code`、`retryable`、`description`。Python（`errors.py`）与 Node
（`motion/contract.mjs`）都**解析**该文件，不各自维护副本。

终态只有 `failed` 与 `cancelled`；退出码唯一，便于在日志中反查。
`config/error_codes.json` 变更必须同时满足两侧测试：
`tests/test_error_codes.py`、`motion/contract.test.mjs`。

### 2.4 取消与超时

- 取消状态是 `threading.Event`，但终止动作是**进程组**信号
  （`start_new_session=True` + `killpg(SIGTERM/SIGKILL)`），Vite 与 Chromium
  不会在取消后继续写帧。
- 启动失败、重复取消、渲染完成与取消竞争：`cancel()` 幂等；构建完成即返回
  `completed`，取消标志不会把已完成的构建改写成 `cancelled`；一次只允许
  一个构建，重复进入被拒绝。

### 2.5 环境门禁

| 依赖 | 期望 | 失败码 |
|---|---|---|
| 平台 | `linux` | `unsupported_platform` |
| Node | `24.22.1` | `environment_unavailable` |
| npm | 11.x（随 Node） | `environment_unavailable` |
| Motion Canvas | `3.17.2` | `environment_unavailable` |
| Playwright | `1.64.0` + Chromium 可执行文件 | `environment_unavailable` |
| 依赖树 | 已安装直接依赖与 `package-lock.json` 一致 | `dependency_mismatch` |
| FFmpeg | `>= 6.0`，实际版本写入证据 | `environment_unavailable` |

`LCES_NODE_BIN` 可指定受控的可执行文件路径，与 `LCES_DOT_BIN` 同型。

### 2.6 FrameManifest（P1.2）

- 构建完成后写 `<build>/frame_manifest.json`，其中帧路径相对**构建目录**
  （例如 `frames/project/000000.png`）。
- 清单由渲染器生成，但**必须独立校验**：重新计算 SHA-256、检查 PNG 结构
  （签名/IHDR/CRC/IEND）、尺寸、场景边界、路径包含关系，并用 FFmpeg 解码
  整段帧序列。哈希正确但不可解码的 PNG 仍然失败。
- 清单哈希通过现有产物流程写入 `VisualAsset.output_hashes`；清单本身
  不进入发布目录。
- 失败码：帧数/序号不一致 → `frame_mismatch`；PNG 结构损坏 →
  `output_corrupt`；清单与文件不一致或解码失败 → `qa_failed`。

## 3. 阶段与完成条件

| 阶段 | 内容 | 完成条件 |
|---|---|---|
| P1.1 | 接口、时间轴、平台/版本门禁、取消、CLI、真实渲染 | 真实 title 场景帧数与分辨率正确；错误版本、错误平台被拒绝 |
| P1.2 | FrameManifest、PNG 结构、哈希、场景边界、路径约束 | 清单可独立证明帧连续、有效、覆盖完整 |
| P1.3 | FFmpeg 编码、ffprobe、解码、时长/帧数一致、原子替换 | 通过全部校验才替换；失败时旧文件哈希不变 |
| P1.4 | 故障注入与持续集成 | 每个故障都有结构化错误、唯一终态、不可发布；PR 跑真实渲染 |

### 3.1 P1.3 验收契约（2026-10-23 冻结，先于实现）

不变量：

1. **清单与视频一致**：解码后的实际帧数、有理数帧率、分辨率与时长都必须
   与 FrameManifest 一致；时长容差为 1 帧，且不能只比较容器自报的单一
   `duration` 字段。
2. **失败不破坏旧资产**：正式路径预置哨兵 `course.mp4` 时，编码失败、
   视频校验失败、取消或超时后，哨兵 SHA-256 必须保持不变。
3. **未验证产物不可发布**：编码只写入 `build/media/.staging-<build_id>/`；
   只有帧清单、视频一致性与解码全部通过后才 `os.replace` 到正式路径。
4. **Gate 4 独立**：发布门禁重新读取 release 中的视频，以及
   `internal/qa/frame_manifest.json` 与 `encode_report.json`，自行比较
   帧数、帧率、分辨率、时长与视频哈希，不信任编码器或清单的自报结果。
5. **编码参数显式**：`-framerate {fps_num}/{fps_den}`、`-start_number 0`、
   libx264、`yuv420p`、`+faststart`；FFmpeg 版本、完整 argv 与产物哈希写入
   `encode_report.json`。

阶段边界：断网与负控制、完整故障注入矩阵、取消/超时的端到端回归留在 P1.4。
P1.3 只验证上述不变量及其确定性失败用例。

## 4. P1-GATE 验收表

本机环境：Windows 11 Pro 10.0.26300；Python 3.13（项目 `.venv`）；
Node `v24.14.1`（**不满足 P1 要求**，本机只跑拒绝路径、单元测试与 Node 契约冒烟）。

CI 环境（run `39762458701`，`ubuntu-latest`）：Node `v24.22.1`、npm `11.19.1`、
Playwright `1.64.0`、FFmpeg `6.1.1-3ubuntu5`；`lces doctor` 报告
Motion Canvas 可用。

| ID | 验收项 | 命令 / 环境 | 结果 | 证据 | 状态 |
|---|---|---|---|---|---|
| P1-GATE-01 | P0 UI 驱动契约 | CI run `39752667833`（`--network none`） | job `success`；仓库记录 11/11 | GitHub Actions artifact | PASS（仅核验 job 结论，未重读 TAP） |
| P1-GATE-02 | 平台入口拒绝 | `uv run lces render-scene projects/example-course var/p1/scene.json --out var/p1/build`（Windows） | 退出码 **2**，`error_code=unsupported_platform`，未创建 `var/p1/build` | 本机终端；`var/p1/`（gitignored） | PASS |
| P1-GATE-03 | 环境报告 | `uv run lces doctor`（Windows） | Motion Canvas 不可用，逐项列出 platform/node/MC/Playwright/Chromium | 本机终端 | PASS |
| P1-GATE-04 | 共享失败码表 | `node -e "import('./motion/contract.mjs')…"`（Node 24.14.1，`motion/`） | 13 个码；`cancelled=130/cancelled`；`win32 → unsupported_platform`；`linux ok` | 本机终端 | PASS |
| P1-GATE-05 | lockfile 可安装 | `cd motion && npm ci && npm rebuild esbuild` | `added 69 packages`；`EBADENGINE` 警告符合预期（Node 24.14.1 ≠ 24.22.1） | 本机终端 | PASS |
| P1-GATE-06 | 单元/契约测试 | `uv run pytest`（本地） | **247 passed, 2 skipped**（Graphviz 未安装、`LCES_MC_E2E` 未设置） | `var/p1/pytest-final3.log` | PASS |
| P1-GATE-07 | 静态检查 | `ruff check .`、`ruff format --check .`、`mypy src`（本地与 CI `test` job） | 全部通过（35 个源文件） | 本机终端；CI run `39762458701` `test` job | PASS |
| P1-GATE-08 | 真实 title 渲染（P1.1 完成条件） | `LCES_MC_E2E=1 uv run pytest tests/test_motion_canvas_e2e.py -v --basetemp=motion-evidence/tmp --junitxml=motion-evidence/e2e-report.xml` | JUnit 1 test / 0 failures / 7.0 s；driver 报告 `frames=30`、`terminal=completed`、`error_code=""`、0.87 s；帧目录 30 个 PNG，首末帧 640×360 且 PNG 结构有效 | CI run `39762458701` artifact `motion-canvas-p1-evidence` | PASS |
| P1-GATE-09 | Node 契约套件 | `cd motion && node --test --test-reporter=tap contract.test.mjs` | TAP **13 tests / 13 pass / 0 fail**（34.4 s） | 同上 artifact `contract-tests.tap` | PASS |
| P1-GATE-10 | CI 必过真实渲染 | `.github/workflows/ci.yml` `motion-canvas-p1` | run `39762458701` 四个 job 全部 success；缺依赖不会 skip | GitHub Actions run | PASS |
| P1-GATE-11 | FrameManifest（P1.2） | `uv run python scripts/verify-frame-manifest.py <frames-artifact>` | 清单 `total_frames=300`、`build_id=build-20261022-111018-a735cb` 与构建目录及 driver report 一致；场景覆盖 `0–300`；**300/300 帧 SHA-256 与实际文件一致**；**300/300 帧 PNG 结构/尺寸通过**；`ffmpeg` 整段解码 exit 0；清单 sha256 `b5af5ac4…60d` | CI run `39767972300` artifact `motion-canvas-p1-frames`（8.6 MB 压缩 / 17 MB 解压） | PASS |
| P1-GATE-12 | 编码与原子发布（P1.3） | `LCES_MC_E2E=1 uv run pytest tests/test_motion_canvas_e2e.py tests/test_encode.py tests/test_release_video.py -v` | CI run `39777983672` job `motion-canvas-p1`：JUnit **9 tests / 0 failures / 0 skipped / 20.7 s**；两个真实构建都产出 `course.mp4`；独立复核 artifact 中的视频：冒烟 30 帧 640×360 30/1 1.000 s、生产 300 帧 1920×1080 30/1 10.000 s，`verify_video_against_manifest` 均为 0 problem | artifact `motion-canvas-p1-evidence`（run `39777983672`） | PASS |
| P1-GATE-15 | Gate 4 独立核对（P1.3） | 同一 job 内的 `tests/test_release_video.py` | `test_gate4_accepts_a_real_video`、`test_gate4_rejects_a_short_video` 均通过；Gate 4 重读发布视频与 `internal/qa/{frame_manifest,encode_report}.json`，短编码被判 `fail` | 同上 | PASS |
| P1-GATE-13 | 故障注入、取消/超时与断网（P1.4） | `uv run pytest tests/test_motion_canvas.py`；`LCES_MC_E2E=1 uv run pytest tests/test_motion_canvas_e2e.py -v`；CI job `motion-canvas-offline` | 单元故障矩阵覆盖 13 个失败码（含 lockfile 不一致）。CI run `39785216053`：`motion-canvas-p1` JUnit **11 tests / 0 failures / 34.7 s**（含真实取消 6.0 s、超时 2.1 s）；`motion-canvas-offline` 在 `--network none` 下 JUnit **11 tests / 0 failures / 30.8 s**，负控制 `fetch_exit=1 npm_exit=1`，两个构建各 4 次外部请求全部失败，视频哈希与编码记录一致 | 本机终端；run `39785216053` artifacts `motion-canvas-p1-evidence`、`motion-canvas-offline-evidence`；§4.3 | PASS |
| P1-GATE-14 | 生产配置渲染（1920×1080 / 300 帧） | `LCES_MC_E2E=1 uv run pytest tests/test_motion_canvas_e2e.py::test_production_config_renders_300_frames_at_1080p -v` | JUnit 2 tests / 0 failures / 19.1 s（生产用例 11.9 s）；driver 报告 `frames=300`、`terminal=completed`、5.87 s；帧目录 300 个 PNG（`000000`–`000299`） | CI run `39765444261` artifact `motion-canvas-p1-evidence` | PASS |

`BLOCKED` 的含义是：验收本身已定义、可执行，但当前环境不满足；
它不是通过，也不是失败。

全量哈希核验需要帧字节，因此常规 PR artifact 只保留清单、报告、驱动日志与
首末帧（约 250 KB）；`workflow_dispatch` 的 `keep_frames=true` 会额外上传
生产配置的全部帧（约 17 MB），供独立脚本核验。首末帧哈希只作摘要，不作为
全量校验的替代。

### 4.1 失败与修复记录

P1-GATE-08/09/10 不是一次通过的，两次失败都保留如下：

| 运行 | 现象 | 原因 | 修复 |
|---|---|---|---|
| `39760664001` | 契约 13/13 通过；真实渲染 `render_failed`，约 35 s 后结束 | 构建工程把 `node_modules` 软链回 `motion/`，Vite 默认 `server.fs.allow` 不包含该真实路径，编辑器 bundle 返回 403，页面没有 Render 控件 | `vite.config.ts` 显式放行 `MC_NODE_MODULES`；导出目录改用绝对路径 `MC_OUTPUT_DIR`；失败信息附驱动日志尾部 |
| `39761467582` | 驱动报告 30 帧、`completed`，Python 随后报 `expected 30 frames, found 0` | image-sequence 导出器把帧写在 `<output>/<project>/` 子目录，Python 只列了顶层 | `_frame_problems` 改为递归扫描，与驱动 `countFrames` 一致，并加测试 |
| `39784382250` | 取消用例收到 `render_failed` 而不是 `cancelled` | 进程组被取消信号终止时，驱动先写出失败报告并退出；适配器轮询到进程结束，尚未观察到取消标志 | 取消标志优先于驱动报告（`_execute_driver` 与 `render` 两处）；新增 `test_cancel_wins_over_the_drivers_failure_report` |
| `39784382250` | 断网 job 的全部渲染在环境门禁失败：`ffmpeg 5.1.9 < 6.0` | 镜像基于 Debian bookworm，其 FFmpeg 为 5.1.9 | 镜像改用 trixie（FFmpeg 7.1.5），并在构建阶段断言 `ffmpeg >= 6`；不为通过而放宽门禁 |

两次失败都不是“放宽断言”解决的；修复后的断言与 P1.1 完成条件一致。

### 4.2 P1.4 故障矩阵与断网证据

故障注入矩阵（主机无关，`tests/test_motion_canvas.py` + `tests/test_encode.py`）。
每一行都断言：结构化失败码、唯一终态（`failed` / `cancelled`）、旧视频哈希不变、
不写 `internal/qa/` 证据；失败矩阵用例集中在
`test_every_failure_publishes_nothing`，其余为单点用例。

| 故障 | 失败码 | 终态 | 关键断言 |
|---|---|---|---|
| 非 Linux 平台 | `unsupported_platform` | failed | 入口拒绝，不创建构建目录 |
| 缺少工具/版本不符 | `environment_unavailable` | failed | 渲染前失败 |
| `node_modules` 与 lockfile 不一致 | `dependency_mismatch` | failed | 渲染前失败，无任何产物 |
| 场景/视频契约非法 | `invalid_input` | failed | 校验阶段拒绝 |
| 驱动 UI 协议不符 | `driver_protocol_mismatch` | failed | 保留驱动报告的错误码 |
| 超时 | `render_timeout` | failed | 进程组终止，旧视频不变 |
| 非零退出/未知错误 | `render_failed` | failed | 驱动日志尾部进入错误 |
| 取消 | `cancelled` | cancelled | 进程组终止，旧视频不变 |
| 缺少 report | `output_missing` | failed | 未发布任何视频 |
| 帧数不符/缺帧 | `frame_mismatch` | failed | 未发布任何视频 |
| PNG 损坏 | `output_corrupt` | failed | CRC/尺寸/结构任一失败即拒绝 |
| FFmpeg 失败/超时/空输出 | `encode_failed` | failed | 旧视频哈希不变 |
| 视频与清单不一致 | `qa_failed` | failed | 不替换正式路径，不写 QA 证据 |

真实取消/超时（`tests/test_motion_canvas_e2e.py`，Linux + 固定工具链）：

- 取消：1080p/300 帧构建出现首帧后调用 `cancel()`；断言线程在限时内结束、
  异常为 `RenderCancelled`（终态 `cancelled`）、旧 `course.mp4` 哈希不变、
  无 `frame_manifest.json` 与新视频。
- 超时：适配器以 1.5 s 期限终止驱动；断言 `render_timeout`、旧视频不变、
  无清单与新视频。

断网验收（`motion/offline.Dockerfile`、`scripts/ci-motion-offline.sh`、
CI job `motion-canvas-offline`）：

1. 构建阶段允许联网；镜像内固定 Node 24.22.1、`npm ci`、Chromium、FFmpeg、
   Python 3.13。
2. 运行阶段 `docker run --network none`，执行真实渲染、编码、Gate 4 与
   `scripts/verify-offline-evidence.py`。
3. 负控制：同一容器内 `fetch(registry.npmjs.org)` 与 `npm install left-pad`
   必须失败；任一成功即 job 失败。
4. 请求审计：每个完成的构建必须记录外部请求尝试且失败数大于 0；否则
   断网未被证明。
5. 证据：镜像 ID、输入哈希、驱动报告、清单、视频与 JUnit 报告上传为
   `motion-canvas-offline-evidence`。

本机 Docker（Linux 容器）与 CI 的执行结果见 §4.3。

### 4.3 P1.4 执行记录（2026-10-22）

| 检查 | 环境 | 结果 | 状态 |
|---|---|---|---|
| 单元/契约测试（含 lockfile 与故障矩阵） | Windows 11，项目 `.venv` | `uv run pytest` → **295 passed, 5 skipped**；`ruff check .`、`ruff format --check .`、`mypy src` 全部通过 | PASS |
| 真实取消/超时 | CI run `39785216053` `motion-canvas-p1` | JUnit 11 / 0 failures；取消用例 6.0 s（首帧后取消），超时用例 2.1 s（1.5 s 期限） | PASS |
| 本机 Docker 断网门禁 | Docker Desktop 29.9.1（Linux 容器） | 构建长时间停在依赖安装阶段，未产出镜像；本机 P0 记录显示同一策略会把 `deb.debian.org` 解析到 `198.18.1.108` 并失败。本次未进入渲染阶段，手动终止 | BLOCKED |
| CI `motion-canvas-offline`（run `39784382250`） | GitHub Actions，main / commit `c8663de` | 镜像构建成功；负控制 `fetch_exit=1 npm_exit=1` 符合预期；但渲染在工具链门禁失败：Debian bookworm 的 FFmpeg 为 **5.1.9**，低于要求的 6.0 | FAIL |
| CI `motion-canvas-offline`（重跑，run `39785216053`） | GitHub Actions，commit `617c650`，trixie 镜像 `sha256:602d820a…141` | JUnit **11 tests / 0 failures / 30.8 s**；负控制 `fetch_exit=1 npm_exit=1`；Node `24.22.1`、npm `11.19.1`、Playwright `1.64.0`、FFmpeg `7.1.5`；两个完成的构建各记录 **4 次外部请求 / 4 次失败**；独立复核视频：30 帧 640×360 1.0 s、300 帧 1920×1080 10.0 s，`video_sha256` 与编码记录一致 | PASS |

本机 Docker 的失败不是门禁放宽的理由，也不构成 PASS。断网验收在 CI runner
上完成：镜像联网构建、容器断网运行，artifact `motion-canvas-offline-evidence`
留档。P1-GATE-13 以 run `39785216053` 记为 PASS。

同一次 run `39784382250` 的 `motion-canvas-p1` 还暴露了取消竞态：驱动在
进程组被终止时先写出 `render_failed`，适配器把它当成普通失败。修复见 §4.1
失败记录第三行；重跑 `39785216053` 的两个 motion job 均已通过。

## 5. 本轮变更

新增：

- `config/error_codes.json`：Python/Node 共用的失败码表。
- `src/content_studio/timeline.py`：MC-01 整数时间轴。
- `src/content_studio/motion_canvas.py`：适配器、环境探测、构建目录、
  驱动进程组管理、帧结构校验、显式注册表。
- `motion/`：固定版本 Node 工程（`.nvmrc`、`package.json`、lockfile、
  `driver.mjs`、`contract.mjs`、`contract.test.mjs`、`src/`）。
- `tests/test_timeline.py`、`tests/test_motion_canvas.py`、
  `tests/test_motion_canvas_e2e.py`、`tests/test_error_codes.py`。
- `schemas/scene_set.schema.json`、`schemas/frame_manifest.schema.json`。
- `src/content_studio/frame_manifest.py`：清单构建、独立校验、PNG 结构检查、
  FFmpeg 序列解码。
- `tests/test_frame_manifest.py`。
- `scripts/verify-frame-manifest.py`：独立于项目校验器的清单复核脚本，
  用于对 CI artifact 做全量哈希、PNG 结构、场景覆盖与解码检查。
- `src/content_studio/encode.py`：显式参数的 libx264 编码、编码证据。
- `src/content_studio/video_qa.py`：解码帧数、有理数帧率、尺寸、时长容差
  与整段解码校验。
- `tests/test_encode.py`、`tests/test_video_qa.py`；`tests/test_release.py`
  增加 Gate 4 用例；E2E 断言真实 MP4 与清单一致。

修改：

- `models.py`：`SceneContract.data`、`SceneSet`、`FrameEntry` /
  `SceneFrameSpan` / `FrameManifest`。
- `renderers.py`：`RenderResult`、`validate(..., context=...)`、
  `environment_error_code()`、注册表终态与错误码映射。
- `errors.py`：码表加载、`RenderError.code`、`RenderCancelled`。
- `visuals.py`：`animation` 资产映射；动画产物越界改为显式失败。
- `cli.py`：`lces render-scene`；`doctor` 增加 Motion Canvas 段；导出
  `scene_set` 与 `frame_manifest`。
- `pyproject.toml`：`motion` marker。
- `schemas/scene_contract.schema.json`、`schemas/README.md`、
  `docs/IMPLEMENTATION_STATUS.md`。
- `.gitignore`：忽略 `node_modules/`。
- `.github/workflows/ci.yml`：新增 `motion-canvas-p1` job。

P1.4 本轮新增：

- `src/content_studio/motion_canvas.py`：`dependency_problems()` 校验
  `package.json` / `package-lock.json` / 已安装直接依赖三者一致；
  环境失败码改为按具体原因返回（`dependency_mismatch`）。
- `tests/test_motion_canvas.py`：lockfile 校验用例与
  `test_every_failure_publishes_nothing` 故障矩阵（旧视频不变、
  不写 QA 证据）。
- `tests/test_motion_canvas_e2e.py`：真实取消（首帧后取消）与真实超时
  回归；E2E 现在写出并断言 `internal/qa/{frame_manifest,encode_report}.json`；
  `LCES_MC_OFFLINE=1` 时要求外部请求尝试存在且失败。
- `motion/offline.Dockerfile`、`.dockerignore`：固定工具链的断网镜像。
- `scripts/ci-motion-offline.sh`：容器内负控制、真实渲染/编码/Gate 4、
  证据收集。
- `scripts/verify-offline-evidence.py`：独立核对断网运行的外部请求失败、
  帧数与已发布视频。
- `scripts/collect-motion-evidence.py`：收集编码记录与项目 QA 副本，
  按相对路径生成唯一标签，避免多个 `qa` 目录互相覆盖。
- `.github/workflows/ci.yml`：新增 `motion-canvas-offline` job。
- `scripts/ci-local.sh`：新增 `offline` 模式；`full` 包含断网门禁。
- `docs/DEVELOPMENT.md`、`README.md`：同步命令与状态。

## 6. 未执行与阻塞

1. **本地 WSL 仍未执行**：本机是 Windows，P1 在入口拒绝；WSL 的 Node 22.22.2
   不满足 24.22.1。P1 的真实执行环境是 CI 的 Linux runner，本地不降低门禁。
   本机 Docker 使用 Linux 容器运行断网门禁，不等同于 Windows 原生支持。
2. **MC-04 视觉验收未实现**：空白帧检测、逐模板像素差分与人工抽检仍为
   `NOT_RUN`。P1.4 的故障矩阵不包含视觉质量结论，不能用渲染成功替代。
3. **跨环境可复现性（Level 3）未实测**：只验证了结构可复现与断网可运行；
   连续三次构建的字节一致率与视觉差分尚未记录。
4. Graphviz Windows 16.1.0 安装仍是独立待办，与本计划无关。

## 7. 已知偏差与决定

1. **规范里的“恰好一帧”边界例子实际是半帧。** 30 fps 下
   `5 帧 = 166.67 ms` 与契约 `150 ms` 相差 `16.67 ms`，是半帧而非一帧；
   通过/失败的结论不变（仍在 1 帧容差内）。测试按实际值断言，并在
   `tests/test_timeline.py` 注明。若要求更严格的边界描述，应修订
   `MOTION_CANVAS.md` §5.3，而不是改代码。
2. **FFmpeg 版本采用“下限 + 记录实际值”。** CI 是 6.1.1，本机是 8.1；
   精确锁定应放到 P1.3 的编码参数与证据里，否则会在不同发行版上制造假失败。
3. **冒烟配置不是生产验收。** CI 冒烟是 640×360 / 30 帧；生产规格
   1920×1080 / 300 帧作为独立验收项 P1-GATE-14 执行，冒烟通过不能替代。
4. **P1.1 不产出 MP4。** 因此 `build/media/course.mp4` 与发布路径未被触碰；
   发布隔离在 P1.3 验证。
5. **P1 只支持单场景 title。** 多场景、`flow`、`compare` 留给 P2；
   `SceneSet` 的结构已经按有序多场景设计，不需要改契约。
6. **`motion/` 与 `spike/` 的契约副本。** spike 保留为 P0 证据，不被导入；
   `motion/contract.test.mjs` 断言两份 `CODES`、`SUPPORTED_PLATFORMS` 一致，
   防止分叉。
7. **构建工程依赖软链，不是整份复制。** `node_modules` 以软链指回
   `motion/`；因此 Vite 必须显式放行该路径，导出目录必须是绝对路径。
   P1.2 增加 FrameManifest 时沿用同一构建目录约定。
8. **清单路径以构建目录为根。** 导出器会把帧放在 `frames/<project>/`
   子目录，清单记录 `frames/project/000000.png`；`verify` 用同一根解析，
   避免路径两套解释。
9. **编码只写 staging，正式路径只做 `os.replace`。** staging 目录位于
   `build/media/.staging-<build_id>/`（同一文件系统），失败时保留但带
   `.staging-` 前缀，不进入发布；旧 `course.mp4` 只有在帧清单、视频一致性
   与解码全部通过后才会被替换。
10. **Gate 4 在缺少清单时只 warn。** 兼容还没有视频清单的旧项目；一旦
   存在 `internal/qa/frame_manifest.json`，视频不一致或编码记录哈希不符
   就是阻断性失败。
11. **外部字体与编辑器自检请求仍会发生。** 它们不阻断渲染（P0 断网时也成功
   产出 300 帧），因此断网证据不要求请求为空，而要求请求**尝试失败**，
   并与容器级负控制互为佐证。
12. **依赖树必须与 lockfile 一致。** `npm install` 可以改写直接依赖而
   `package.json` 看起来没变；适配器在渲染前比较声明、lockfile 与已安装
   版本，任一不一致即 `dependency_mismatch`，不降级为 `environment_unavailable`。
13. **断网门禁用独立容器，不在 `motion-canvas-p1` job 内。** GitHub 容器 job
   无法嵌套 `docker --network none`；离线 job 在宿主机 runner 上构建镜像，
   再以断网容器运行同一套真实测试与负控制。两者都必须绿，不能互相替代。
14. **证据收集按相对路径命名。** E2E 与 Gate 4 都会产生
   `frame_manifest.json`，只按目录名收集会让多个 `qa` 目录互相覆盖；
   收集器现在保留路径前缀，并同时收集编码记录与项目 QA 副本。

## 8. 运行方式

推送前先跑本地门禁（命令与 CI 相同，脚本不安装任何东西）：

```bash
./scripts/ci-local.sh fast     # 任意平台
./scripts/ci-local.sh render   # Linux/WSL2，Node 24.22.1 + Chromium + FFmpeg
./scripts/ci-local.sh offline  # Docker：构建镜像后用 --network none 运行
./scripts/ci-local.sh full     # fast + render + offline + browser QA
```

```bash
# 本机（任意平台）：只跑契约与拒绝路径
uv run pytest
uv run lces render-scene projects/example-course var/p1/scene.json --out var/p1/build
# Windows 期望：退出码 2，unsupported_platform，不产生构建目录

# Linux / WSL2（Node 24.22.1，Chromium，FFmpeg 由用户维护）
cd motion && npm ci && npm rebuild esbuild && npx playwright install chromium
cd .. && LCES_MC_E2E=1 uv run pytest -m motion -v   --basetemp=motion-evidence/tmp --junitxml=motion-evidence/e2e-report.xml
# Node 契约（需要 Chromium）
cd motion && node --test --test-reporter=tap contract.test.mjs
```
