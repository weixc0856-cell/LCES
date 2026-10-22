# Motion Canvas P0 可行性验证记录

日期：2026-10-22
状态：**已完成；本轮结论 NO_GO（本环境离线隔离受阻）**
范围：可行性实验，不进入 `renderers/` 生产路径，不修改用户项目文件。

## 1. 结论

- 官方 headless API：**未发现**。核心包只导出 `Renderer` 与 `ImageExporter`，
  帧数据通过 Vite HMR 事件 `motion-canvas:export` 写给 dev server。
- 编辑器驱动：**技术上可驱动，但不是官方稳定 API**。在锁定 3.17.2 下可观察到
  明确信号（见 §4），依赖 DOM 文本与 CSS 状态，升级必须重新验证。
- 离线：**未能证明**。Docker `--network none` 隔离机制本身可用，但本环境无法
  构建包含 Chromium 的离线镜像（apt 连接 deb.debian.org 失败）。按约定门禁，
  离线未闭环 → **NO_GO**，不允许用 CONDITIONAL_GO 跳过。
- 资源：1080p / 30 fps / 10 s，300 帧，约 5.5 s，峰值内存约 302 MB，
  帧序列磁盘 17.2 MB。
- 帧数：显式 range（帧 299）可精确得到 300 帧；全范围会多出 2 帧（302）。

本轮 NO_GO 是对**实验环境**的结论，不是对 Motion Canvas 本身的最终否定。
在具备正常网络构建能力的环境重跑 §10 的离线步骤后，可重新决策。

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
- **建议契约**：rendering = `Abort` 存在于 DOM 且帧数增长；
  completed = `Abort` 消失 + `RENDER` 存在 + 帧数连续 2 次不变 + 帧数等于
  MC-01 计算值。任一信号缺失或选择器不匹配 → `driver_protocol_mismatch`。

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

## 7. 离线隔离（P0-3：BLOCKED）

编辑器默认请求（host 实测）：

- `fonts.googleapis.com`（Roboto、JetBrains Mono CSS）
- `fonts.gstatic.com`（woff2）
- `unpkg.com/highlightjs@9.16.2/styles/atom-one-dark.css`
- `registry.npmjs.org/@motion-canvas/core/latest`

隔离机制验证（通过）：

```text
docker run --rm --network none node:24.22.1-bookworm-slim \
  node -e "fetch('https://registry.npmjs.org').then(...).catch(...)"
→ OFFLINE_OK TypeError
```

其中 `198.18.1.108` 是本机网络环境对 `deb.debian.org` 的解析/代理地址。apt 在
下载到第 97/111 个包后开始出现 `Unable to connect ... [IP: 198.18.1.108 80]`，
最终 `E: Unable to fetch some archives`，`playwright install --with-deps`
退出码 100，镜像构建失败。

构建包含 Chromium 的离线镜像在本环境无法完成，因此：

- **没有**完成的离线渲染证据；
- **没有**完成负控制（断网安装未缓存依赖失败）；
- 不以浏览器请求日志替代操作系统级隔离证据。

阻塞证据：`var/spike/evidence/docker-build-failure.txt`（构建日志尾部）。
网络恢复或改用可正常访问 Debian 源的构建环境后，按 §10 重跑。

## 8. 证据路径

- 证据目录：`var/spike/evidence/`
  - `editor-initial.png`、`editor-30fps-10s-after.png`、
    `editor-300frames-after.png`
  - `good-frame.png`、`corrupt-frame.png`
  - `docker-build-failure.txt`（apt 失败日志）
  - `user-home-motion-canvas-settings.created-by-spike.json`
- 工程与运行时：`var/spike/motion-canvas-standalone/`、
  `var/spike/node-v24.22.1/`、`var/spike/npm-cache/`、`var/spike/docker/`
- 全部位于 `var/`（gitignored），不进入生产路径。

副作用说明：首次打开编辑器时，Motion Canvas 在
`C:\Users\99236\.motion-canvas\settings.json` 写入了 214 字节的默认设置
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

**NO_GO（本环境本轮）**。

理由：P0 的硬性门槛包含"可证明的离线渲染"。本轮：

- 驱动信号：有可用的受控信号（§4），但非官方 API；
- 离线：隔离机制可用，但构建离线镜像失败（§7），无证据；
- 输出完整性：帧数、解码、取消、损坏输出均已实测（§5/§6）。

按既定门禁，网络隔离不允许用 CONDITIONAL_GO 跳过，因此本轮只能判 NO_GO。
这不是"Motion Canvas 不可用"的结论，而是"在本机网络环境下 P0 未闭环"。

### 重跑条件（满足后重新决策）

1. 构建环境能正常访问 Debian 源与 npm registry；
2. 成功构建含 Node 24.22.1 + Chromium + 依赖的镜像；
3. 在 `docker run --network none` 下完成 300 帧渲染，帧数/尺寸/时长通过；
4. 断网安装未缓存依赖的负控制失败；
5. 浏览器请求日志仅包含 `file:`/`data:`/`blob:`/`127.0.0.1`。

满足 1–5 后，若驱动协议仍依赖 DOM 文本，最多可判 `CONDITIONAL_GO`，
条件为：锁定版本、UI 变化即失败、每次升级重跑驱动契约测试。

### 重跑所需材料

- `var/spike/docker/`（Dockerfile 与 driver.mjs）
- `var/spike/motion-canvas-standalone/`（工程、lockfile、300 帧配置）
- `var/spike/node-v24.22.1/`（精确 Node 运行时）
