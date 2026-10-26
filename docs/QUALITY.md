# 质量标准

**性质：** 本文件是课程内容、视觉、动画、工程与交付质量的唯一标准。它规定"什么算通过、
什么必须报 `NOT_RUN`、发现问题如何定位"。产品目标见 [`PRODUCT.md`](PRODUCT.md)，实现边界见
[`ARCHITECTURE.md`](ARCHITECTURE.md)。

**第一原则：** 自动检查证明"检查确实执行了"，不证明"课程内容正确"。测试通过率不等于
课程质量；没运行的检查永远记为 `NOT_RUN`，不得折叠成 `pass`。

---

## 1. 五个质量维度

### A. 内容准确性

| 检查 | 执行方式 | 阻断 |
|---|---|---|
| 关键主张有支持证据 | Gate 1 `key_claims_have_evidence` | 是 |
| 被证据否定的主张 | Gate 1 `contradicted_claims_blocked` | 是 |
| 引文能在原文中定位 | `evidence_locator.py`，只接受 `verified_exact` / `verified_normalized` | 候选不进台账 |
| 数字/单位/公式与复核记录一致 | `lces audit-course` | 是 |
| 来源冲突已披露 | `audit-course` + Gate 4 `source_conflicts_acknowledged` | 是 |
| 限定条件保留（`big`、dev/test、BLEU 口径） | `number_audit.py` / `course_audit.py` | 是 |
| 公式分母、转置、符号与复核一致 | `latex-tokens/v1` 归一化匹配 + 人工复核记录 | 是 |
| 科学结论本身是否正确 | 专家复核 | **`NOT_RUN`，不能自动判定** |

### B. 教学质量

| 检查 | 执行方式 |
|---|---|
| 课程目标与受众明确 | `CourseContract` 必填字段；Gate B |
| 每个场景一个主要任务 | 场景契约 `objective_ids` / `required_checks`（见 §6 缺口） |
| 讲稿与场景一一对应 | `speaker_script_covers_slides`；Gate B `timing_matches_script` |
| 讲稿是口语，不是论文改写 | 人工审读；自动检查只能看结构与长度 |
| 信息密度与时长匹配 | 时长偏差 80%–130%；超出告警/阻断 |
| 学习检查存在且可回答 | `CheckBlock` + Gate B `learning_checks` |

### C. 视觉与动画质量

| 检查 | 执行方式 |
|---|---|
| 16:9 画布，1920×1080 优先 | 模板 `data-stage="1920x1080"` + `stage` 缩放 |
| 关键视口无横向溢出 | Gate 3 浏览器检查：1280 / 1920 / 2560 / 3840 / 390 |
| 无 JavaScript 错误、无资源加载失败 | Gate 3 浏览器检查 |
| 无外部 CDN / 在线字体 | `no_external_assets`；Mermaid 运行时随仓库交付 |
| 公式排版可读、不乱码 | `latex_render.py`；不支持的 LaTeX 命令让构建失败 |
| 图表/示意图不被裁切 | SVG `max-width:100%` + 视口检查 |
| 动画有讲解目的、可重复播放 | 复看动画步骤；场景复位检查 |
| 视觉漂移被记录而不是隐藏 | 截图基线三态 `missing / matched / drifted`；漂移只 `warn`，需人工确认 |
| 页面适合直接录屏 | 录屏模式/隐藏调试 UI（见 §6 缺口） |

### D. 工程质量

| 规则 | 执行方式 |
|---|---|
| 公开/内部类型隔离 | `PublicContent` vs `SpeakerScript`；模板只拿公开模型 |
| 稳定 ID 与契约校验 | Pydantic + JSON Schema（`lces export-schemas`） |
| 构建可复现 | 输入哈希、渲染清单、`release_manifest` 血缘 |
| 运行记录 | `tasks.run_id/input_sha256`、`stage_runs.error_class/retry_count/artifacts` |
| 门禁不放宽 | 新规则必须配新测试；不得为变绿删除断言或降低阈值 |
| 失败显式 | 抛 `LCESError` 子类；未知视觉类型/依赖缺失直接失败，不降级为空白 |

