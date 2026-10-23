# Motion Canvas P2.3-D：渲染期网络边界

日期：2026-10-23
基线：`feat/motion-canvas-p2.3-c`（P2.3-C 供应链固定）
范围：只解决渲染期的浏览器网络访问边界。不涉及多场景、字体内嵌、资源配额或平台扩展。

## 1. 威胁模型与边界

| 层级 | 控制 | 证明方式 |
|---|---|---|
| 浏览器页面请求 | 驱动在首次导航前安装 local-only 路由 | 每次构建的 `report.json`：`blocked_requests`、`blocked_count`、`request_failures` |
| 进程树整体外联 | 现有 `--network none` 离线 job / 离线镜像 | 负控制 `fetch_exit=1 npm_exit=1`；P1.4 起保留 |

**明确边界**：Playwright 的 `page.route` 只约束页面发起的 HTTP(S) 请求，
**不是**操作系统级隔离，也不能证明 Vite、Node 或其它子进程无法联网。
OS 级断网仍由 `motion-canvas-offline` job 证明；两者结论不可互相替代。

## 2. 规则

允许：

- 编辑器自身 origin：`http://127.0.0.1:9000`（Vite 只在回环地址监听）；
- `data:`、`blob:`、`file:` 方案。

其余一律 `route.abort('blockedbyclient')`，同时记录一条
`{origin, path, type, reason}`：

- 只记 origin 与 path，**丢弃 query、fragment 与凭据**（report 会作为 CI
  artifact 上传）；
- path 截断到 80 字符；
- 不记录请求头、cookie、响应内容。

编辑器已知会发起的四条外部请求（P2.3-C 离线证据实测）：

1. `https://fonts.googleapis.com/css2?family=Roboto…`
2. `https://fonts.googleapis.com/css2?family=JetBrains+Mono…`
3. `https://unpkg.com/highlightjs@9.16.2/styles/atom-one-dark.css`
4. `https://registry.npmjs.org/@motion-canvas/core/latest`

前三条是编辑器界面样式，第四条是更新检查；都不参与画布渲染。

**未覆盖**：WebSocket（Vite HMR 使用 `ws://127.0.0.1:9000`，Playwright 的
`page.route` 不拦截 WS；目标是回环地址）。若将来引入外部 WS，需要
`page.routeWebSocket` 或等价的单独控制与测试。

## 3. 字体回退的确定性

Motion Canvas 的 2D `View2D` 默认 `fontFamily: 'Roboto'`，而 Roboto 来自被拦截的
Google Fonts；断网时浏览器会自行回退，结果依赖宿主已装字体。

P2.3-D 的做法：

- 生成场景时显式写入固定字体栈
  `'DejaVu Sans', 'Liberation Sans', Arial, sans-serif`
  （`motion_templates.SCENE_FONT_FAMILY`），不依赖任何网络字体；
- 适配器通过 `MC_SCENE_FONT` 把同一串传给驱动；
- 驱动在渲染前用 `document.fonts.check()` 探测该栈，把
  `scene_fonts: {requested, available, named_available}` 写进报告；
- **没有任何具名字体可用时以 `environment_unavailable` 失败**（通用 `sans-serif`
  总会解析，不能作为证据），不允许静默渲染成缺字方块。

镜像内的可用字体（`fc-list` 实测）：DejaVu Sans、Liberation Sans、FreeSans、
IPAGothic、Unifont、WenQuanYi Zen Hei（中文）。因此镜像内该栈必然可解析；
Windows 宿主依赖 Arial 等本地字体，具体可用项记录在每次构建的报告里。

字体栈不承诺跨 OS 的字节级一致（Level 3），只承诺“不回退到网络字体、不静默缺字”。

## 4. 代码与测试

