# LECS 课程内容一致性与发布门禁验收（2026-10-24）

对象：`projects/attention-is-all-you-need`  
任务：`LECS — Course Content Consistency & Release Gate`  
结论：**发布会话被正确阻断，P0-B3 保持关闭。** 证据机制、课程审计和发布门禁都已落地并有负向测试；
课程内容本身仍有未修复的高风险问题，七条记录仍缺正式人工签署。

> 本文只记录本轮实际执行过的命令与产物。模板、脚本和测试通过不等于课程事实正确。
> 代码变更已提交并推送到 `feat/course-content-audit-release-gate`（`0f421db`），
> 推送后在干净工作树重新跑过工程回归。**没有重建、覆盖或撤回 `release/v1`**，
> 也没有提交任何课程工作区数据（`projects/` 被忽略）。

## 一、执行环境与结果

| 命令 | 结果 |
|---|---|
| `pytest --no-header`（推送基线干净工作树） | **568 passed, 49 skipped** |
| `ruff check src tests scripts`（推送基线） | passed |
| `ruff format --check`（推送基线） | 118 files already formatted |
| `mypy src`（推送基线） | passed（52 个源文件） |
| `lces review-evidence-ai` ×7 | 七条 AI 实质复核写入；人工结论保持 `pending` |
| `scripts/validate-review-record.py` | 7/7 链接有效；`pending human conclusions: 7/7` |
| `lces audit-course`（当前课程） | `needs_correction`：blocker=0, major=2, advisory=8 |
| `lces audit-course --scan release/v1` | `blocked`：blocker=3, major=1, advisory=12 |
| `lces validate` | **exit 1**：2 项阻断（Gate 1 证据缺口 + Gate 2 课程审计） |
| `lces release-check --version v1` | **exit 1**：`decision=blocked`，4 项阻断 |

### 推送基线

- 分支：`feat/course-content-audit-release-gate`
- 提交：`0f421dba6d2bbea82a50c6dec64e8796f426a2d7`（本地 HEAD 与 `origin` 一致）
- 干净工作树：`git worktree add --detach ../LECS-pushed-baseline 0f421db`，在该工作树中执行
  全量测试、ruff、format 与 mypy，结果见上表。
- 真实课程复跑在推送提交的同一代码树上执行（`projects/` 被 `.gitignore` 排除，
  课程工作区不属于提交内容）。`validate`、`audit-course`、`release-check` 的结果与
  提交前一致，没有出现只在本地通过的偏差。


产物：

- `projects/attention-is-all-you-need/internal/qa/structured_evidence_review.json`（项目真源）
- `docs/design/structured-evidence-review-2026-10-24.json`（同一记录的归档副本）
- `projects/attention-is-all-you-need/internal/qa/evidence_review_audit.jsonl`（AI 复核审计行）
- `projects/attention-is-all-you-need/internal/qa/course_content_audit.json`（当前课程）
- `docs/design/course-content-audit-2026-10-24.json`（归档副本）
- `docs/design/release-v1-content-audit-2026-10-24.json`（对已发布 v1 的只读审计）
- `var/acceptance-validate.log`、`var/acceptance-release-check.log`（命令输出）

## 二、A. 来源与证据（P0）

### 七条记录的真实核对结果

复核发现原记录有三个必须修正的问题：

1. **区块指针过期。** Table 2 的 Transformer 行在当前 source map 中位于
   `source-001:b0048`（原记录写 `b0050`）；Table 3 的行数据位于 `source-001:b0051`
   （原记录写 `b0052`）。新区块的 section 标签仍显示旧节名，这是切块跨节造成的标签漂移。
   七条记录的 `chunk_id` 已全部指向真实区块。
2. **冲突口径不完整。** 原记录只写“NeurIPS Table 2/§6.1 = 41.0；arXiv 摘要 = 41.8”。
   本地 arXiv 抽取的 **Table 2 行本身也是 41.8**（`b0048`），而 §6.1 正文是 41.0
   （`b0050`）、摘要是 41.8（`b0026`）。记录已补全为完整冲突，仍未裁决。
