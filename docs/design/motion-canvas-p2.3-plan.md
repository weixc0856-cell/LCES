# Motion Canvas P2.3 审计、威胁模型与实施计划

日期：2026-10-23
基线：`main` @ `3730608`（P2.2 收口；run `39810527209` 五个 job 全绿）
本文件只做审计、威胁建模和计划，不包含 P2.3 的实现改动。P2.3 的实现应在
独立批次中完成，并且不修改 P2.2 的模板能力或 P2.1 的生产链路语义。

## 1. 范围

P2.3 = **动画渲染执行边界隔离与供应链约束**：

- P0：子进程、可执行文件、参数、超时/取消、进程树和退出码边界；
- P1：输入/临时/输出目录、路径解析和符号链接边界；
- P2：lockfile、固定版本、镜像、Node/npm/Playwright/FFmpeg 的来源与可复现性；
- P3：每类边界的正/负向测试与独立 CI 证据。

非目标：

- 不新增场景模板，不改 P2.2 的 `flow`/`compare` 数据契约；
- 不重做 P2.1 的 Registry/资产/发布链路；
- 不提前做 P2.4 的全局门禁或 MC-04 视觉验收；
- 不承诺抵御与 LCES 同 OS 账户、可任意修改仓库/环境的恶意本地用户；
- 不承诺容器逃逸、内核漏洞或宿主机隔离；P2.3 只收紧 LCES 自己的执行边界。

## 2. 资产与信任边界

| 资产 | 说明 | 信任级别 |
|---|---|---|
| 原始资料 / `content/` | 论文、网页、模型输出的公开内容 | 不可信数据 |
| `SceneContract.data` | 模型/作者提供的结构化场景数据 | 不可信数据，必须 schema 校验 |
| `content/scenes/*.json` | 场景文件 | 不可信数据，必须路径/尺寸/契约校验 |
| Python 适配器 → Node 驱动 | 子进程调用与 JSON/文件契约 | 受控接口 |
| Node 驱动 → Vite/Chromium | 编辑器 UI 与本地 HTTP | 受控子进程，但含外部资源请求 |
| 适配器 → FFmpeg/ffprobe | 编码与探测 | 系统可执行文件，列表参数 |
| `build/`、`internal/qa/` | 帧、清单、编码记录、资产清单 | 可重建的中间产物 |
| `release/`、ZIP | 人工审批后的正式资产 | 发布边界 |
| 用户 HOME、系统 PATH、环境变量 | 驱动继承的宿主环境 | 宿主资源 |
| CI runner / 容器镜像 / npm / 浏览器下载 | 构建与运行依赖 | 供应链 |

信任边界：

1. **内容/模型 → 场景数据**：只能以 JSON 数据进入；不能成为 TypeScript。
2. **Python → Node**：环境变量白名单、构建目录、JSON 契约、进程组。
3. **Node → 浏览器/Vite**：本地回环地址；必须假定编辑器会请求外部字体/资源。
4. **适配器 → 系统工具**：`subprocess` 列表参数，无 shell；路径来自已校验契约。
5. **构建 → 发布**：提交标记、资产校验、Gate 3/4、人工审批。
6. **CI/镜像 → 运行时**：版本固定、lockfile、镜像 ID 记录；来源可信度分层。

## 3. 代码现状审计

### 3.1 子进程与执行（P0）

| 位置 | 现状 | 评估 |
|---|---|---|
| `motion_canvas.node_binary()` (`:106`) | `LCES_NODE_BIN` 必须存在，否则 `node` from PATH | 未校验可执行位/是否符号链接/是否目录；env 由操作者控制 |
| `_run_probe()` (`:115`) | `subprocess.run` 列表参数、20 s 超时 | 无 shell；失败返回空 |
| `_execute_driver()` (`:618`) | `start_new_session=True`，轮询取消/超时，进程组 SIGTERM/SIGKILL | 结构正确；缺少“无残留子进程”的断言 |
| `cancel()` / `_terminate()` (`:863`/`:887`) | 先 SIGTERM 组，5 s 后 SIGKILL | 需负向测试验证 Vite/Chromium 全部退出 |
| `encode.encode_frames()` (`encode.py:50`) | `subprocess.run` 列表参数、超时、空输出检查 | 无 shell；FFmpeg 来自 PATH |
| `video_qa.probe_video()/decode_video()` | `ffprobe`/`ffmpeg` 列表参数、超时 | 无 shell |
| `motion/driver.mjs:53` | `spawn(process.execPath, [vite,...])`，无 shell | Vite 固定入口 |
| `motion/driver.mjs:189` | `server.kill('SIGTERM')` | 正常退出只杀 Vite；异常由 Python 进程组兜底 |
| `motion/driver.mjs:90` | Chromium `--no-sandbox` | 容器内常见；需在威胁模型明确边界 |
| `_driver_env()` (`:805`) | 白名单 PATH/HOME/TMP/LANG + `PLAYWRIGHT_BROWSERS_PATH` + LCES_* | **HOME/TMP 继承宿主**；编辑器可能写 `~/.motion-canvas`（P0 已观测） |

P0 主要缺口：

- 驱动会在 `OUTPUT_DIR` 内递归清理条目（`motion/driver.mjs:45-48`）；该目录由
  适配器创建为专用帧目录，但 Python 侧没有校验它必须位于项目内、不可为符号
  链接；`render-scene --out` 允许任意路径，构建/媒体目录可能越界写入项目外；
- 取消/超时测试只断言不发布视频，未断言 Vite/Chromium 无残留；
- HOME 未隔离，编辑器可能写用户配置目录；
- `LCES_NODE_BIN` 只检查 `is_file()`，未检查可执行与规范化路径。

### 3.2 文件系统与路径（P1）

