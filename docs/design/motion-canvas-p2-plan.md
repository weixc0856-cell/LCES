# Motion Canvas P2.1 实施与验收计划：Registry 生产准入

日期：2026-10-22
基线：`main` @ `2ea0534`（P1 全部验收通过）
范围：P2.1 一个阶段。P2.2（`flow`/`compare` 模板）、P2.3（A11 隔离与供应链）、
P2.4（P2 全量验收）不在本计划内，也不在本轮实现。

状态词严格沿用 P1：`NOT_RUN`、`PASS`、`FAIL`、`BLOCKED`。未执行的检查不得
记为 `PASS`；单元测试通过不能替代 `lces build` 的真实生产入口。

## 1. 目标与非目标

目标：让动画真正进入 `lces build` 的生产资产链路——由内容触发、经
`default_registry()` 选择 Motion Canvas、产出可发布的视频、把视频与
FrameManifest/编码证据写入 `visual_assets.json`，并且失败时明确失败、
不静默回退、不留下可被误发布的半成品。

非目标：

- 多场景/多模板；P2.1 仍只支持单场景 `title`。
- 多视频/多镜头合成；一个构建最多一个动画资产。
- 自动把模型输出变成动画场景；P2.1 只接受结构化场景文件。
- 视觉质量（MC-04）、跨环境字节级复现、Windows 原生渲染。

## 2. 生产路径审计（基于 `2ea0534`）

| 位置 | 现状 | 对 P2.1 的影响 |
|---|---|---|
| `renderers.py:920` `default_registry()` | 注册 table/figure/svg/chart/diagram/graph，**没有** `animation` | 动画无法进入 `lces build` |
| `visuals.py:54` `_spec_for_block()` | 只把 table/figure/chart/diagram/graph 映射为 `VisualSpec` | 内容模型里没有任何东西能触发动画 |
| `models.py:306` `PublicBlock` | 没有 animation/video 块；`PROJECT_SUBDIRS` 已创建 `content/scenes`，但没有代码读取 | 需要新增触发契约 |
| `rendering.py:53` `build_public_html()` | 以 `output_path.parent`（`build/slides`）作为 renderer 输出目录；先写 HTML，后写资产清单 | 若直接注册，视频会落在 `build/slides/media/`，发布装配只复制 `build/media/`；且 HTML 与资产清单没有共同提交点 |
| `visuals.py:145` `write_render_manifest()` | `visual_specs.json` → `render_manifest.json` → `visual_assets.json` 顺序写入，无临时文件/回滚 | 任一步失败会留下新旧混杂的证据 |
| `visuals.py:190` `_asset_contracts()` | 已识别 `animation`，越界产物会失败；但 `RenderedVisual` 没有 `build_id` | 资产无法关联构建标识 |
| `release.py:151` `_stage()` | 只复制 `build/media/{course.mp4,srt,vtt}`；`paths.py` 白名单同样只含这一路径 | 视频必须落在 `build/media/course.mp4` |
| `motion_canvas.py` P1 适配器 | 编码到 `.staging-<id>/` 后 `os.replace`；`project_dir` 存在时写 `internal/qa/{frame_manifest,encode_report}.json` | 视频原子性已有；需要把 `output_path` 与构建提交策略接上 |
| `rendering.py:31` `_reject_registry_only_blocks()` | 旧模板路径拒绝 chart 块 | 动画块也必须被拒绝，不能静默跳过 |
| `validation.py` Gate 4 | 重新读取 release 视频与 `internal/qa` 清单/编码记录 | 生产路径必须继续写这些证据，P2.1 不另造一套 |

## 3. 冻结决策

### D1 触发方式：内容块 + 场景文件

新增 `AnimationBlock`（`type: "animation"`），字段：

- `scene_file`：工作区相对路径，必须位于 `content/scenes/` 且以 `.json` 结尾；
- `alt`：必填，用于无障碍文本；
- `caption`：可选。