| 位置 | 作用 |
|---|---|
| `motion/network-policy.mjs` | `isAllowedUrl` / `describeRequest` / `installLocalOnlyPolicy` |
| `motion/network-policy.test.mjs` | 允许/拒绝矩阵、去 query、截断、伪造 page/route 的 continue/abort 断言 |
| `motion/driver.mjs` | 首次导航前安装策略；字体探测；报告新增 `network_policy`、`blocked_requests`、`blocked_count`、`scene_fonts`（report schema 1.1） |
| `src/content_studio/motion_templates.py` | `SCENE_FONT_FAMILY` + 所有 `Txt` 显式 `fontFamily={FONT}` |
| `src/content_studio/motion_canvas.py` | `MC_SCENE_FONT` 传给驱动 |
| `tests/test_motion_canvas_e2e.py` | N15：真实构建必须 `blocked_count > 0`、`request_failures > 0`、被拦截项不含回环 origin、path 不含 query/fragment；`scene_fonts.available` 非空 |
| `tests/test_motion_canvas.py` | 三个模板的生成源码都带固定字体栈且不含 `Roboto` |

Node 测试并入 `npm test`、CI 的 Node contract 步骤与 `scripts/ci-local.sh render`。

## 5. 负向测试映射

| ID | 用例 | 预期 |
|---|---|---|
| N15 | 真实渲染（联网 CI 与本机离线镜像） | 四条外部请求全部被浏览器拦截；构建成功；`blocked_count > 0`、`request_failures > 0`；字体栈至少解析出一个 |
| N15-b | 无可用场景字体 | `environment_unavailable`，不写视频；由字体探测分支与单测覆盖 |
| N15-c | 允许项误伤 | 编辑器 origin、data/blob/file 必须 `continue`；单测覆盖 |

## 6. 实施记录（本机；CI 待执行）

**实现**

- `motion/network-policy.mjs`：`isAllowedUrl`、`describeRequest`、
  `installLocalOnlyPolicy`；
- `motion/driver.mjs`：首次导航前安装策略；报告 schema 1.1 新增
  `network_policy`、`blocked_requests`、`blocked_count`、`scene_fonts`；
- 三个模板的所有 `Txt` 显式 `fontFamily={FONT}`，适配器经 `MC_SCENE_FONT`
  传入同一字体栈；
- Node 测试并入 `npm test`、CI 的 contract 步骤与 `ci-local.sh render`。

**本机离线门禁（Windows 11，Docker 29.9.1）**

- 用 digest 固定的 base image 与 Node SHA-256 重建 `lces-motion-offline-d`
  （`sha256:853b9c08…bc44`）；
- `--network none` 运行 `scripts/ci-motion-offline.sh`：**11 passed / 0 failed**
  （25.4 s）；负控制 `fetch_exit=1 npm_exit=1`；
- 两次构建（300 / 30 帧）各 4 次外部请求、4 次失败；
- 报告：`network_policy=local-only`、`blocked_count=4`，去重后 3 条
  （unpkg stylesheet、`fonts.googleapis` `/css2`、`registry.npmjs.org` fetch），
  path 不含 query；
- `scene_fonts.named_available = [DejaVu Sans, Liberation Sans, Arial]`；
- 视频正常发布（47048 / 11032 字节）。

**本机测试**

- Node：`contract.test.mjs` + `output-dir.test.mjs` + `network-policy.test.mjs`
  → 29 tests / 26 pass / 0 fail / 3 skipped（符号链接用例在 Windows 跳过）；
- Windows：`uv run pytest` → 373 passed, 38 skipped；ruff/format/mypy 全绿。

**D 批 CI 证据（run `39893948581`，commit `9b64bf4`）**：五个 job 全绿。

- `motion-canvas-p1`：JUnit 17/0/0（66.3 s），Node 契约 TAP 29/29（0 skipped）；
- `motion-canvas-offline`：JUnit 11/0/0（34.9 s），镜像
  `sha256:626c144e…25ae`，负控制 `fetch_exit=1 npm_exit=1`，两次构建 4/4 外部请求失败；
- 两个 job 的全部 8 份 completed `report.json` 均为：
  `network_policy=local-only`、`blocked_count=4`、`request_failures=4`、
  `scene_fonts.named_available=[DejaVu Sans, Liberation Sans, Arial]`，
  拦截项的 path 不含 query/fragment；
- `test` / `graphviz` / `browser-qa` 绿。artifact 已下载到
  `var/ci-run-d/`（git 忽略）并独立复核。