| 位置 | 现状 | 评估 |
|---|---|---|
| `models._relative_path()` | 拒绝绝对路径、盘符、`..` | 基础契约正确 |
| `visuals._animation_spec()` (`visuals.py`) | `resolve()` + `is_within(content/scenes)` + 1 MB 上限 | 符号链接越界被拒绝；已有测试 |
| `motion_canvas._parse()` | `video.output_path` 由模型校验；publish 时必须是 `build/media/course.mp4` | 生产路径收紧；独立 `--out` 未收紧 |
| `_materialise_project()` (`:749`) | `copytree` 复制模板；`node_modules` 符号链接回仓库 | 模板受控；复制会跟随模板内符号链接（如存在） |
| `frame_manifest` | 路径以构建目录为根；`verify_frame_manifest` 解析后检查越界、重新哈希、PNG 结构/解码 | 证据校验强；需符号链接负向测试 |
| `rendering.build_public_html` | marker + HTML 原子写 + 资产提交后复核 | 一致性策略明确 |
| `release._stage()` (`release.py:131`) | 固定复制 HTML/charts/media；`copytree(charts)` 跟随符号链接 | **`content/charts` 中的符号链接可能把项目外文件带入发布** |
| `_copy_charts()` (`rendering.py`) | `copytree(..., dirs_exist_ok=True)` | 同上 |
| `utils.write_text_atomic` | 固定 `.tmp` 文件 + `os.replace` | 同目录内原子；未检查临时文件是否为符号链接（本地同账户风险） |
| `paths.require_inside()` | 解析后强制位于项目内 | 可用于收紧 `--out`/输出目录 |
| `visuals._asset_contracts()` | 解析后相对化；动画产物越界即失败 | 好；非动画越界产物会被忽略 |
| `release._manifest_files()` | `rglob` 全量列文件并哈希 | staging 内符号链接未显式拒绝 |

P1 主要缺口：

- `render-scene --out`、`RenderContext.output_dir` 的边界未强制；
- `content/charts` → `build/slides/charts` → `release` 的符号链接未拒绝；
- staging/build 内符号链接没有统一的 `lstat`/`resolve` 检查；
- 驱动 `OUTPUT_DIR` 的递归清理缺少“目录内只允许已知产物”的约束。

### 3.3 供应链与版本（P2）

| 位置 | 现状 | 目标分类 |
|---|---|---|
| `motion/package.json` / `package-lock.json` | MC 3.17.2、Playwright 1.64.0、Vite 4.5.14 精确；`npm ci`；lockfile integrity | 版本固定（好） |
| `package-lock.json` resolved URL | 指向 `registry.npmmirror.com` | 来源可信度需显式记录/决策 |
| `motion_canvas.NODE_VERSION` + `engines` | Node 24.22.1 硬门禁 | 版本固定 |
| `motion/offline.Dockerfile` | base `ghcr.io/astral-sh/uv:python3.13-trixie-slim`（移动 tag）；Node tarball 直接 `curl`，**无校验和**；`npm ci`；`npx playwright install`；`uv sync --locked` | 版本固定部分；来源/可复现需补 |
| CI `.github/workflows/ci.yml` | actions 使用 `@v4/@v5` 主版本 tag；Playwright image `v1.64.0-noble`（tag）；记录 image ID | 供应链需分层记录/固定 |
| FFmpeg | 系统包；要求 >=6.0，记录实际版本 | 版本下限 + 记录（可复现不承诺） |
| Python 依赖 | `uv.lock` + `uv sync --locked` | 版本固定 |
| Graphviz/Mermaid | 外部/内置；Mermaid sha256 校验 | 已有部分供应链控制 |

P2 主要缺口：

- Node 压缩包未校验 SHA256；base image 未固定 digest；CI actions 未固定 SHA；
- npm registry 镜像与 Playwright 下载的可信来源未被文档化到“来源可信”层；
- “版本固定 / 来源可信 / 构建可复现”三个目标尚未在文档和测试中分开；
- 受限网络下的构建行为只覆盖了运行时 `--network none`，镜像构建期仍是正常网络。

### 3.4 已有负向测试

已有：场景路径越界/缺文件/非法契约、输出路径非 `build/media/course.mp4`、
锁文件不一致、帧数/PNG/清单/视频不一致、编码失败、取消/超时、失败标记、
视频篡改、非法 flow/compare 数据、模板注入字符串、非动画清理残留视频。

缺少（P2.3 重点）：

- 符号链接逃逸（场景文件、帧、charts、release staging）；
- 驱动 `OUTPUT_DIR` 越界/符号链接/非专用目录；
- 取消/超时后 Vite/Chromium 残留进程；
- HOME 写入隔离；
- 默认真实构建的外部网络请求（当前只靠 P1.4 断网 job）；
- `LCES_NODE_BIN` 非可执行/目录/符号链接；
- Node 压缩包/actions/镜像来源校验；
- 资源配额（磁盘/内存）边界。

## 4. 威胁模型

