# Motion Canvas P1 实施计划与准入验收表

日期：2026-10-22
范围：P1（Linux / WSL2），`title` 最小原型。
前置：P0 结论 **GO（仅 Linux）**，CI run `39752667833`；详见
`docs/design/motion-canvas-spike.md`、`docs/design/MOTION_CANVAS.md`。

本文是 P1 的实施依据。它冻结接口决策，并记录每条验收的实际状态；
状态只有四种：`NOT_RUN`、`PASS`、`FAIL`、`BLOCKED`。
未执行的检查不得记为 `PASS`；CI job 的总体成功不得代替逐条断言。

**当前状态（2026-10-22）**：P1.1 已在 Linux CI 通过真实渲染
（run `39762458701`，commit `c9d31af`，job `motion-canvas-p1` 全绿）；
P1.2–P1.4 尚未开始。

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

## 3. 阶段与完成条件

| 阶段 | 内容 | 完成条件 |
|---|---|---|
| P1.1 | 接口、时间轴、平台/版本门禁、取消、CLI、真实渲染 | 真实 title 场景帧数与分辨率正确；错误版本、错误平台被拒绝 |
| P1.2 | FrameManifest、PNG 结构、哈希、场景边界、路径约束 | 清单可独立证明帧连续、有效、覆盖完整 |
| P1.3 | FFmpeg 编码、ffprobe、解码、时长/帧数一致、原子替换 | 通过全部校验才替换；失败时旧文件哈希不变 |
| P1.4 | 故障注入与持续集成 | 每个故障都有结构化错误、唯一终态、不可发布；PR 跑真实渲染 |

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
| P1-GATE-11 | FrameManifest（P1.2） | — | 未实现 | — | NOT_RUN |
| P1-GATE-12 | 编码与原子发布（P1.3） | — | 未实现 | — | NOT_RUN |
| P1-GATE-13 | 故障注入（P1.4） | — | 未实现 | — | NOT_RUN |

`BLOCKED` 的含义是：验收本身已定义、可执行，但当前环境不满足；
它不是通过，也不是失败。

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
- `schemas/scene_set.schema.json`。

修改：

- `models.py`：`SceneContract.data`、`SceneSet`。
- `renderers.py`：`RenderResult`、`validate(..., context=...)`、
  `environment_error_code()`、注册表终态与错误码映射。
- `errors.py`：码表加载、`RenderError.code`、`RenderCancelled`。
- `visuals.py`：`animation` 资产映射；动画产物越界改为显式失败。
- `cli.py`：`lces render-scene`；`doctor` 增加 Motion Canvas 段；导出 `scene_set`。
- `pyproject.toml`：`motion` marker。
- `schemas/scene_contract.schema.json`、`schemas/README.md`、
  `docs/IMPLEMENTATION_STATUS.md`。
- `.gitignore`：忽略 `node_modules/`。
- `.github/workflows/ci.yml`：新增 `motion-canvas-p1` job。

## 6. 未执行与阻塞

1. **本地 WSL 仍未执行**：本机是 Windows，P1 在入口拒绝；WSL 的 Node 22.22.2
   不满足 24.22.1。P1 的真实执行环境是 CI 的 Linux runner，本地不降低门禁。
2. **P1.2–P1.4 未实现**：FrameManifest、编码、原子发布、故障注入。
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
3. **P1.1 不产出 MP4。** 因此 `build/media/course.mp4` 与发布路径未被触碰；
   发布隔离在 P1.3 验证。
4. **P1 只支持单场景 title。** 多场景、`flow`、`compare` 留给 P2；
   `SceneSet` 的结构已经按有序多场景设计，不需要改契约。
5. **`motion/` 与 `spike/` 的契约副本。** spike 保留为 P0 证据，不被导入；
   `motion/contract.test.mjs` 断言两份 `CODES`、`SUPPORTED_PLATFORMS` 一致，
   防止分叉。
6. **构建工程依赖软链，不是整份复制。** `node_modules` 以软链指回
   `motion/`；因此 Vite 必须显式放行该路径，导出目录必须是绝对路径。
   P1.2 增加 FrameManifest 时沿用同一构建目录约定。
7. **外部字体与编辑器自检请求仍会发生。** 它们不阻断渲染（P0 断网时也成功
   产出 300 帧），但属于 P1.4 的离线证据范围，不能因为本次 CI 通过而记为
   离线已验收。

## 8. 运行方式

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