3. **主张范围过宽。** Table 3 的两条主张现在写明 `BLEU (dev)`、EN-DE、newstest2013；
   base 25.8 明确“取第一行，同值也出现在 (A) 组 16 头变体”；28.4 明确属于 big 模型。
   公式主张改为完整转录（含符号与维度口径）。

| review_id | 真实区块 | 修正后主张 | AI 实质复核 | 人工 |
|---|---|---|---|---|
| `review-table2-base-27.3` | b0048 | base EN-DE newstest2014 = 27.3 | consistent | pending |
| `review-table2-big-ende-28.4` | b0048 | big EN-DE newstest2014 = 28.4 | partial（claim-002 未写 big） | pending |
| `review-table2-big-enfr-conflict` | b0048 / b0050 / b0026 | 41.0 / 41.8 未裁决冲突 | consistent | pending |
| `review-table3-big-26.4` | b0051 | big BLEU (dev) EN-DE newstest2013 = 26.4 | consistent | pending |
| `review-table3-base-25.8` | b0051 | base BLEU (dev) EN-DE newstest2013 = 25.8 | consistent | pending |
| `review-formula-attention` | b0033 | Eq. (1) 完整转录 | consistent | pending |
| `review-formula-multihead` | b0035 | §3.2.2 两行公式 | consistent | pending |

### 三层分离

- 研究核验：`research_finding=verified` / `source_conflict`，`reviewed_by_human=false`。
- AI 实质复核：`substantive_review.reviewer_kind=ai`，审计行
  `layer=ai_substantive_review`、`conclusion_unchanged=pending`。
- 人工签署：`reviewer` / `reviewed_at` / `basis` / `conclusion`，七条全部 `pending`。

Pydantic 拒绝 `reviewer_kind=human`，`review-evidence-ai` 不提供写 conclusion 的参数，
所以 AI 记录无法仅靠改 JSON 变成签署。

### 未通过项

- **正式人工签署 7/7 缺失。** 这是发布被拒绝的首要原因，不能在验收中绕过。
- 原记录中的 `program_status` 是按旧 source map 计算的历史值。本轮修正了指针，
  但没有把任何记录提升为 `verified_structured`；`table_row_span_too_wide` 等旧原因
  仍按历史值保留，并在 `program_precheck` 中标注不可复现。

## 三、B. 公式与表格

### 当前课程内容（`content/` 与 `build/`）

审计版本 `b653ec5af0bc`，blocker=0，major=2，advisory=8：

- **major**：两条已复核公式（Eq. 1 与 Multi-Head）都没有出现在当前课程内容中。
  当前 `public_content.json` 只有 3 节，没有任何 `formula` 块。
- **advisory**：8 处 28.4 BLEU 没有标明它属于 Transformer (big)。
- 未发现：错误数值、未披露冲突、测试集/dev 混淆、错误公式。

结论：**当前内容不是可发布版本**。它相对 v1 丢失了公式、表格和“局限性”章节。

### 已发布 `release/v1`

审计 `0b00175dd34a`，blocker=3，major=1，advisory=12：

- **blocker** `source_conflict_disclosed`：`reading_edition.html` 只写 41.8，没有 41.0 与冲突说明。
- **blocker** `source_conflict_disclosed`：`slides/index.html#slide-004` 同上。
- **blocker** `formula_matches_review`：位置编码公式 `PE(pos,2i)=sin(pos/10000^{2i/d_model})`
  没有对应的结构化证据复核记录（未核验公式）。
- **major** `reviewed_formula_present`：Multi-Head 公式未展示。
- 通过项：`release/v1` 的缩放点积注意力公式与已复核转录在 `latex-tokens/v1`
  规范化后一致（`\frac`/`√`/括号差异被正确归一）。