| ID | 威胁 | 向量 | 影响 | 现有控制 | P2.3 动作 |
|---|---|---|---|---|---|
| T01 | 场景路径/符号链接越界读取 | 恶意 `scene_file` | 读取项目外文件、渲染内容泄露 | 相对路径校验 + `resolve/is_within` + 1 MB 上限 | 补符号链接负向测试；统一 `lstat` 检查 |
| T02 | 输出目录越界/覆盖 | `--out`、`OUTPUT_DIR`、`video.output_path` | 覆盖宿主文件、破坏其它项目 | publish 固定路径；`--out` 未约束 | 限制 `--out`/output 在项目内；校验 `OUTPUT_DIR` 为专用目录 |
| T03 | 驱动清理/写入越界 | 错误 `OUTPUT_DIR`/符号链接 | 在项目外创建或清理构建专用目录、覆盖同名路径 | 目录由适配器创建；构建 ID 冲突会拒绝 | 驱动只清理已知产物；Python 侧校验目录位于项目内且非链接 |
| T04 | 取消/超时后残留进程 | Vite/Chromium 子进程 | 资源泄漏、后续构建干扰 | 进程组 SIGTERM/SIGKILL | 负向测试断言无残留；记录进程组 |
| T05 | 写用户 HOME/配置 | 编辑器默认设置 | 污染宿主、跨构建泄漏 | 未隔离 | 将 HOME/XDG 指向构建目录；测试无外部写入 |
| T06 | 渲染期外部网络 | 编辑器字体/unpkg/npm | 数据外泄、不可复现 | P1.4 断网可运行；正常构建不阻断 | 驱动层请求审计 + 默认阻断非 localhost（字体回退）；保留显式证据 |
| T07 | 模型代码执行 | 场景数据变成 TS/表达式 | 任意代码执行 | 固定模板 + JSON 字面量 + 转义测试 | 保持；增加生成源码静态断言 |
| T08 | 依赖树被改写 | `npm install`/本地篡改 | 不可复现、恶意包 | lockfile 直接依赖比对；`npm ci` | 保留；记录 lockfile 哈希；考虑校验 transitive 完整性 |
| T09 | 供应链篡改 | Node tarball/镜像/actions | 执行恶意二进制 | 版本固定；image ID 记录 | Node SHA256；base digest；actions SHA；来源记录 |
| T10 | 第三方 npm 镜像 | lockfile resolved URL | 来源不可信 | integrity 校验 | 文档化来源；决策是否改用官方 registry |
| T11 | FFmpeg 参数/路径注入 | 恶意路径/文件名 | 读写越界 | 列表 argv、无 shell、路径来自契约 | 固定 FFmpeg 解析路径/版本；负向测试 |
| T12 | 发布内容夹带 | charts/媒体符号链接 | 泄露项目外文件 | 发布白名单、Gate 4 | 拒绝 staging/charts 符号链接；测试 |
| T13 | 标记绕过/半成品发布 | 手工删除/崩溃 | 发布不完整资产 | marker + 资产复核 + release 拒绝 | 保持；P2.1 已有测试 |
| T14 | 资源耗尽 | 超大画布/帧/场景 | OOM/磁盘耗尽 | 尺寸/时长/帧数/场景大小上限；超时 | 明确磁盘/内存配额与预检；Docker 限额 |
| T15 | 日志/artifact 泄漏 | 绝对路径/环境 | 信息泄露 | 驱动 env 白名单；不写密钥 | 审计 artifact 内容；确认无密钥/敏感路径 |
| T16 | 环境变量覆盖 | `LCES_NODE_BIN` 等 | 执行非预期程序 | 部分存在性检查 | 校验可执行/规范化路径；限制到受控目录 |

## 5. 负向测试矩阵（先定义，后实现）

| ID | 用例 | 前置条件 | 预期行为 | 退出与产物 | 独立证据 | 回归范围 |
|---|---|---|---|---|---|---|
| N01 | `scene_file` 为 `../../x.json` / 绝对路径 | 构造 animation 块并调用模型校验或 `lces build` | `invalid_input`，不读取目标 | 退出码 13；无构建目录/视频 | 断言错误码与未创建目录；canary 文件未被读取 | P2.1/P2.2 生产入口 |
| N02 | `content/scenes/link.json` 符号链接到项目外 | 在 temp 项目创建链接与 canary | `invalid_input`，不读取目标 | 退出码 13；无视频 | canary 内容未进入日志/产物 | 场景文件校验 |
| N03 | `video.output_path` 绝对/`..`/非 `build/media/course.mp4` | 构造场景文件 | `invalid_input` | 无视频、无资产记录 | 断言错误码；目录未创建 | `lces build` |
| N04 | `render-scene --out` 指向项目外 | 运行 CLI | P2.3-B 后拒绝 | 退出码 13；项目外无新目录 | 断言目标路径不存在 | `render-scene` |
| N05 | `LCES_BUILD_ID` 含 `/`、`..`、大写 | 设置环境变量并渲染 | `invalid_input` | 无构建目录 | 断言目录不存在 | P1 E2E |
| N06 | `LCES_NODE_BIN` 为目录/不可执行/相对路径 | 设置环境变量并直接 render | `environment_unavailable`，不启动进程 | 无构建目录/视频 | 断言 `node_binary()` 为 None、无子进程 | P2.1 生产构建 |
| N07 | 驱动 `OUTPUT_DIR` 为项目外/符号链接/非专用目录 | 直接驱动或伪造 context | P2.3-A/B 后拒绝 | 不在项目外创建/清理目录 | 断言目标不存在、diag 记录 | P1 真实渲染 |
| N08 | 取消/超时后检查 Vite/Chromium | 真实渲染首帧后取消 / 短超时 | `cancelled` / `render_timeout`；进程组清空 | 无新视频/QA；旧视频哈希不变 | 检查本次 pgid 无成员；driver 日志 | P1 E2E、P2.1 失败路径 |
| N09 | 构建期写 HOME/XDG | 真实 `lces build` | P2.3-B 后写入仅限构建目录 | 构建成功；HOME 无新文件 | HOME canary 前后对比 | P2.1/P2.2 |
| N10 | 帧路径为符号链接/越界 | 构造 manifest/帧目录 | `qa_failed`/`output_corrupt` | 视频不发布 | 清单校验错误；目标未被读取 | P1.2/P1.3 |
| N11 | `content/charts` 或 staging 符号链接到外部 | 在 temp 项目放链接 | P2.3-B 后构建/发布拒绝 | 无 release/无外部文件 | release 树中无 canary | release 装配 |
| N12 | lockfile 与已安装直接依赖不一致 | 改写 node_modules 版本 | `dependency_mismatch` | 不启动渲染 | 错误码；无构建目录 | P1/P2 环境门禁 |
| N13 | Node tarball 校验和不匹配 | 构建镜像时替换 tarball/校验和 | P2.3-C 后镜像构建失败 | 无镜像/无 artifact | 构建日志退出码 | CI offline image |
| N14 | base image/actions 与记录不符 | 检查 Dockerfile/workflow 与记录 | P2.3-C 后审计失败或明确记录 | 无未记录依赖 | digest/SHA 文件 | CI |
| N15 | 正常构建的外部请求未阻断 | 真实渲染并观察请求 | P2.3-D 后非本地请求失败；字体回退 | 构建成功；request_failures>0 | report.json 请求审计 | P1/P2 E2E、offline job |
| N16 | 非法 flow/compare 数据（已有） | 真实 `lces build` | `invalid_input`，无视频 | 无视频；marker 保留 | CLI 输出/退出码 | P2.2 |
| N17 | 超大画布/帧数/场景文件 | 构造边界数据 | `invalid_input`，不启动渲染 | 无构建目录 | 错误码 | P1/P2 |
| N18 | FFmpeg 路径不可用/版本不足 | 移除/伪造 FFmpeg | `environment_unavailable`/`encode_failed` | 无视频；旧视频不变 | doctor/报告 | P1.3/P2.1 |

