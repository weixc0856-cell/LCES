# Motion Canvas P2.2 实施与验收计划：`flow` / `compare` 场景模板

日期：2026-10-22
基线：`main` @ `8a0f66b`（P2.1 已合并，run `39800811292` 全绿）
范围：P2.2 一个阶段。P2.3（A11 隔离与供应链）、P2.4（P2 全量验收）不在本计划内，
也不在本轮改动中。

## 1. 目标与边界

目标：在 P2.1 的生产准入之上新增两个受控场景模板：

- `flow`：少量节点的流程/架构示意，节点与连线由结构化数据给出，布局确定；
- `compare`：左右对照（方案/优劣/前后），栏目与条目由结构化数据给出。

硬边界：

- 模型只提供经过 Schema 校验的**数据**；渲染器只使用仓库内的固定模板生成
  TypeScript。模型不能生成或修改可执行 TypeScript、表达式或 import。
- 仍是一次构建一个场景；多场景合成留给后续阶段。
- 不改变 P2.1 的 Registry、资产合同、提交标记和发布门禁。
- 不引入图自动布局库、不引入新运行时依赖。

## 2. 现有实现审计（避免重复造轮子）

| 位置 | 现状 | P2.2 的处理 |
|---|---|---|
| `models.SceneContract.data` | 任意 JSON 对象，由渲染器 `validate_input()` 解释 | 保持不变；在适配器内按 `scene_type` 严格校验字段 |
| `motion_canvas._scene_problems()` | 只接受 `title`，校验 title/subtitle/颜色 | 扩展为按类型分派，未知字段也拒绝 |
| `motion_canvas._scene_source()` | 固定 title TSX 模板，`_ts_string()` 转义 | 扩展为按类型分派；新增 `_ts_json()` 把结构化数据作为 JSON 字面量嵌入 |
| `SceneSet` / `VideoContract` / `timeline.py` | 已支持顺序场景、整数时间轴 | 不修改；P2.2 仍要求恰好一个场景 |
| `visuals._animation_spec()` | 校验场景文件、video 契约、单动画限制 | 不修改；场景数据由渲染器继续校验 |
| `renderers.default_registry()` / 资产合同 | P2.1 已把动画接入生产路径 | 不修改；新模板自动复用 |
| `motion/src/project.ts` | 固定导入一个 `generated?scene` | 不修改；每次构建仍只生成一个场景 |
| `motion/contract.test.mjs` | UI/版本/DOM 契约 | 不修改；模板类型不影响驱动协议 |

结论：P2.2 只需改 `motion_canvas.py` 的“场景数据校验 + 固定模板生成”两处，
加上测试和文档；生产路径、资产记录、发布门禁均复用 P2.1。

## 3. 数据契约

公共字段（三种模板共用）：

| 字段 | 类型 | 规则 |
|---|---|---|
| `title` | string | 必填，1–120 字符 |
| `subtitle` | string | 可选，≤ 200 字符 |
| `accent_color` | string | 可选，`#rrggbb` |
| `background_color` | string | 可选，`#rrggbb` |

未知字段一律 `invalid_input`，不静默忽略。

### 3.1 `flow`

```json
{
  "scene_type": "flow",
  "data": {
    "title": "请求处理流程",
    "subtitle": "从网关到存储",
    "direction": "lr",
    "nodes": [
      {"id": "gateway", "label": "网关", "kind": "start"},
      {"id": "auth", "label": "鉴权", "kind": "step"},
      {"id": "store", "label": "存储", "kind": "end"}
    ],
    "edges": [
      {"from": "gateway", "to": "auth"},
      {"from": "auth", "to": "store", "label": "写入"}
    ]
  }
}
```

约束：

- `direction`：`"lr"`（默认）或 `"tb"`；
- `nodes`：2–6 个；`id` 匹配 `^[a-z0-9][a-z0-9-]{0,31}$` 且唯一；`label` 1–40 字符；
  `kind` ∈ `start` / `step` / `decision` / `end`，默认 `step`；
- `edges`：1–10 条；`from` / `to` 必须引用存在的节点；禁止自环与重复
  `(from, to)`；`label` 可选且 ≤ 24 字符；
- 允许 DAG 也允许环；布局只按节点顺序，不做自动分层；
- 布局必须放得下画布：LR 每个节点最小宽 120px、间距 32px；TB 每个节点最小高
  72px、间距 28px；放不下即 `invalid_input`，不缩到不可读。

布局规则（固定、确定）：

- 内容区左右边距 `max(80, width*0.06)`，上下边距同理；
- LR：节点等距排成一行，节点框宽 `min(280, 可用宽/n - 间距)`，高度 96；
  连线从源框右缘到目标框左缘，画在节点下层；
- TB：节点等距排成一列，节点框高 `min(140, 可用高/n - 间距)`，宽度 360；
  连线从源框下缘到目标框上缘；
- 标题在上方，节点依次淡入，连线在节点之后淡入；动画总时长不超过
  `min(2.4s, duration*0.7)`，剩余时间 `waitFor`。

### 3.2 `compare`

```json
{
  "scene_type": "compare",
  "data": {
    "title": "两种方案",
    "subtitle": "吞吐与复杂度",
    "left": {"title": "方案 A", "items": ["实现简单", "吞吐稳定"]},
    "right": {"title": "方案 B", "items": ["扩展性好", "运维复杂"]}
  }
}
```

约束：

- `left` / `right` 必填，各含 `title`（1–60 字符）与 `items`（1–6 条，
  每条 1–120 字符）；
