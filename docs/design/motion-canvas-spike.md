# Motion Canvas P0 可行性验证记录

日期：2026-10-22
状态：**已完成；结论 CONDITIONAL_GO（CI/Linux），未进入生产**
范围：可行性实验，不进入 `renderers/` 生产路径，不修改用户项目文件。

## 1. 结论

- 官方 headless API：**未发现**。核心包只导出 `Renderer` 与 `ImageExporter`，
  帧数据通过 Vite HMR 事件 `motion-canvas:export` 写给 dev server。
- 编辑器驱动：**可稳定驱动，但不是官方 API**。锁定 3.17.2 下的信号已由 CI
  验证（见 §4/§7），依赖 DOM 文本，升级必须重跑协议测试。
- 离线：**CI 已证明**。镜像在正常网络下构建，渲染在
  `docker run --network none` 中完成；负控制（`fetch` 与 `npm install`）均失败。
- 资源：1080p / 30 fps / 10 s，300 帧，**4.71 s**，容器内存上限 768 MB；
  帧序列可全部解码，尺寸 1920×1080。
- 帧数：显式 range（帧 299）精确得到 300 帧；全范围会多出 2 帧（302）。
- 决策：**CONDITIONAL_GO**，条件见 §10。未进入 P1 的正式实现。

## 2. 环境与依赖（P0-1）

| 项 | 值 |
|---|---|
| OS | Windows 11 Pro 10.0.26300，x64 |
| Node.js | 24.22.1（项目内运行时，来自 nodejs.org） |
| Node ZIP sha256 | `d2046d28c2c3dcd211ac5145c0bf30e2047ef9dfb306693c8c6e2eccd8b95fa5` |
| npm | 11.19.1 |
| Motion Canvas | core / 2d / ui / vite-plugin 均为 **3.17.2** |
| Vite | 4.5.14 |
| TypeScript | 5.9.3 |
| 浏览器 | Playwright Chromium build 1248（156.0.8078.4） |
| FFmpeg | 8.1-full_build-www.gyan.dev |
| 模板来源 | `@motion-canvas/create@3.17.2` 内置 `template-2d-ts`，commit `e735a995aa738ca682feb4204a39ee7db7b5d279` |

安装结果：

- `npm install` 67 packages，18 s；`npm ci` 7 s，均成功。
- `package-lock.json` sha256：`c24d7c61a278422220ac9d0bad1279d1073d08dec2afa23367d526438843e0ce`
- 锁文件 89 个包，**全部带 integrity**；许可证分布：MIT 78、Apache-2.0 5、
  ISC 3、BSD-3-Clause 2、BSD+Apache 1。
- npm 11 默认阻止 esbuild 的 postinstall；需在 package.json 写入
  `allowScripts: {"esbuild@0.18.20": true}` 后 `npm rebuild esbuild`。
  这是安装期必须显式处理的步骤。

CI 环境（run `39752667833`，Ubuntu runner）：

| 项 | 值 |
|---|---|
| Node / npm | v24.22.1 / 11.19.1 |
| Playwright | 1.64.0 |
| FFmpeg | 6.1.1-3ubuntu5 |
| 镜像 ID | `sha256:5aaa2065fe2b971cd0c3928403587aade87897e7f4219a558a3a381c27cf2250` |
| 输入哈希 | lock `c24d7c61…`；Dockerfile `8b6327f2…`；driver `693c1408…` |

本机 Docker 构建曾因 apt 无法访问 deb.debian.org（解析到 `198.18.1.108`）
失败；CI 正常网络下构建成功，说明阻塞在本机网络，而非镜像定义。

## 3. 官方 API 调查（P0-2）

源码（tag v3.17.2）观察：

- `packages/core/src/app/Exporter.ts`、`ImageExporter.ts`、`Renderer.ts` 存在。
- `ImageExporter` 通过 `import.meta.hot.send('motion-canvas:export', ...)` 把帧
  交给 Vite 插件；插件写入 `output/<project>/<frame>.png`。
- 没有导出的 `renderVideo` 或独立 headless 入口。

结论：**headless 渲染必须同时运行 Vite dev server 与浏览器**；官方未提供可
长期依赖的程序化接口。

## 4. 编辑器驱动信号

在 3.17.2 + Chromium 下实测：