## 5A. P2.3-A 执行边界（已批准，先实施）

### A1 执行文件与参数

- `LCES_NODE_BIN` 必须解析为**绝对路径的普通可执行文件**：拒绝目录、相对路径、
  不存在/不可执行文件；符号链接按解析后的目标判断。
- 未设置时从 PATH 解析 `node`；解析失败即 `environment_unavailable`。
- 直接 `render()` 也必须在创建构建目录前校验 Node，不得回退到 PATH 上的
  `node` 而静默忽略非法 override。
- 所有子进程继续使用参数数组（无 shell）；新增静态回归测试防止
  `shell=True`。
- 失败不得创建构建目录、发布视频或写成功资产记录。

### A2 取消/超时与进程生命周期

- 记录本次驱动的进程组；SIGTERM → 宽限期 → SIGKILL → 等待回收。
- 终止后检查该进程组是否仍有成员；若仍存在，构建以 `render_failed` 失败，
  不能只因主进程退出就报告清理成功。
- 取消与超时仍保留各自终态（`cancelled` / `render_timeout`），但清理失败优先
  报为 `render_failed`。
- 诊断记录进程组清理结果，供测试与 CI artifact 复核。

### A3 负向验收

- 真实渲染首帧后取消、短超时两种路径；断言终态、旧视频哈希、无新视频/QA。
- 独立查询本次启动的进程组，确认 Vite/Chromium 无残留。
- 另起一个无关进程（不同进程组），确认终止逻辑不会误杀。
- A 批完成后运行 P1/P2.1/P2.2 回归；A 批独立提交与独立 CI 证据。

### A 批完成条件

- N06/N08 通过；`LCES_NODE_BIN` 非法配置在启动前拒绝。
- 取消/超时均完成进程组清理；无 Vite/Chromium 残留。
- 失败不发布产物，旧视频哈希不变。
- `title`/`flow`/`compare` 与 P2.1 生产构建回归通过。
- 五个 CI job 全绿，A 批证据可追溯。

### A 批实现记录（本机，CI 待执行）

- `node_binary()` 现在要求 `LCES_NODE_BIN` 为绝对路径的普通可执行文件；目录、
  相对路径、不存在/不可执行文件、断链均返回 `None`；合法符号链接按解析后的
  目标判断。
- `render()` 在创建构建目录前硬校验 Node，非法 override 不再回退到 PATH 上的
  `node`；驱动命令固定为 `[node, "driver.mjs"]`。
- `_stop_driver()`：SIGTERM → 5 s 宽限 → SIGKILL → 检查进程组；主进程退出但
  Vite/Chromium 仍存活时构建以 `render_failed` 失败，不会误报清理成功。
- 取消/超时/正常退出都记录 `process group <pgid> cleaned` 诊断；真实 E2E
  断言该诊断，并保留旧视频/无新视频与 QA。
- 新增 Linux 进程组测试：整组清理、忽略 SIGTERM 后升级 SIGKILL、不同进程组
  不被误杀；新增“子进程调用不使用 shell”的静态回归测试。
- 本机：`uv run pytest` → **337 passed, 17 skipped**（5 个 POSIX 进程组测试在
  Windows 跳过）；ruff/format/mypy 全绿。

**A 批 CI 证据（run `39816426680`，commit `2dc3ba1`）**：五个 job 全绿。
`test` job 运行 5 个 POSIX 进程组测试（整组清理、SIGTERM 忽略→SIGKILL、无关
进程组存活、zombie 不算活成员）；`motion-canvas-p1` 的真实 smoke/production、
flow/compare、`lces build`、取消与超时均通过，且 E2E 断言
`process group <pgid> cleaned` 诊断。合并后 `main` run `39817559381`
（`68ba9ff`）五个 job 全绿。A1/A2/A3 与 A 批完成条件均满足；
P2.3-GATE-01 仍保留 `NOT_RUN`，因为其中“输出目录边界”属于 B 批。

**A 批失败记录（CI run `39814506769`）**：真实渲染全部报
`render_failed: driver process group did not exit`；`test` job 的简单 sleeper
进程组测试通过，说明问题出在真实 Vite/Chromium 子进程。原因是容器 PID 1 不
回收孤儿，已退出的 Vite/esbuild 以 zombie 形式留在进程组内，而 `killpg(pgid, 0)`
对 zombie 仍返回成功。修复：Linux 下扫描 `/proc/<pid>/stat`，忽略 `Z`/`X`
状态；新增“未回收 zombie 不算活进程”的测试。