场景文件复用 `lces render-scene` 的输入结构：

```json
{"scene_set": {"scenes": [...]}, "video": {"...": "..."}}
```

`source` 记录 `content/scenes/<file>`，不是生成的 TypeScript；`source_hash`
是该文件的 sha256。场景文件不得包含可执行代码。

### D2 注册与选择

`default_registry()` 注册 `MotionCanvasRenderer()`，`known_types()` 包含
`animation`。选择仍由 `visual_type` 决定；显式 `renderer` 不匹配即失败；
注册表**不会**回退到模板或其它渲染器。

环境门禁只在真正需要渲染动画时才执行：非动画构建不受 Linux/Node/FFmpeg
缺失影响；包含动画且环境不满足时，构建以 `unsupported_platform` /
`environment_unavailable` / `dependency_mismatch` 失败。

### D3 输出路径与数量

- 当 `RenderContext.project_dir` 存在时，适配器把最终视频写到
  `project_dir / video.output_path`；P2.1 只接受
  `build/media/course.mp4`（与发布白名单一致），其它路径是 `invalid_input`。
- `RenderContext.publish` 区分生产构建与独立入口：`build_public_html` 设置
  `publish=True`，视频写入 `project_dir / video.output_path`；`lces render-scene`
  保持 `publish=False`，仍按 `output_dir/media/course.mp4` 输出，`--out`
  语义不变。没有 `project_dir` 时同样走 `output_dir`。
- 一个 `PublicContent` 最多一个 `AnimationBlock`；第二个直接 `invalid_input`，
  避免两个资产争用同一个发布路径。
- 场景文件里的 `video.project_id` 必须等于项目 ID；`video.scene_ids` 必须与
  `scene_set.scenes` 顺序一致；其余契约由 P1 的 `_parse()` 继续校验。

### D4 资产关联

`RenderedVisual` 新增 `build_id`。`VisualAsset` 至少记录：

| 字段 | 内容 |
|---|---|
| `asset_id` | `slide-xxx-block-yy` |
| `asset_type` | `animation` |
| `source` / `source_hash` | 场景文件相对路径 / sha256 |
| `renderer` / `renderer_version` | `motion_canvas.renderer` / 适配器版本 |
| `parameters` | 画布、`fps_num`/`fps_den`、总帧数、场景帧边界、`video_id`、`build_id` |
| `output_paths` | `build/media/course.mp4`、`internal/qa/frame_manifest.json`、`internal/qa/encode_report.json` |
| `output_hashes` | 上述三个文件的 sha256 |
| `build_id` | 与视频清单/编码记录一致的构建 ID |
| `status` | 仅在三者都存在且哈希一致后写 `rendered` |

`build/media/course.mp4` 的哈希必须同时等于 `encode_report.video_sha256`；
`internal/qa/frame_manifest.json` 的 `build_id` 必须等于资产的 `build_id`。
任何一项不一致都是 `qa_failed`，不写资产记录。

### D5 公开 HTML

模板新增 `animation` 分支，由构建器注入 `video_src`（由
`video.output_path` 推导为页面相对的 `../media/course.mp4`），模板只输出固定
结构的 `<video controls preload="metadata">` + `figcaption`，不接受模型提供的
HTML。视频 `max-width:100%`，不自动播放。`use_registry=False` 时遇到动画块
直接失败（与 chart 相同）。

### D6 构建提交与一致性

构建不是一次文件写入，必须有一个可判定的提交点：

1. `lces build` 开始时写 `build/.build-in-progress`（含 build_id、时间）。
2. 渲染全部视觉资产；Motion Canvas 仍先用 staging 编码并原子替换视频。
3. HTML、`visual_specs.json`、`render_manifest.json`、`visual_assets.json`
   先写同目录临时文件，并做提交前校验：
   - 每个资产 `output_paths` 均存在且 sha256 匹配；
   - 视频与 `internal/qa/frame_manifest.json` 一致（帧数、尺寸、时长、解码）；
   - 视频哈希与 `encode_report.json` 一致；
   - 有动画时 HTML 含预期 `video_src`，无动画时不出现视频元素。
