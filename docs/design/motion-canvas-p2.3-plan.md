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
- 本机：`uv run pytest` → **337 passed, 16 skipped**（4 个 POSIX 进程组测试在
  Windows 跳过）；ruff/format/mypy 全绿。Linux 进程组与真实取消/超时证据
  仍待 CI。

| 批次 | 内容 | 完成条件 |
|---|---|---|
| P2.3-A 执行边界 | 校验 `OUTPUT_DIR`/`--out` 在项目内且为专用目录；HOME/XDG 隔离；可执行文件校验；进程残留断言 | N04/N05/N06/N07/N08/N09 通过；P1/P2 回归 |
| P2.3-B 文件系统 | 符号链接统一检查（场景、帧、charts、staging）；临时文件安全；发布拒绝链接 | N01/N02/N10/N11 通过 |
| P2.3-C 供应链 | Node tarball SHA256；base image digest；CI actions SHA/记录；lockfile/registry/浏览器来源记录；构建可复现性分级 | N12/N13/N14 通过；文档记录来源/版本/可复现边界 |
| P2.3-D 网络隔离 | 驱动层 Playwright 路由只允许 localhost/data/blob；外部请求失败并记录；字体回退 | N15 通过；P1.4 断网 job 继续 |
| P2.3-E 安全验收 | 全量负向矩阵；CI artifact（JUnit、报告、截图/关键帧）；P2.1/P2.2 回归 | N01-N18 + 全部 P2.1/P2.2 测试；五个 CI job 绿 |

每批独立提交、独立审查；不把 P2.4 的全局门禁混入。

## 7. 验收门禁

| ID | 验收项 | 状态 |
|---|---|---|
| P2.3-GATE-01 | 执行边界：输出目录、可执行文件、超时/取消、进程残留 | NOT_RUN（可执行文件/进程组部分已实现并本地测试；输出目录与 Linux CI 证据待 A 批 CI） |
| P2.3-GATE-02 | 文件系统边界：路径穿越、符号链接、临时文件、发布夹带 | NOT_RUN |
| P2.3-GATE-03 | 供应链：版本固定、来源可信、可复现边界均有记录与测试 | NOT_RUN |
| P2.3-GATE-04 | 网络边界：渲染期非本地请求被阻断/记录，断网 job 仍通过 | NOT_RUN |
| P2.3-GATE-05 | 负向测试矩阵 N01-N18 全部符合预期 | NOT_RUN |
| P2.3-GATE-06 | P2.1/P2.2 生产链路与模板无回归 | NOT_RUN |
| P2.3-GATE-07 | 最终提交的五个 CI job 全绿，artifact 可独立复核 | NOT_RUN |
| P2.3-GATE-08 | 审计、威胁模型、负向测试命令与退出码全部留档 | NOT_RUN |

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

- `main` = `3730608`；CI run `39810527209` 五个 job success。
- 本地：`337 passed, 16 skipped`（A 批后）；ruff/format/mypy 全绿。
- P2.2 计划、契约和证据已提交；P2.1 生产链路已合并。
- 工作区仅 `.claude/` 未跟踪，无业务改动。