### B 批实现记录（本机 + WSL Linux；CI 待执行）

**B1 输出目录边界（N04/N05/N07）**

- `render()` 在创建任何目录前校验非 publish 路径的 `RenderContext.output_dir`：
  必须位于项目内、不得是项目根、不得位于 `input/`、`internal/`、`content/`、
  `release/`；路径任一组件是符号链接即拒绝（`invalid_input`）。CLI
  `render-scene --out` 走同一条路径，退出码 13。
- publish 路径仍固定为 `<project>/build`；`build/`、`media/` 也做链接组件检查。
- `LCES_BUILD_ID` 继续由 `BUILD_ID_PATTERN` 拒绝 `/`、`..` 和大写；新增显式用例。
- 注意：P1 文档里 `--out var/p1/build`（项目外）的示例按决策 6 不再可用；独立渲染
  必须写到项目内（通常 `<project>/build`）。那是 Windows 平台门禁的旧记录，历史
  证据仍成立，但 Linux 上该命令现在以 `invalid_input`（退出码 13）拒绝。
- 驱动 `OUTPUT_DIR` 由适配器创建为 `<build>/frames`。Node 侧新增
  `motion/output-dir.mjs`：要求绝对路径、目录本身及其父链 realpath 不得经过
  链接、目录内只允许 `report.json`、`after.png`、`NNNNNN.png`，并且只删除这些
  已知条目。目录被拒绝时不写报告、不在该目录创建任何文件。

**B2 HOME/XDG/TMP/缓存隔离（N09）**

- `_driver_env` 只继承 `PATH`、`LANG`、`LC_ALL`。`HOME`、
  `XDG_CONFIG_HOME`/`XDG_CACHE_HOME`/`XDG_DATA_HOME`/`XDG_STATE_HOME`、
  `TMPDIR`/`TMP`/`TEMP` 都指向 `build/motion/<id>/home|tmp`；编辑器默认配置
  写入构建目录。
- `PLAYWRIGHT_BROWSERS_PATH` 仍是宿主只读输入：显式设置时原样传入；未设置时
  回退到宿主默认浏览器目录，避免隔离 HOME 后找不到 Chromium。
- 真实 E2E 把宿主 HOME 指向 canary 目录；渲染成功后 canary 仍为空，且
  `build/motion/<id>/home` 存在。

**B3 符号链接与临时文件（N01/N02/N10/N11）**

- `paths.symlink_components()` / `symlinks_in_tree()` 作为统一检查。
- 场景：`content/scenes` 或其下任一组件为链接时拒绝，不读取链接目标。
- 帧：`build_frame_manifest` 扫描前拒绝帧目录内任何链接；
  `verify_frame_manifest` 对清单路径与帧目录再次检查并报 `qa_failed`，
  同时修掉了链接越界时 `resolve().relative_to()` 直接抛错的问题。
- charts：`_copy_charts` 拒绝源树链接与链接目标目录；`release._stage` 在复制
  前再次检查，`build/` 本身是链接时拒绝发布，staging 树不允许链接；
  `_manifest_files`/`_write_archive` 不会跟随链接；Gate 4 新增阻断检查
  `no_symlinks`。
- 临时文件：`write_text_atomic` 改用 `tempfile.mkstemp`（`O_EXCL`、随机名），
  预先放置的 `.target.txt.tmp` 链接不会被跟随；已有目标保留原权限。

**B 批修复记录（提交前反向审计）**

反向审计发现两项阻断，已在同一分支本地修复：

1. **E2E HOME canary 与浏览器解析冲突**：原测试先把宿主 `HOME` 指向空 canary，
   驱动又被隔离到构建 HOME，Playwright 因而找不到 Chromium；CI 因 job 级
   `PLAYWRIGHT_BROWSERS_PATH` 不会暴露，但 `scripts/ci-local.sh render` 会失败。
   现在 `host_home_canary` 在移动 `HOME` 之前解析浏览器目录：显式配置时原样保留
   （包括 `0`），未配置但宿主默认目录可解析时仅在测试作用域内固定，无法解析时
   明确 fail 而不是 skip。驱动仍只收到隔离 HOME，宿主 canary 断言保留。
2. **Release 中间目录链接**：叶子文件检查看不到“父目录是链接”的情况。新增
   `_reject_link_path` 在读取/写入前检查路径每个组件，覆盖 `build/`、
   `build/slides`、`build/slides/charts`、`build/media`、`build/artifacts`、
   `release/`、staging 与 ZIP 目标；`internal/qa` 在 `approve`、
   `load_qa_report`、`run_validation`、`write_render_manifest`、
   `verify_build_assets` 与动画 QA 写入前拒绝链接。负向测试 A/B/C/D 分别断言：
   外部 `index.html` 不进入任何产物、外部 artifacts 目录不出现 ZIP、外部
   release 目录为空、`internal/qa` 无新写入，且不留下 staging 或发布树。

**TOCTOU 边界**：当前符号链接检查属于文件操作前的路径校验，主要防御预先存在的
符号链接及非并发场景下的路径绕过。不承诺抵御具有同一操作系统账户权限、能够并发
修改仓库目录的攻击者。检查与使用之间仍可能存在 TOCTOU 窗口。实现没有使用
`openat2`/`O_NOFOLLOW`/目录 fd 相对操作，因此不得声称竞态已消除。

**补充测试**：`write_text_atomic` 增加“目标为链接时不跟随”“`os.replace` 失败时
清理临时文件”“POSIX 权限保留”三项；文件 `fsync` 不等于目录项持久性，目录未
fsync 的事实继续记录。E2E canary 的浏览器路径分支（已配置/未配置可解析/不可
解析）各有单元测试。

