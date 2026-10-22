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
commit `cdce036`）；P1.3 已实现（编码、视频/清单一致性、原子发布、Gate 4），
正在等待本阶段 CI 证据；P1.4 尚未开始。

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
| P1-GATE-12 | 编码与原子发布（P1.3） | `LCES_MC_E2E=1 uv run pytest tests/test_motion_canvas_e2e.py -v` | 已实现：`build/media/.staging-<build_id>/` 编码 → 视频/清单一致性 → `os.replace`；失败保留旧 `course.mp4`（单元测试） | 等待 CI | NOT_RUN |
| P1-GATE-15 | Gate 4 独立核对（P1.3） | `uv run pytest tests/test_release.py -k gate4` | 已实现：重读 release 视频与 `internal/qa/{frame_manifest,encode_report}.json`，比较帧数/帧率/尺寸/时长/哈希 | 等待 CI | NOT_RUN |
| P1-GATE-13 | 故障注入（P1.4） | — | 未实现 | — | NOT_RUN |
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

两次失败都不是“放宽断言”解决的；修复后的断言与 P1.1 完成条件一致。

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

## 6. 未执行与阻塞

1. **本地 WSL 仍未执行**：本机是 Windows，P1 在入口拒绝；WSL 的 Node 22.22.2
   不满足 24.22.1。P1 的真实执行环境是 CI 的 Linux runner，本地不降低门禁。
2. **P1.4 未实现**：断网与负控制、完整故障注入矩阵、取消/超时端到端回归。
3. **离线隔离尚未由操作系统证明**：本次渲染记录了 6 个外部请求
   （fonts.googleapis/gstatic、unpkg highlight.js、npm registry），
   本次网络可用、请求成功。P0 的 `--network none` 证据不能自动继承到 P1；
   P1.4 必须重新做断网与负控制。
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
   产出 300 帧），但属于 P1.4 的离线证据范围，不能因为本次 CI 通过而记为
   离线已验收。

## 8. 运行方式

推送前先跑本地门禁（命令与 CI 相同，脚本不安装任何东西）：

```bash
./scripts/ci-local.sh fast     # 任意平台
./scripts/ci-local.sh render   # Linux/WSL2，Node 24.22.1 + Chromium + FFmpeg
./scripts/ci-local.sh full     # fast + render + browser QA
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