4. 按固定顺序 `os.replace`：HTML → specs/manifest → `visual_assets.json`。
5. 全部成功后删除 `build/.build-in-progress`；任一步失败保留标记。
6. 成功的**非动画**构建会删除残留的 `build/media/course.mp4`：发布装配按文件名
   复制媒体，不能留下新内容未引用的旧视频。
7. 标记只能由一次**成功且通过校验**的构建清除；失败后重试会重写标记并在成功时
   清除。进程在视频发布后崩溃时标记保留，release 仍被阻断（测试模拟）。

`lces release` / `build_release()` 在标记存在时拒绝，并说明先重新运行
`lces build`。因此失败构建可以留下诊断产物，但**不能**被装配成发布包；
旧 `release/` 目录不会被触碰。

### D7 失败语义

| 情况 | 结果 |
|---|---|
| 环境缺失/版本不符/lockfile 不一致 | 构建失败，错误码来自环境门禁；不写 HTML/资产 |
| 场景文件缺失、越界、非法 JSON、契约不合法 | `invalid_input`；不开始渲染 |
| 第二个动画块 | `invalid_input`；不开始渲染 |
| 渲染/编码/帧清单/视频校验失败 | 构建失败；旧视频由 staging 保护；标记保留，release 拒绝 |
| 资产提交前校验失败 | 构建失败；标记保留；不发布新 HTML/资产 |
| 非动画构建 | 行为不变；不实例化动画渲染器 |

### D8 向后兼容

- 非动画内容仍走原有 registry；模板输出与 P2.1 之前一致。
- `use_registry=False` 仍可用于非动画内容；动画/图表块显式拒绝。
- CLI `render-scene` 与 P1 的独立入口不变。
- 现有 `visual_assets.json` 字段不删除；只新增动画资产和 `build_id`。

## 4. P2.1 验收表

| ID | 验收项 | 通过条件 | 状态 |
|---|---|---|---|
| P2-GATE-01 | Registry 发现 | `default_registry().known_types()` 含 `animation`；解析到 `motion_canvas.renderer`；显式 renderer 不匹配失败 | PASS（本机单元） |
| P2-GATE-02 | 生产入口 | `lces build`（或 `_stage_build`）对含动画块的 content 调用真实 renderer，产出 `build/media/course.mp4`；不是只测试 `render-scene` | PASS（run `39796759273`：`test_lces_build_renders_animation_end_to_end` 通过；JUnit 12/0/0；artifact 含视频、清单、编码记录、`visual_assets.json`） |
| P2-GATE-03 | 资产关联 | `visual_assets.json` 的视频、FrameManifest、编码记录路径与哈希一致；`build_id` 与清单一致；视频可解码 | PASS（run `39796759273`：独立复核 artifact，30 帧 640×360 30/1 1.0 s；三个文件哈希、`build_id` 与编码记录全部一致） |
| P2-GATE-04 | 失败传播 | 缺 Node/FFmpeg、非法场景、渲染失败、编码失败、清单不一致均使构建失败；无回退、无资产记录 | PASS（run `39796759273`：`test` job 315 个用例通过，含真实 CLI 非法场景、渲染/编码失败、清单不一致；`motion-canvas-p1` 的真实生产入口同时通过） |
| P2-GATE-05 | 原子性与旧资产 | 失败后旧 `build/media/course.mp4` 哈希不变；标记存在时 `release` 拒绝；成功构建清除标记 | PASS（run `39796759273`：失败重试、发布后崩溃、校验失败保留标记、视频篡改检测、非动画构建清理残留视频、`release` 拒绝均有测试；P1 staging 保护旧视频） |
| P2-GATE-06 | 向后兼容 | 非动画构建/模板输出不变；`use_registry=False` 仍拒绝 registry-only 块；现有测试全绿 | PASS（315 passed, 6 skipped） |
| P2-GATE-07 | CI 证据 | `test` job 与 Linux `motion-canvas-p1` job 跑新增测试并上传 JUnit/资产证据 | PASS（run `39796759273` 五个 job 全绿；p1 JUnit 12/0/0，TAP 13/13；artifact `motion-canvas-p1-evidence` 含 video/清单/编码记录/`visual_assets.json`） |