**本轮未覆盖的残余**：`browser_qa` 的 screenshots/baselines 与 `content` 的
generation trace 仍直接写入 `internal/qa`；它们属于构建内部证据，发布链已会在
读取前拒绝链接目录，本轮未逐一加锁。Windows 无法在本机创建符号链接，所有链接
负向用例只在 WSL/Linux 执行；Windows 上 `os.replace` 覆盖链接的语义也未本地
验证。非 Motion Canvas 渲染器的输出路径检查不在本轮范围。

**B 批测试与证据**

- 新增 `tests/test_p23_filesystem_boundaries.py`（N01/N02/N04/N05/N07/N09/N10/N11）；
  符号链接用例在无创建权限的 Windows 跳过，在 WSL Linux 全部执行。
- 新增 `motion/output-dir.test.mjs`（N07，9 项），CI 的 Node 契约测试步骤会
  同时运行 `contract.test.mjs` 与 `output-dir.test.mjs`。
- 本机 Windows：`uv run pytest` → **349 passed, 38 skipped**；ruff/format/mypy
  全绿；Node `output-dir.test.mjs` → 6 pass / 3 skipped（符号链接用例）。
- WSL Ubuntu（同一份代码，`uv run --python 3.13`）：**353 passed, 34 skipped**；
  `tests/test_p23_filesystem_boundaries.py` **33 passed, 0 skipped**（含 A/B/C/D、
  release-check/Gate 4 链接根、全部链接负向用例）；ruff 全绿。
- WSL 工具链：Node **v24.22.1**（官方 tarball，SHA256 校验通过）、FFmpeg
  **7.0.2-static**、Playwright 1.64.0 + Chromium 156.0.8078.4；在 WSL 内
  `npm ci` 重新安装 Linux 依赖（69 包），不再复用 Windows `node_modules`。
- WSL Node 测试：`contract.test.mjs` + `output-dir.test.mjs` → **22 tests /
  22 pass / 0 fail**（契约 13/13，输出目录 9/9）。
- WSL `scripts/ci-local.sh render`：**通过**。Node 契约 47.4 s；真实渲染/编码/
  Gate 4 **12 passed / 0 failed / 60.5 s**（e2e 4、production 4、templates 2、
  release_video 2），其中真实 E2E 含 HOME canary 断言。初次运行曾因
  Node 22.22.2 与 FFmpeg 缺失非零退出；安装锁定工具链后重跑，以上为最终结果。
- Windows 上 `ci-local.sh render` 是 Linux-only，未运行。
- **未执行**：`--network none` 离线 job、五个 CI job。B 批在 CI 证据产生前
  不得记为 PASS。

### C 批实现记录（本机 + CI）

**C1 供应链记录与审计**

- `config/supply-chain.json` 是供应链记录。每个组件同时声明来源
  `trust`（`official-release` / `official-registry` / `upstream-publisher` /
  `upstream-installer` / `distro-package`）与可复现级别 `reproducibility`
  （`digest-pinned` / `checksum-pinned` / `lockfile-pinned` /
  `version-pinned` / `version-floor`）。记录由 Pydantic 校验，
  格式错误即 `ConfigurationError`，不会退化成“未记录但继续构建”。
- `src/content_studio/supply_chain.py` 的 `audit_supply_chain()` 逐项核对记录与
  真正消费该固定的文件；`lces supply-chain-check` 输出 `[PASS]/[FAIL]`，
  任一失败以退出码 1 结束。检查项：
  - SC-01 base image 必须按 digest 固定，且与记录一致；
  - SC-02 Dockerfile 的 `ARG NODE_VERSION` / `ARG NODE_SHA256` 与记录一致，
    并在解压前执行 `sha256sum -c`；
  - SC-03 `package-lock.json` 的 `resolved` 必须全部来自记录的 registry，
    每个非链接包必须带 sha512 integrity；
  - SC-04 `package.json` 与锁文件根条目一致，直接依赖必须是精确版本；
  - SC-05 所有 workflow 的 `uses:` 必须是 40 位 commit SHA，且与记录一致；
  - SC-06 Node / Motion Canvas / Playwright / FFmpeg 下限在记录、适配器常量与
    `motion/package.json` 之间一致；
  - SC-07 `uv.lock` 覆盖 pyproject 的直接依赖，所有包来自记录的
    `https://pypi.org/simple`，CI 使用 `uv sync --locked`。
- CI `test` job 与 `scripts/ci-local.sh fast` 都执行该命令；记录本身不构成控制，
  审计必须读到消费方文件。

**C2 固定下载**

- `motion/offline.Dockerfile`：base image 固定为
  `ghcr.io/astral-sh/uv:python3.13-trixie-slim@sha256:331fbb15…22ab0`
  （多架构 index digest，标签仅保留可读性）；Node 24.22.1 linux-x64 归档固定
  SHA-256 `6c172a9a…95e6`（取自官方 `SHASUMS256.txt`），解压前校验，
  解压后再断言 `node --version`。
- CI workflow 的 Actions 全部改为 40 位 commit SHA，行尾保留可读 tag：
  checkout `11d5960a…`（v4）、setup-node `49933ea5…`（v4）、
  upload-artifact `ea165f8d…`（v4）、setup-uv `d4b2f3b6…`（v5）。
- `motion/package-lock.json` 的 91 个 `resolved` 从 `registry.npmmirror.com`
  改写为官方 `registry.npmjs.org`；integrity 值未变。本机对该锁文件执行
  `npm ci` 重新安装 69 个包成功（@motion-canvas 3.17.2 / Playwright 1.64.0），
  证明官方 registry 提供的内容通过全部 integrity 校验。
- Playwright 浏览器仍为 `version-pinned`：下载由 Playwright 自带校验和验证，
  LCES 不单独记录浏览器归档哈希；CI 每个 job 记录解析出的浏览器路径与版本。