| 状态 | 可观察信号 |
|---|---|
| idle | `RENDER` 按钮存在且可用；无 `ETA:` 文本 |
| rendering | `Abort` 按钮出现；body 出现 `ETA: hh:mm:ss`；存在 `loading` 类；帧数持续增长 |
| completed | `Abort` 消失、`RENDER` 回来；帧数在连续采样中不再增长 |
| cancelled | 点击 `Abort` 后同上，但帧数少于预期且保留部分帧 |

采样陷阱（实测）：

- 用 `locator("button").all()` + `inner_text()` 轮询，曾在 1.0 s 漏掉
  `Abort`；改用 `page.evaluate` 直接读取 DOM 后，100 ms 采样稳定。
- body 级 `ETA` 正则可能在结束后短暂残留；完成判定不能只依赖“无 ETA”。
- 按钮的 DOM 文本是 **`Render` / `Abort`**，大写只是 CSS `text-transform`。
  Playwright 的 `innerText` 返回大写，而 JS `textContent` 返回原始大小写；
  早期驱动用 `textContent === "RENDER"` 判断，导致离线渲染已产出 300 帧却
  被误判为未完成。判定必须大小写不敏感，并在协议测试中锁定。
- **建议契约**：rendering = `Abort` 存在于 DOM 且帧数增长；
  completed = `Abort` 消失 + `RENDER` 存在 + 帧数连续 2 次不变 + 帧数等于
  MC-01 计算值。两个控件同时存在 → `driver_protocol_mismatch`；
  两者都缺失 → 显式 `transition`（非终态，绝不视为完成）。
  任一信号缺失或选择器不匹配 → `driver_protocol_mismatch`。

## 5. 时间轴与帧数（P0-2/P0-4）

- 默认渲染帧率为 **60**，项目级 `src/project.meta` 的 `rendering.fps` 优先于
  全局设置。
- `shared.range` 在 meta 文件中以**秒**存储；UI 输入以**帧**显示。
- 4.03 s 全范围：242 帧（60 fps），与 60 fps 一致。
- 10.03 s 全范围：302 帧（30 fps）。
- 将 range end 设为帧 299（meta 秒值 `299/30`）后：**300 帧整**，
  与 MC-01 的 `round(10000 ms × 30 / 1000) = 300` 一致。
- 结论：LCES 必须显式写入 range（秒）并校验帧数；不能依赖“全范围”。

## 6. 资源与失败注入（P0-4）

1080p / 30 fps / 10 s / 300 帧：

| 指标 | 结果 |
|---|---|
| 帧数 | 300（显式 range） |
| 帧序列磁盘 | 17.2 MB |
| 渲染耗时 | 约 5.5 s（Abort→RENDER 状态切换） |
| 峰值内存 | 约 302 MB（Playwright Chromium + Node，按路径过滤，仅本项目进程） |

失败注入：

- **取消**：渲染至 83 帧时点击 Abort，最终 88 帧（在途帧落地），
  `RENDER` 返回、`Abort` 消失。部分帧留在 `output/`，**必须隔离，不得发布**。
- **超时**：1 s 超时模拟中，按钮文本轮询不可靠；DOM 信号可用。
  超时后应主动 Abort 并保留证据。
- **损坏输出**：截断 PNG 后，`ffprobe` **退出码 0** 但 `width=0,height=0`；
  `ffmpeg` 解码退出码 **69**。结论：不能只看退出码，必须校验尺寸、像素解码
  与帧清单。
- **缺少依赖**：移除 `@motion-canvas/vite-plugin` 后，导入报
  `Cannot find package '@motion-canvas/vite-plugin'`，错误明确。

## 7. 离线隔离（P0-3：PASS，CI）

编辑器默认请求（实测）：

- `fonts.googleapis.com`（Roboto、JetBrains Mono CSS）
- `fonts.gstatic.com`（woff2）
- `unpkg.com/highlightjs@9.16.2/styles/atom-one-dark.css`
- `registry.npmjs.org/@motion-canvas/core/latest`

CI run `39752667833` 在 `docker run --network none` 中完成真实渲染：