### E. 交付质量

| 检查 | 执行方式 |
|---|---|
| 课件、讲稿、阅读版、支撑材料齐全 | Gate B 交付物检查 |
| 关键内容可追溯 | 证据台账 + 审计报告绑定内容哈希 |
| 构建/版本信息明确 | `render_manifest.json`、`release_manifest.json` |
| 发布物不含内部文件 | Gate 4 白名单 + 内部标记扫描 + 密钥扫描 |
| 未解决的高严重度问题可见 | 报告中 `blocker` / `NOT_RUN` 原样输出，不隐藏 |

## 2. 自动门禁与命令

| 命令 | 作用 | 失败含义 |
|---|---|---|
| `lces validate` | Gate 1–3：证据、内容、工程与浏览器 | 有阻断项；`NOT_RUN` 单独列出 |
| `lces audit-course` | 课程↔证据的确定性审计 | 数字/公式/冲突未通过 |
| `lces audit-product` | Gate B：课程产品是否满足契约 | `blocked` / `needs_human_review` |
| `lces duration-plan` | 单元时长预算、估算与实测差距 | 只报告，不把估算当实测 |
| `lces expand-unit` | 按单元做证据约束的讲稿扩展 | 校验失败不落盘 |
| `lces rebalance` | 扩展 → TTS 实测 → 再评估（最多 2 轮） | 未测量则保持 NOT_RUN |
| `lces plan-impact` | 失效单元或某主张影响的单元/场景 | 只报告 |
| `lces release-check` | Gate 4：发布目录与清单血缘 | 发布物不合规 |
| `pytest` | 单元/集成/契约/负向测试 | 行为回归 |
| `ruff check` / `ruff format --check` / `mypy src` | 静态质量 | 代码问题 |
| `scripts/check_docs.py` | 文档链接、命令、必需文件 | 文档失联 |
| `lces supply-chain-check` | 固定版本的构建输入 | 供应链漂移 |

Gate 1–4 的具体检查项由 `validation.py`、`course_audit.py`、`course_quality.py`、
`release.py` 实现；本文不复述全部检查名，避免两份清单漂移。

## 3. 证据规则

### 3.1 状态词

`pending` · `supported` · `partially_supported` · `contradicted` · `insufficient_evidence` ·
`not_applicable`。旧项目的 `unverified / verified / conflict / unverifiable` 由
`canonical_status()` 映射。

### 3.2 两条硬规则

1. **模型不能给自己核验。** 研究阶段把模型返回的核验状态重置为 `pending`/`unverified`，
   清空审核人。模型输出 `verified` 不产生任何效力。
2. **没有署名，就没有信用。** 没有 reviewer 的 `supported` 会被降回 `pending`。
   `contradicted` 永远阻断，直到冲突被处理或披露。

### 3.3 三层记录不能互相替代

| 层 | 回答的问题 | 单独能否放行发布 |
|---|---|---|
| `research_verification` | 权威来源是否一致 | 否 |
| `substantive_review`（AI） | AI 是否逐条对照过来源 | 否 |
| `conclusion` + `reviewer`（人） | 具名的人是否对这一范围负责 | 是 |

AI 复核记录写入 `internal/qa/structured_evidence_review.json`，`reviewer_kind` 固定为 `ai`，
不能通过改 JSON 变成人工签署。

### 3.4 引文定位

模型只提出候选；`evidence_locator.py` 在指定区块内定位。完全匹配 `verified_exact`，
排版归一化后匹配 `verified_normalized`，其余为 `needs_review` / `rejected` 并写入
`internal/qa/quote_audit.json`。跨区块拼接、省略号、表格重排、数学符号改写不接受。
表格与公式使用结构化证据，`verified_structured` 只做结构校验，不等于语义正确。