**C3 来源可追溯（Level 1）**

- `internal/qa/encode_report.json` 升级为 schema 1.1，新增 `provenance`：
  `node_version`、`npm_version`、`motion_canvas_version`、`playwright_version`、
  `ffmpeg_version`、`python_version`、`lces_version`、
  `package_json_sha256`、`package_lock_sha256`。不写任何绝对路径，
  可安全作为 CI artifact 上传。
- 假驱动发布测试与真实 E2E 都断言 provenance 中的 lockfile 哈希与磁盘一致，
  且 provenance 块不含构建目录路径（`command` 字段仍按 P1.3 记录绝对 argv）。

**C 批测试与证据**

- 新增 `tests/test_supply_chain.py`（21 项）：仓库自身审计通过；N13（Node
  校验和不一致、缺少校验步骤）与 N14（tag 代替 SHA、未记录 action、无 digest
  的镜像、digest 不一致）的负向用例；镜像来自非白名单 host、缺 integrity、
  锁文件版本漂移、范围版本、Python 锁缺依赖、CI 未用 `--locked`；
  CLI 成功/失败退出码；encode report provenance 与无路径泄漏断言。
- 本机 Windows：`uv run pytest` → **370 passed, 38 skipped**；
  `ruff check .`、`ruff format --check .`、`mypy src` 全绿；
  `node --test contract.test.mjs output-dir.test.mjs` → 22 tests /
  19 pass / 0 fail / 3 skipped（符号链接用例在 Windows 跳过）。
- WSL Linux（同一份代码）：`tests/test_supply_chain.py` 21 passed；
  `lces supply-chain-check` 7/7 PASS。
**C 批 CI 证据（run `39888269698`，commit `e943433`）**：五个 job 全绿。

- `test` job 实际执行 `lces supply-chain-check`，SC-01…SC-07 全部 PASS。
- `motion-canvas-p1`：JUnit 17 tests / 0 failures / 0 skipped（66.7 s）；
  Node 契约 TAP 22/22；Node 24.22.1、npm 11、Playwright 1.64.0、FFmpeg 6.1.1。
- `motion-canvas-offline`：用 digest 固定的 base image 重新构建镜像
  （image ID `sha256:53423ae7…f4a6`），`--network none` 下真实渲染、编码与
  Gate 4 通过（JUnit 11/0/0，34.7 s）；负控制 `fetch_exit=1 npm_exit=1`；
  两次构建（300 帧 / 30 帧）各有 4 次外部请求、4 次全部失败。
- `graphviz`、`browser-qa` 绿。
- artifact 已下载到本机 `var/ci-run-39888269698/`（git 忽略），
  `image-id.txt`、`input-hashes.txt`、`contract-tests.tap`、`e2e-report.xml`
  可独立复核；输入哈希：`package-lock.json` `c387b6d6…`、`uv.lock`
  `03660c8f…`、`offline.Dockerfile` `023fc359…`。
- 文档提交 `a4431f6` 的复跑（run `39889057954`）同样五个 job 全绿。

**C 批本机 Docker 复验（Windows 11，Docker 29.9.1）**：用 digest 固定的
base image 在本机重建 `lces-motion-offline`（`sha256:a4ed0dfc…3d02`），
再以 `--network none` 运行 `scripts/ci-motion-offline.sh`：
**11 passed / 0 failed**（31.8 s）；两次真实构建 300 帧与 30 帧，各有
4 次外部请求且全部失败；负控制 `fetch_exit=1 npm_exit=1`。
证据写入 `var/ci-offline/`（git 忽略）。

**C 批残余与边界**

- 审计是静态一致性检查：它证明记录与消费文件相符，不能证明上游发布本身可信。
  Node 的 `SHASUMS256.txt.sig` 未在 LCES 内做 GPG 验证，信任锚是官方发布渠道。
- Playwright 浏览器由 installer 自带的校验和验证，LCES 不单独记录浏览器归档哈希；
  CI 每个 job 记录解析出的浏览器路径与版本。
- `encode_report.json` 的 `command` 字段（P1.3 既有）记录绝对 FFmpeg argv，会把
  runner 临时路径带入 CI artifact；新增的 `provenance` 不含路径。该报告不在发布
  白名单内，因此不构成发布泄露，artifact 级脱敏留待 E 批统一处理。
- 镜像构建期仍需外网（apt/npm/Playwright/uv）；P2.3-C 保证的是固定与校验，
  不是构建期断网。

| 批次 | 内容 | 完成条件 |
|---|---|---|
| P2.3-A 执行边界 | 校验 `OUTPUT_DIR`/`--out` 在项目内且为专用目录；HOME/XDG 隔离；可执行文件校验；进程残留断言 | N04/N05/N06/N07/N08/N09 通过；P1/P2 回归 |
| P2.3-B 文件系统 | 符号链接统一检查（场景、帧、charts、staging）；临时文件安全；发布拒绝链接；输出目录/HOME 隔离（A 批表内遗留项） | 实现与本机/WSL 测试完成；CI 待执行 |
| P2.3-C 供应链 | Node tarball SHA256；base image digest；CI actions SHA/记录；lockfile/registry/浏览器来源记录；构建可复现性分级 | N12/N13/N14 通过；文档记录来源/版本/可复现边界 |
| P2.3-D 网络隔离 | 驱动层 Playwright 路由只允许 localhost/data/blob；外部请求失败并记录；字体回退 | N15 通过；P1.4 断网 job 继续（run `39893948581` 五 job 全绿） |
| P2.3-E 安全验收 | 全量负向矩阵；CI artifact（JUnit、报告、截图/关键帧）；P2.1/P2.2 回归 | N01-N18 + 全部 P2.1/P2.2 测试；五个 CI job 绿（run `39899991262`） |

每批独立提交、独立审查；不把 P2.4 的全局门禁混入。