`BLOCKED` 只用于“已定义、可执行、但当前环境不满足”；本地 Windows 的真实
生产渲染属于此类，必须由 CI 的 Linux runner 完成。

## 5. 实施步骤

1. 模型与内容：新增 `AnimationBlock`、`PublicBlock` 联合类型；场景文件加载与
   校验；`specs_for_slide()` 映射。
2. 适配器：注册到 `default_registry()`；按 `project_dir + video.output_path`
   发布；把 `internal/qa` 证据加入 artifacts；`RenderResult.html` 保持空。
3. 构建：`build_public_html` 注入 `video_src`；`RenderedVisual.build_id`；
   资产合同、提交前校验、临时文件与标记。
4. 发布：`build_release()` 检查标记；Gate 4 继续使用现有证据。
5. 测试：
   - 单元：块/场景校验、spec 映射、registry 选择、资产合同、失败矩阵、
     标记与临时文件（使用 stub renderer，任意平台）。
   - 真实集成：Linux CI 用 30 帧 smoke 配置跑 `lces build`，断言视频、
     manifest、编码记录与资产清单一致；不重复 300 帧生产渲染。
6. CI：`motion-canvas-p1` job 增加生产入口测试文件；artifact 增加
   `visual_assets.json`、`internal/qa` 证据。

## 6. 风险与待定

1. **模板兼容**：新增块类型会改变 `PublicBlock` 的 JSON Schema；这是新增
   可选类型，`schema_version` 保持 1.x。需要 `lces export-schemas` 更新。
2. **Release 标记**：标记文件位于 `build/`，不会进入 release；但需要明确
   清理路径（成功构建删除；失败后由下一次成功构建覆盖）。
3. **单视频限制**：P2.1 不接受多动画；多镜头合成留给后续阶段。
4. **模型生成**：P2.1 不要求 `generate` 阶段产出动画块；手工/外部结构化
   场景文件是受支持的入口。若后续要让模型生成，必须先定义受控模板与校验，
   不能直接生成场景代码。


## 7. 本轮实现状态（2026-10-22）

已完成代码：`AnimationBlock`、场景文件校验、`default_registry()` 准入、
`lces build` 生产链路、视频/QA 证据入 `visual_assets.json`、构建标记与
`release` 拒绝、Gate 3 的 `animation_media_exists` / `build_committed`。

本机验证：

- `uv run pytest` → **315 passed, 6 skipped**（跳过的是 Graphviz、四个 Linux
  真实渲染用例和一个真实生产入口用例）。
- `ruff check .`、`ruff format --check .`、`mypy src` 全部通过。
- `tests/test_production_animation.py` 用 stub renderer 覆盖生产装配、
  资产合同、标记、发布拒绝与失败路径；`tests/test_motion_canvas_production.py`
  是唯一的真实 `lces build` 用例，只能在 Linux + 固定工具链的 CI 中执行。

最终 CI（run `39796759273`，commit `01f7e88`）五个 job 全绿：`test` 315 个用例、
`motion-canvas-p1` JUnit 12/0/0、TAP 13/13、`motion-canvas-offline` 断网 job
通过。production artifact 已独立复核：30 帧、640×360、30/1、1.0 s，
`visual_assets.json` 中的视频/清单/编码记录哈希与 `build_id` 全部一致。
P2-GATE-01～07 全部为 PASS。