## 4. 课程内容审计规则

`lces audit-course` 只读课程实际展示的内容（公开内容模型、阅读版、构建后的 HTML），检查：

- BLEU 等数值必须属于已复核记录；
- 来源冲突必须同时出现两个值并带冲突标记；
- Table 3 的 26.4/25.8 必须保留 `BLEU (dev)` + `newstest2013` + EN-DE 条件；
- 公式与已复核转写按 `latex-tokens/v1` 归一化后匹配（只证明匹配，不证明语义）；
- 已复核但课程未展示的公式、无复核证据的公式都会被报告；
- 来源文本缺失时记为不可核验，不记为通过。

问题按 `blocker` / `major` / `advisory` 分级，`finding_id` 由检查类型、位置、期望值与实际值
稳定生成。报告绑定所读文件的 SHA-256；内容改动后旧报告自动失效，必须重跑。

## 5. 视觉回归

- 基线截图必须来自真实构建；没有基线时状态是 `missing`，永远不算通过。
- 比较结果三态：`matched` / `drifted` / `missing`。漂移默认 `warn`，需要逐张确认或重建基线；
  不得通过放宽阈值隐藏布局退化。
- 截图与实测覆盖 5 个视口、2 个页面；控制台错误、资源加载失败、横向溢出是硬检查。
- 2026-10-24 基线刷新依据：旧基线来自 5 节旧课程（截图内只有 5 个场景），当前课程为 14 节且
  课件已改版。逐张检查了 10 张截图：页面全部加载、0 个 JavaScript 错误、0 横向溢出、静态布局
  与改版前一致；确认差异来自课程扩展与既有主题改版后重建基线，第二次比较为 `matched`。
  这是工程核对，不是人工视觉验收。

## 6. 已知缺口（工程可关闭的）

以下缺口真实存在，报告必须如实显示，不得写成已实现：

| ID | 缺口 | 状态 |
|---|---|---|
| Q-01 | 场景契约缺目标/主张/版本/进入退出状态/复位策略/必检项 | **已实现**：`SceneContract` 扩展 + `scenes.py`；构建时派生并校验，14 个真实场景写入 `internal/qa/scene_contracts.json` |
| Q-02 | 单元级生成（`LearningUnit` → 正文/口播） | **已实现**：构建物化 `CourseMaster → LearningUnit → ScenePlan → SceneContract`；14 个交付单元，`lces generate --unit` 只重生成该单元映射的场景，输入未变自动跳过；`expand-unit` 在证据约束下扩展讲稿并同步视觉 |
| Q-03 | HTML 课件没有录屏模式 | **已实现**：`?record=1` 或 `R`；隐藏顶栏/页脚/控件，1920×1080 时画布精确铺满 |
| Q-04 | 逐场景动画播放/复位未被机检 | **已实现**：`window.__lces` 支持播放/暂停/重播/重置/步进；7 项 Playwright 测试 |
| Q-05 | 视觉基线漂移未经逐张确认 | **已刷新（2026-10-24）**：旧基线是 5 节旧课程；检查后重建，第二次比较 `matched`（依据见 §5） |
| Q-06 | 只有一门真实课程（Attention） | OPEN |
| Q-07 | `superseded` 审核状态未实现 | **部分实现**：增量指纹、未变跳过、构建产物可复现已实现；`superseded` 状态仍 OPEN |

## 7. 当前实测（2026-10-24，Windows 11 / Python 3.13.12）