结论：**v1 是在门禁生效前发布的，按当前政策不应视为可发布版本。** 是否需要撤回或重建，
是人工发布决定，本轮没有改动发布目录。

### Table 2 / Table 3 数值

当前课程只出现 28.4，引用 `source-001`，来自已复核记录；27.3、41.0、41.8、26.4、25.8
没有出现在当前内容中。v1 出现的 41.8 触发冲突披露阻断。

## 四、C. 写回与审计

- 写回使用现有 CLI：`review-evidence-ai` 追加审计行并以原子替换写回 JSON；
  人工签署仍只能通过 `review-evidence` 写入。
- `scripts/validate-review-record.py` 重新校验来源、区块、claim 与论文要素链接：7/7 有效。
- 课程审计是只读的：不修改内容、不签署、不发布。
- 审计报告绑定 4 个文件的 SHA-256（`content/public_content.json`、
  `content/reading_edition.json`、`build/slides/index.html`、`build/reading_edition.html`）。
  任一文件变化，旧报告立即过期。
- 问题 ID 由 `check_type + location + expected + actual` 计算；重复运行得到相同 ID，
  报告整体重写，不追加重复项。

## 五、D. 发布与回归：负向测试

`tests/test_course_audit.py`（26 个测试）与发布门禁测试覆盖：

| 计划要求 | 测试 | 结果 |
|---|---|---|
| 41.8 替代 41.0、删除冲突说明 → 阻断 | `test_undisclosed_conflict_blocks`、`test_release_is_refused_when_the_conflict_is_undisclosed` | 通过 |
| 保留 41.0 但删除来源定位 → 不能直接通过 | `test_review_without_a_locator_blocks` | 通过 |
| 来源不可访问 → 不判为正确 | `test_missing_source_text_is_not_a_pass` | 通过 |
| 公式分母/转置被改 → 发现差异 | `test_formula_denominator_change_is_detected`、`test_formula_transpose_removal_is_detected` | 通过 |
| Table 3 的 BLEU(dev) 误标为测试集 → 发现 | `test_table3_value_in_test_context_blocks` | 通过 |
| Table 3 缺 dev 条件 → 要求修正 | `test_table3_value_without_condition_needs_correction` | 通过 |
| research=verified 但人工 pending → 不放行 | `test_release_is_blocked_while_evidence_is_unsigned` | 通过 |
| 审核后修改内容 → 旧结论失效 | `test_release_check_detects_content_edited_after_the_audit` | 通过 |
| 发布资产不是被审计版本 → 阻断 | `test_release_asset_must_match_the_audited_build` | 通过 |
| 重复审计不重复追加问题 | `test_finding_ids_are_stable_across_runs` | 通过 |
| 未复核公式 → 阻断 | `test_unreviewed_formula_blocks` | 通过 |
| AI 复核不能冒充签署 | `test_ai_substantive_review_is_not_a_human_signature`、`test_substantive_review_rejects_a_human_kind` | 通过 |

发布决策四类已实现：`blocked`、`needs_human_review`、`approved_with_disclosures`、`approved`。
`release-check v1` 的实际输出：

```
decision=blocked
structured_evidence_signed: 7 条全部 pending
source_conflicts_acknowledged: review-table2-big-enfr-conflict
course_content_audit_passed: needs_correction（两条已复核公式未展示）
release_matches_audited_content: slides/index.html、reading_edition.html 与审计版本不一致
```

## 六、E. 端到端真实试跑结果