- 不支持第三列、图标、图片或富文本；这些留给后续模板；
- 两栏等宽，中间留白；标题在顶部；栏目依次从左/右滑入，条目逐条淡入；
- 640×360 冒烟画布下字体按 `min(width/1920, height/1080)` 缩放，但最小字号
  不得低于 12px；低于时可读性不足即 `invalid_input`。

## 4. 模板生成与注入防护

- 新增 `_ts_json(value)`：`json.dumps(value, ensure_ascii=True, separators=(",", ":"))`，
  作为 TypeScript 对象/数组字面量嵌入。JSON 本身不能表达函数、import 或语句。
- 模板只 import 固定的 `@motion-canvas/2d` 与 `@motion-canvas/core` 符号；
  节点、连线、栏目全部由数据循环生成。
- 所有字符串走 JSON 转义；`</script>`、反引号、`${}`、U+2028/2029、换行
  都只能成为字符串内容，不能改变代码结构。
- 生成源码中不出现 `eval`、`Function`、`new Function`、动态 import 或模型
  提供的标识符作为代码。
- `title` 模板的输出保持 P1/P2.1 原样，避免视觉回归；新增测试锁定。

## 5. 失败行为

| 情况 | 结果 |
|---|---|
| 未知 `scene_type` | `invalid_input`，不渲染 |
| 未知字段、类型错误、空标签、超长文本 | `invalid_input`，不渲染 |
| 节点/边/栏目数量越界 | `invalid_input`，不渲染 |
| 边引用不存在的节点、自环、重复边 | `invalid_input`，不渲染 |
| 布局在画布上放不下 / 字号低于 12px | `invalid_input`，不渲染 |
| 场景文件/video 契约错误 | 复用 P2.1 的 `invalid_input` |
| 渲染/编码/清单失败 | 复用 P1.3/P2.1 的 `render_*` / `qa_failed`，不发布 |

所有失败都发生在渲染前（数据校验）或复用现有失败路径；没有新错误码。

## 6. P2.2 验收表

| ID | 验收项 | 通过条件 | 状态 |
|---|---|---|---|
| P2.2-GATE-01 | `flow` 契约 | 合法数据通过；未知字段/类型/数量/边引用/自环/重复/布局越界全部 `invalid_input` | PASS（本机单元） |
| P2.2-GATE-02 | `compare` 契约 | 合法数据通过；栏目/条目/字数/未知字段/画布可读性全部校验 | PASS（本机单元） |
| P2.2-GATE-03 | 模板安全 | 恶意字符串只成为字面量；生成源码无动态执行；title 模板输出不变 | PASS（本机单元 + `tsc --noEmit`） |
| P2.2-GATE-04 | 真实 `flow` 渲染 | Linux CI 640×360/30 帧真实渲染 + 编码；帧数/尺寸/清单/视频一致 | NOT_RUN |
| P2.2-GATE-05 | 真实 `compare` 渲染 | 同上 | NOT_RUN |
| P2.2-GATE-06 | 生产入口 | `lces build` 分别用 `flow` 与 `compare` 内容产出视频与 `visual_assets.json` | NOT_RUN |
| P2.2-GATE-07 | 失败矩阵 | 非法 flow/compare 数据在渲染前失败；不产生视频或资产记录 | NOT_RUN |
| P2.2-GATE-08 | 向后兼容 | P1/P2.1 全部测试与真实用例保持通过；未触碰 P2.3 | PASS（333 passed, 11 skipped；P2.1 真实用例在 CI 继续跑） |

## 7. 实施步骤

1. `motion_canvas.py`：`SUPPORTED_SCENE_TYPES`、按类型分派的 `_scene_problems`、
   `_ts_json`、`_scene_source` 的 `flow`/`compare` 分支；布局计算写成纯函数，
   便于单元测试。
2. 单元测试：契约校验、布局越界、恶意字符串、title 输出不变。
3. E2E：新增 flow/compare 的 30 帧真实渲染（Linux CI），断言帧数、尺寸、清单、
   视频一致。
4. 生产入口：把 `test_motion_canvas_production.py` 参数化为 `flow` 与 `compare`，
   验证 `lces build` 产出与资产记录。
5. CI：沿用 `motion-canvas-p1` job；artifact 已收集视频、清单、编码记录与
   `visual_assets.json`。
6. 文档：CONTENT_CONTRACTS 增加两个模板的数据契约与布局规则；
   IMPLEMENTATION_STATUS、P2.2 计划记录证据；不动 P2.3/P2.4。

## 8. 非目标

- 多场景时间轴、转场组合、旁白/字幕；
- Mermaid/Graphviz 自动布局；
- 代码走读（`code-walkthrough`）模板；
- 路径/子进程隔离与供应链加固（P2.3）；
- P2 全量验收结论（P2.4）。


## 9. 本机实现状态（2026-10-22）

已完成 `motion_templates.py`（严格数据校验、确定性布局、固定 TSX 模板）、
适配器接入、单元测试、真实渲染 E2E 与生产入口参数化用例。本机：

- `uv run pytest` → **333 passed, 11 skipped**（跳过的是 Graphviz、P1/P2.1/P2.2
  的 Linux 真实渲染与生产入口用例）；
- `ruff check .`、`ruff format --check .`、`mypy src` 全部通过；
- 生成的 `flow`/`compare` TSX 已用 `npx tsc --noEmit` 在本机运动工程中类型检查
  通过（Node 版本低于 P2 门禁，仅作语法/类型验证，不构成渲染证据）。

P2.2-GATE-04/05/06/07 仍为 `NOT_RUN`，必须由 Linux CI 的真实渲染与
`lces build` 证据关闭。