| 项目 | 命令 | 结果 |
|---|---|---|
| 测试 | `pytest --no-header -o addopts=""` | **711 passed, 49 skipped, 0 failed**（场景 22 + 单元/计划 7 + 计时 8 + 时长/扩展 9 + 生产判定 2） |
| 静态检查 | `ruff check` / `ruff format --check` / `mypy src` | 通过（60 个源文件） |
| 文档机检 | `python scripts/check_docs.py` | 0 错误 / 0 警告 |
| 课程门禁 | `lces validate <attention>` | Gate 3 通过；浏览器 10/10；视觉回归 `pass`（基线已核对重建） |
| 场景运行时 | `tests/test_scene_runtime.py` | 8 项通过：打开/播放/暂停/步进/重播/重置/深链/切场景/录屏几何 |
| 场景契约 | `internal/qa/scene_contracts.json` | 14 个场景，含步骤、时长、目标、主张、证据引用与 `unit_id` |
| 教学单元 | `internal/plan/course_master.generated.json` | 39 个单元（25 个论文覆盖蓝图 + 14 个交付单元），交付单元映射到场景 |
| 自动场景计划 | `internal/qa/scene_plan.generated.json` | 14 个场景；移走作者计划后仍能构建（实测 14/14） |
| 增量生成 | `lces plan-impact` / `generate --unit` | 改一个主张后 5 个引用单元失效；只重生成 1 个单元，其余 4 个保持失效 |
| 内容审计 | `lces audit-course` | `passed`，blocker/major/advisory = 0/0/0，14 条复核记录 |
| 产品门禁 | `lces audit-product` | `blocked`：实测 12.9 分钟低于 20 分钟目标的 80%（blocker=1）；3 项人工记录仅作为发布披露（见 §7.2） |
| 课程规模 | — | 14 个场景、34 条主张、50 条证据、7 个公式、14 条复核记录（0 条人工结论） |
| 发布状态 | `release-check` | 基准课程未发布；`release/v1` 是历史非合规清单，不重建、不重标记 |

跳过项来自平台/依赖限制（Graphviz、Linux-only Motion Canvas、真实模型/网络）。
跳过不等于通过。

### 7.1 已知缺陷守卫

历史缺陷必须转成可执行守卫；测试通过只证明机制存在，不证明真实课程已经正确。

| 编号 | 缺陷 | 守卫 |
|---|---|---|
| REG-001 | 关键主张缺证据 | `key_claims_have_evidence` 失败并阻断（`tests/test_regression_register.py`） |
| REG-002 | 课程缺公式 / 公式未复核 | Gate B 与 `audit-course` 阻断（`tests/test_course_quality.py`、`test_course_audit.py`） |
| REG-003 | `28.4` 缺 `big` 限定 | `bleu_variant_qualifier` 报告（`test_course_audit.py`） |
| REG-004 | `41.0/41.8` 冲突未披露 | 未披露即 `blocked`；披露后 `approved_with_disclosures` |
| REG-005 | 位置编码公式未复核 | AI 复核不等于人工签署；未签署时发布被拒 |
| REG-006 | 人工签署 pending | Gate 4 `structured_evidence_signed` 阻断 |
| REG-007 | 16:9 交互未被证明 | 5 视口浏览器检查（`tests/test_browser_qa.py`） |
| REG-008 | 三个来源哈希指向不同字节对象 | `tests/test_source_map.py::test_reg_008_three_hashes_name_three_byte_objects` |
| REG-009 | 视觉基线缺失或漂移 | `missing / matched / drifted` 三态；缺基线不算通过 |
| REG-010 | 自动检查不能判断科学正确性 | `scientific_review = NOT_RUN`，永远不折叠成 pass |

### 7.2 计时证据（2026-10-24 重测 + 扩展后复测）

- **数据含义：** `measured_seconds` 是 TTS 完整朗读的音频时长；`scene_seconds` 是同一次
  测量的逐场景秒数。它不是学习者时长、动画时长或人工录制时长。
- **旧证据：** `script_sha256` 为 `1d54ef…`，当前讲稿为 `1e3180…`；讲稿改写后没有重新测量，
  因此 `timing_matches_script` 阻断。这是过期证据，不是审计规则错误。
- **首次重测：** 用 `scripts/measure-narration-timing.py`（Windows SAPI `Microsoft Huihui
  Desktop` + FFprobe）对当前讲稿重测：**712.44 秒（11.87 分钟）**，脚本/音频哈希更新；
  `timing_matches_script`、`timing_audio_hash` 通过，`timing_in_range` 阻断。