## 7. 验收门禁

| ID | 验收项 | 状态 |
|---|---|---|
| P2.3-GATE-01 | 执行边界：输出目录、可执行文件、超时/取消、进程残留 | PASS（A 批 run `39816426680`；B 批 run `39875910627`；C 批 run `39888269698` 的真实渲染、取消/超时与 HOME canary） |
| P2.3-GATE-02 | 文件系统边界：路径穿越、符号链接、临时文件、发布夹带 | PASS（边界模块 33/33 在 WSL；run `39875910627` 与 `39888269698` 的 Linux pytest 覆盖同一模块） |
| P2.3-GATE-03 | 供应链：版本固定、来源可信、可复现边界均有记录与测试 | PASS（run `39888269698`：SC-01…SC-07 全 PASS；离线 job 用 digest 固定的镜像重建并通过，输入哈希留档） |
| P2.3-GATE-04 | 网络边界：渲染期非本地请求被阻断/记录，断网 job 仍通过 | PASS（run `39893948581`：8 份真实构建报告均为 `local-only`、4 次拦截/4 次失败；离线 job 11/0 且负控制失败） |
| P2.3-GATE-05 | 负向测试矩阵 N01-N18 全部符合预期 | PASS（E 批 run `39899991262`；矩阵见 `motion-canvas-p2.3-e-acceptance.md`） |
| P2.3-GATE-06 | P2.1/P2.2 生产链路与模板无回归 | PASS（run `39888269698`：flow/compare 模板与 `lces build` 的真实渲染、编码、Gate 4 全部通过） |
| P2.3-GATE-07 | 最终提交的五个 CI job 全绿，artifact 可独立复核 | PASS（合并后 `main` @ `f98df74`，run `39902414995` 五 job 绿；E 批 artifact 已复核） |
| P2.3-GATE-08 | 审计、威胁模型、负向测试命令与退出码全部留档 | PASS（E 批：矩阵文档 + 脱敏 + 证据审计；run `39899991262`） |

`BLOCKED` 只用于已定义但环境不满足的项；本地 Windows 的 Linux 专属测试仍由
CI 执行，不得用“本机通过”替代。

## 8. 已确认决策（2026-10-23）

| # | 决策 | 默认 | 实施约束 |
|---|---|---|---|
| 1 | Base image | 固定 digest | 记录最终解析 digest；更新流程写入文档 |
| 2 | Node tarball | SHA-256 + 官方签名/可信发布证明（若可用） | 校验和来自独立可信渠道；同源未认证的校验和不单独作为来源证明 |
| 3 | CI Actions | 固定 40 位 commit SHA | 保留可读版本注释与升级计划 |
| 4 | npm registry | 优先官方 registry | 先验证锁文件完整性、CI 可达性；若保留镜像，明确信任/回退 |
| 5 | 外部网络 | 渲染期默认阻断非本地请求；必要白名单精确到主机 | 字体等静态资源优先入库；白名单需负向测试 |
| 6 | `render-scene --out` | 限制在项目内 | 规范化 + 符号链接边界；项目外输出需显式受控选项 |
| 7 | HOME/XDG | 隔离到构建临时目录 | 同时检查 TMPDIR/TMP/TEMP/缓存/编辑器配置目录 |
| 8 | 资源配额 | 分层硬限制 | 优先容器/cgroup 限制内存/CPU/磁盘/进程数；预检与超时不替代硬限制 |
| 9 | 进程残留检测 | 进程组查询为主，`pgrep` 为辅 | 只针对本次启动的进程组；不按进程名误杀 |

## 9. 基线

- `main` = `04e879f`（A 批证据合并后）；CI run `39817559381` 五个 job success。
- B 批分支 `feat/motion-canvas-p2.3-b`；审计修复后本地：Windows
  `349 passed, 38 skipped`，WSL Linux `353 passed, 34 skipped`（边界模块 33/33）；
  ruff/format/mypy（Windows）全绿；Node Windows 6/0/3、Linux 22/0/0（契约 +
  输出目录）。
- WSL `scripts/ci-local.sh render` 已通过：Node 契约 13/13，真实渲染/编码/
  Gate 4 12/12（60.5 s）；工具链为 Node 24.22.1、FFmpeg 7.0.2-static、
  Playwright 1.64.0、Chromium 156.0.8078.4。离线 job 与 CI 仍未运行。
- B 批已于 PR #16 合并（`main` = `5bb69bb`），CI run `39875910627` 五个 job 全绿。
- C 批分支 `feat/motion-canvas-p2.3-c`（基于 `main` = `5bb69bb`），PR #17 已合并；本机 Windows
  `368 passed, 38 skipped`；Node 22/19/0/3；ruff/format/mypy 全绿；
  `lces supply-chain-check` 7/7 PASS。离线镜像与五个 CI job 未运行。
- C 批 CI run `39888269698`（commit `e943433`）五个 job 全绿；离线 job 用
  digest 固定镜像重建成功。C 批证据已回填本节与 GATE-01/02/03/06/07。
- D 批分支 `feat/motion-canvas-p2.3-d`（基于 C 批），PR #19 已合并；
  CI run `39893948581` 五个 job 全绿；本机离线门禁 11/11。详见
  `docs/design/motion-canvas-p2.3-d-plan.md`。
- E 批分支 `feat/motion-canvas-p2.3-e`（基于 D 批），PR #20 已合并；
  矩阵收口、encode report 1.2 脱敏、doctor home 脱敏、证据审计脚本；
  本机 Windows `386 passed, 39 skipped`，CI run `39899991262` 五 job 全绿。
  详见 `docs/design/motion-canvas-p2.3-e-acceptance.md`。
- P2.3 全部批次已合并到 `main` @ `f98df74`；合并后 CI run `39902414995`
  五个 job 全绿。