| 指标 | 结果 |
|---|---|
| 帧数 | **300** |
| 渲染耗时 | **4.71 s** |
| 尺寸 | 1920×1080，PNG，全帧 `ffmpeg` 解码通过 |
| 外部请求 | 4 次尝试，**全部失败**（`ERR_INTERNET_DISCONNECTED`） |
| 负控制 | `fetch_exit=1`、`npm install left-pad` `npm_exit=1` |
| 隔离范围 | 渲染容器本身（Vite + Chromium 同一容器） |

请求审计来自驱动记录（`report.json` 的 `external_requests` 与
`request_failures`），与操作系统级禁网互为佐证；不单独以日志代替隔离。
本机 Docker 构建失败记录（apt 连接 `198.18.1.108`）保留为历史证据
`var/spike/evidence/docker-build-failure.txt`；CI 正常网络下构建成功。
证据 artifact：`motion-canvas-p0-evidence`（run `39752667833`）。

> P0 的断网结论不能自动继承到 P1。P1.4 已在 P1 适配器上重新执行断网渲染、
> 编码与负控制，见 `docs/design/motion-canvas-p1-plan.md` §4.2。

## 8. 证据路径

- CI artifact：`motion-canvas-p0-evidence`（run `39752667833`）
  - `render/report.json`、`frame-count.txt`、`frame-info.txt`、`decode.log`
  - `cancel/report.json`、`timeout/report.json`
  - `negative-control.txt`、`image-id.txt`、`input-hashes.txt`、版本文件
  - 本地副本：`var/spike/evidence/motion-canvas-p0-ci/`
- 本机证据：`var/spike/evidence/`
  - `editor-initial.png`、`editor-300frames-after.png`、
    `offline-blocked-after.png`
  - `good-frame.png`、`corrupt-frame.png`
  - `docker-build-failure.txt`（本机构建阻塞记录）
  - `user-home-motion-canvas-settings.created-by-spike.json`
- 受控实验工程：`spike/motion-canvas/`（已入库）
- 本机运行时/缓存：`var/spike/node-v24.22.1/`、`var/spike/npm-cache/`
  （gitignored）

副作用说明：首次打开编辑器时，Motion Canvas 在
`%USERPROFILE%\.motion-canvas\settings.json` 写入了 214 字节的默认设置
（创建时间 2026-10-22 15:05，内容仅 appearance/defaults）。该文件已在上述
证据目录留档；后续实验均使用沙箱 `USERPROFILE`，未再触碰用户目录。
未删除该文件，交由用户决定是否保留。

## 9. 对设计的影响

1. `shared.range` 用秒、UI 用帧：LCES 必须统一到 MC-01 的帧边界，再换算秒。
2. 全范围会多出约 1–2 帧：必须显式设置 range 并校验帧数。
3. 完成信号为 DOM/文本，不是官方 API：驱动协议必须锁定版本并显式失败。
4. `ffprobe` 对损坏 PNG 可能返回 0：输出校验必须检查尺寸与解码。
5. 编辑器有外部资源请求：离线渲染必须先证明可断网运行，或替换字体/样式。

## 10. 决策（P0-5）

**GO（仅 Linux）** —— P1 准入范围由方案 B 确定（2026-10-22）。

已通过的强制门槛（run `39752667833`）：

- 离线渲染：`--network none` 下 300 帧、4.71 s、全帧解码、1920×1080；
- 网络负控制：`fetch` 与 `npm install` 均失败（exit 1）；
- 请求审计：4 次外部尝试全部失败；
- 取消：95 帧后 Abort，状态 `cancelled=true`；
- 超时：76 帧时检测到并停止，`timed_out=true`；
- 输出完整性：帧数、尺寸、解码、截图与报告已归档；
- 资源上限：容器 `--memory=768m` 下完成渲染；
- UI 契约：run `39752667833` **11/11**（DOM、状态转换、产物、负向用例）。

判为 GO 的前提是**范围限定为 Linux**：驱动依赖 DOM 文本，只在 Linux CI 验证过。
Windows 不在 P1 范围；P1 入口必须显式拒绝非 Linux 平台
（`assertSupportedPlatform`，错误码 `unsupported_platform`），不得让 Windows
路径“看起来可用”却在运行时失败。

### 条件（进入 P1 前/期间必须满足）

1. **平台门禁**：P1 入口调用 `assertSupportedPlatform(process.platform)`；
   非 Linux 立即失败。已实现于 `contract.mjs`，P1 必须使用。