- **扩展后复测：** unit-105 从 201 字扩展到 456 字；逐单元 TTS 测得全课
  **772.60 秒（12.88 分钟）**，14 个 `scene_seconds`，脚本哈希 `85f647…`。
  哈希检查仍通过；`timing_in_range` 仍阻断，距离 16 分钟还差 **187.4 秒（3.12 分钟）**。
- **根因：** 冻结讲稿约 3341 字，正常语速约 4.7 字/秒；20 分钟目标对应更长的旧讲稿。
  不是计算错误，也不能靠改阈值解决。
- **未解决：** 还需约 3.1 分钟实质讲稿。继续扩展剩余低于预算的 10 个单元，或由产品负责人
  正式修订契约目标。本轮未改目标、未伪造人工记录。

### 7.3 时长预算与内容扩展（2026-10-24）

- **指标分开记录：** 课程目标时长、允许范围（80%–130%）、单元预算、讲稿估算、TTS 实测、
  动画播放时长、最终录制时长是不同的量。`duration-plan` 只把估算与实测分列，不合并。
- **预算模型：** 单元权重 = 基础 + 目标数 + 关键概念数 + 公式数 + 视觉块数 + 主张数 +
  学习检查 + 视觉需求；权重按 20 分钟目标水位分配，单单元 45–480 秒，不按单元数平均。
- **实测有效性：** 只有 `timing_evidence.script_sha256` 等于当前 `speaker_script.json` 的
  SHA-256 时，`scene_seconds` 才作为实测值；否则显示为无效，估算值不会被冒充实测。
- **扩展约束：** 只能引用本单元已有的 claim/evidence；必须为每个公式/表格/实验/结构图
  写 `visual_sync`；长度必须落在预算区间；不得重复句子、不得出现内部编号、不得出现
  证据中没有的数字。失败写入 `internal/qa/expansion_rejected.jsonl`，磁盘文件不变。
- **定向修复：** 扩展未通过时，用失败原因续写缺失段落并合并，最多 3 次；仍失败则不落盘。
- **真实运行（2026-10-24）：** unit-105 扩展 201→456 字，TTS 实测 105.2 秒（预算 93 秒）；
  全课 12.88 分钟；其余 12 个低于预算 85% 的单元仍合计约 3.1 分钟缺口。
- **模型状态：** 本地 Qwen3-8B（约 3.1 tokens/s）的多次尝试（含 3 次修复循环）均因缺少
  `visual_sync` 或长度不足被拒绝；最后一次原始输出在 `internal/qa/expansion_rejected.jsonl`。
  本轮接受的扩展是在同一约束下人工撰写、经系统校验与 TTS 实测的文本；模型自动扩展仍为
  `NOT_RUN`，不冒充成功。
- **生产与发布分离：** `audit-product` 同时输出 `decision`（发布用）与
  `production_decision`（只由自动检查决定）。人工记录作为 `disclosures`，不阻断构建、
  播放与录屏。

## 8. 人工确认的边界

自动检查不能替代：

- 科学结论、公式语义、单位与因果判断；
- 学习者是否真的学会；
- 视觉画面是否"讲清楚了"；
- 最终发布授权。

这些项目在报告中必须保持 `NOT_RUN` / `pending`，并由真实的人记录，AI 不得代填。
正常课程生产不要求这些记录；只有发布到 `release/` 时才要求。

## 9. 变更规则

1. 新规则 ⇒ 新测试；未实现的规则 ⇒ `NOT_RUN`。
2. 不得删除断言、放宽阈值或隐藏问题来让门禁变绿；应登记缺陷并修复。
3. 改动内容或构建产物后，必须重跑受影响的审计；旧报告会因内容哈希失效。
4. 报告只写真实命令与真实结果；测试失败就写失败。