| 检查 | 结果 |
|---|---|
| 来源可访问、版本与定位可追溯 | 通过（source-001 与 arXiv/NeurIPS 定位） |
| 七条记录关联真实 claim / chunk / paper | 通过（links 7/7；区块已修正） |
| 研究核验与正式签署独立存储 | 通过（三层 + 测试） |
| 41.0 / 41.8 冲突完整保留 | 记录通过；**课程 v1 未披露 → 未通过** |
| 两条公式的课程展示与原文一致 | 当前内容无公式；v1 的 Eq.1 一致、PE 未复核 → 未通过 |
| Table 2 / Table 3 数值语境一致 | 当前内容通过（仅 28.4）；v1 未披露 41.8 → 未通过 |
| 列语义不明确的表格不自动通过 | 通过（程序保持 `needs_review`） |
| 缺字段、错误 ID、断链输入被拒绝 | 通过（既有 CLI 测试 + 本轮 links 校验） |
| 冲突项的通过路径要求显式确认 | 通过（`--conflict-ack`） |
| JSON 原子写回、审计记录可追溯 | 通过 |
| 错误数值和错误公式触发阻断 | 通过（负向测试 + 真实 v1 审计） |
| 缺少必需人工签署时不能放行 | 通过（release-check 实际拒绝） |
| 内容修改后旧审计失效 | 通过 |
| 结果可重复、产物版本可识别 | 通过（稳定 finding ID、`course_version`） |

## 七、新发现的阻断问题（本轮未修复）

1. **Gate 1 证据缺口。** `claims.json` 有 22 条主张，但台账中 claim-001、claim-002、
   claim-003 没有任何支持证据；`lces validate` 因此阻断。
   这三条是早期内容阶段的主张，与后一次研究运行的 claim 编号没有合并。
   修复需要重新研究或人工把真实证据行关联到这三条主张；**不能靠复制证据行凑数**。
2. **课程内容回退。** 当前 `content/` 只有 3 节，丢失 v1 中的公式、Table 1/3 与局限性章节；
   覆盖矩阵仍报告“必需要素均有教学单元”，说明覆盖矩阵反映的是规划，不是实际内容。
3. **v1 已发布但不符合现行门禁。** 41.8 未披露，且包含一条未复核公式。是否撤回、重建或
   补发勘误，属于人工发布决定。
4. **人工签署缺失（7/7）。** 没有人工 `pass`，任何发布都不放行。
5. **程序状态不可复现。** 旧 source map 的 section 标签在表格边界漂移，导致历史
   `program_status` 无法按当前数据重算。已修正指针并保留历史原因，未提升任何状态。

## 八、P0-B3 是否重新开放

| 条件 | 结果 |
|---|---|
| 七条记录的研究结论与真实 claim 一致 | 通过（本轮修正；AI 记录在案） |
| 41.0 / 41.8 冲突被准确建模和披露 | 证据通过；课程未披露 → **未通过** |
| 公式转录与课程实际展示一致 | Eq.1 一致；PE 未复核；Multi-Head 未展示 → **未通过** |
| 课程解释中的高风险错误得到处理 | **未通过**（公式缺失、big 限定缺失） |
| 研究核验与正式人工签署保持分离 | 通过 |
| 发布阻断和负向回归测试通过 | 通过 |
| 全量测试、lint、format、mypy 通过 | 通过 |
| 未来所有数学公式均能自动语义验证 | 本阶段不要求 |

**决定：P0-B3 保持关闭，`release/v1` 在当前政策下不放行。** 结构化证据机制本身验收通过，
但课程事实与内容发布验收未通过；不因机制通过而推翻内容失败。

## 九、下一步（按优先级）

1. 人工签署七条结构化记录（冲突项需 `--conflict-ack` 并写明 41.0/41.8 口径）。
2. 修复 Gate 1：为 claim-001/002/003 关联真实证据，或重新运行研究生成台账。
3. 恢复课程内容：展示并解释两条已复核公式，把 28.4 标为 Transformer (big)；
   若覆盖矩阵声称覆盖，则内容必须真的覆盖。
4. 处理 v1：重建并在 41.8 处披露 41.0 与冲突来源，或撤回该版本。
5. 上述完成前不重开 P0-B3，也不再扩展证据状态模型。