2. **UI 契约测试**：`contract.test.mjs` 覆盖选择器/状态机/产物；3.17.2 之外的
   版本一律 `driver_protocol_mismatch`，不得用启发式猜测。
3. **版本变更即重跑 P0**：Node、Motion Canvas、Chromium、FFmpeg 任一升级，
   重新执行本 CI 工作流并保留 artifact。
4. **不进入生产**：P1 原型通过相同门禁前，不得写入 `renderers/` 或发布路径。
5. **Windows 另立准入**：需要新的 P0（断网、负控制、完整清单）并重新判定，
   旧版本的 Linux 结果不自动继承。

### 撤销条件

出现任一情况立即回到 NO_GO：离线渲染失败、完成信号无法判定、取消后产生可发布
产物、帧数/解码校验失败、负控制意外成功。

### 重跑材料

- 受控工程：`spike/motion-canvas/`（源码、lockfile、Dockerfile、driver、contract）
- CI 工作流：`.github/workflows/motion-canvas-p0.yml`（手动触发）
- 本机实验残留（gitignored）：`var/spike/`

## 11. P1 准入任务（P1-GATE）

| 任务 | 内容 | 状态 |
|---|---|---|
| P1-GATE-01 | UI 驱动契约测试 | **已实现**；CI run `39752667833` **11/11**（`--network none`），Windows 主机 11/11 |
| P1-GATE-02 | Windows 本地重跑 | **Out of scope**（方案 B：P1 仅 Linux）；本地 Linux 使用 WSL2 Ubuntu 24.04，环境由用户维护；Windows 清单保留供未来准入 |
| P1-GATE-03 | 准入决策记录 | **已更新**：方案 B，仅 Linux |

### P1-GATE-01：契约测试范围

`contract.mjs` 统一驱动与测试使用的判定逻辑；`contract.test.mjs` 在真实
编辑器构建上运行，失败映射到 `driver_protocol_mismatch`、`frame_mismatch`、
`output_corrupt`。

| 层级 | 覆盖 | 负向用例 |
|---|---|---|
| DOM 契约 | Render/Abort 存在与消失、ETA、loading | Render 与 Abort 同时存在/同时缺失 → 失败，不猜测 |
| 状态转换 | idle → rendering → completed；rendering → cancelled/timeout | ETA 残留不得判定为渲染中或完成 |
| 产物契约 | 300 帧、1920×1080、PNG 头、辅助文件排除、发布目录不变 | 帧数不足、截断 PNG、取消/超时后不得发布 |

测试运行方式（CI，`--network none`）：

```powershell
docker run --rm --network none --memory=768m `
  -v "$PWD/evidence/contract:/app/output" `
  --entrypoint node lces-mc-p0 `
  --test --test-reporter=tap contract.test.mjs
```

CI 契约结果（run `39752667833`）：**11 tests / 11 pass / 0 fail**，
TAP 归档为 `contract-tests.tap`；同一轮离线渲染、负控制、取消、超时全部通过。

Windows 主机部分结果（2026-10-22，**非断网**）：`node --test contract.test.mjs`
**11/11 通过**（约 61–74 s）；`node driver.mjs` 渲染 **300 帧 / 5.45 s**。该运行
证明契约与驱动在 Windows 主机可工作，但不构成 Windows 断网/负控制证据。

### P1-GATE-02：Windows 范围

`docs/design/motion-canvas-windows-validation.md` 是执行模板，当前为 0/12。
Windows 原生验证未完成前：

- 不得声称 Windows 受支持；
- 不得让 Windows 入口“看起来可用”；
- 若选择仅 Linux，必须在 P1 入口显式拒绝 Windows 并写入支持矩阵。

### 准入规则

- 方案 A：Windows 与 Linux 强制项全部通过 → 未采用。
- **方案 B（已选择）：P1 仅 Linux** —— 入口显式拒绝 Windows
  （`unsupported_platform`）；文档、CI、发布范围均限定 Linux。
- 两者都不满足 → 保持 `CONDITIONAL_GO`，不进入生产。

P1 原型（title 场景）可以在 Linux 范围内开始；本地使用 WSL2 Ubuntu 24.04，
Node/Chromium/FFmpeg 由用户维护（LCES 不自动安装）。Windows 支持需要新的 P0
与重新准入。
