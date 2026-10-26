# 仓库减负报告

**日期：** 2026-10-24  
**范围：** 文档、开发流程、以及只服务于审批/签核的材料。未改动课程内容、未提交、未推送。  
**恢复位置：** 所有被移出主线的文件保存在 `var/archive/slimdown-2026-10-24/`（已被
`.gitignore` 忽略）。未跟踪文件没有直接删除，确认不需要后可整目录删除。

---

## 1. 清理前后规模

| 指标 | 清理前 | 清理后 | 变化 |
|---|---|---|---|
| `docs/` 文件总数 | 140 | 77 | −63（−45%） |
| `docs/` Markdown | 86 | 34 | −52 |
| `docs/design/` 文件 | 111 | 54 | −57 |
| 权威入口文档 | 3 份外部 PRD/SAD/TDD + 8 份状态/治理文档 | 4 份（README + PRODUCT + ARCHITECTURE + QUALITY） | 单一主线 |

`docs/` 现有 77 个文件：34 Markdown、41 JSON、2 HTML。JSON/HTML 全部是测试夹具或
证据快照，不是文档正文。

## 2. 处置分类

| 类别 | 数量 | 说明 |
|---|---|---|
| 保留（权威） | 4 份 | `README.md`、`docs/PRODUCT.md`、`docs/ARCHITECTURE.md`、`docs/QUALITY.md` |
| 保留（专项技术） | 7 份 | 内容契约、证据规则、本地模型、MCP、媒体、依赖、评测 |
| 保留（决策记录） | 12 份 | `docs/ADR/0001…0012`，只作为决策档案，不再是必读入口 |
| 保留（夹具/证据） | 54 个文件 | 内容快照、证据包、p9 课程基线；被代码或测试直接读取 |
| 合并 | 8 份 | 治理、基线、差距、阶段计划、实现日志、验收、开发规则、缺陷登记 |
| 移出主线 | 57 份 | `docs/design/**` 的历史计划、试跑、验收、审批、试测材料 |
| 移除代码 | 2 个文件 | 签核表生成脚本及其测试 |

## 3. 合并去向

| 原文档 | 合并到 |
|---|---|
| `GOVERNANCE.md` | 规则进入 `README.md`、`ARCHITECTURE.md`（开发规则）、`AGENTS.md` |
| `AUTHORITY_BASELINE.md`、`GAPS.md`、`IMPLEMENTATION_STATUS.md` | 现状与实测进入 `QUALITY.md` §7；工程缺口编号化为 `QUALITY.md` §6（Q-01…Q-07） |
| `ACCEPTANCE_TESTS.md`、`REGRESSION_REGISTER.md` | 门禁命令进入 `QUALITY.md` §2；缺陷守卫表进入 §7.1（REG-001…REG-010） |
| `DEVELOPMENT.md` | 开发规则进入 `ARCHITECTURE.md` 的 "Development rules" |
| 外部 PRD / SAD / TDD | 产品目标与新 `PRODUCT.md`；实现描述以 `ARCHITECTURE.md` 为准 |
| `docs/authority/MANIFEST.json` | 移除；外部权威文档不再是开发入口 |

## 4. 实际删除/移出的主要内容

**人工审批与试测流程（不再作为正常生产前置条件）：**

- `docs/design/p9/` 的契约审查记录、再审决定、有条件批准、执行状态、来源核查报告、
  D1–D4 实施包、学习者试测协议与结果模板（共 20 个文件）。
- `docs/design/p6/learner-trial/` 全套材料（6 个文件）。
- `scripts/export-evidence-signoff.py`（签核表生成器）与 `tests/test_signoff_worksheet.py`。
- `docs/design/release-acceptance-2026-10-24.md`、`course-recovery-acceptance-2026-10-24.md`、
  `course-product-qualification-2026-10-24.md` 等人工验收报告。

**历史计划与重复报告：**

- `docs/design/motion-canvas-p*.md`（9 份阶段计划与验收）、`course-production-plan-v1`、
  `course-production-review-v2`、`research-trial`、`quote-locator-trial`、P6/P7/P8 执行报告。
- 重复的课程审计/产品审计 JSON 快照（保留一套被测试读取的快照即可）。

**保留原因：** 上述文件均无代码、测试、CI 或提示词依赖；删除前逐文件做了引用扫描。

## 5. 权威文档位置

| 文档 | 作用 |
|---|---|
| `README.md` | 安装、主要命令、输出目录、文档索引 |
| `docs/PRODUCT.md` | 唯一产品目标、用户流程、交付物、非目标 |
| `docs/ARCHITECTURE.md` | 实际架构、数据流、模块边界、开发规则、ADR 索引 |
| `docs/QUALITY.md` | 五维质量标准、门禁、证据规则、实测结果、缺口与缺陷守卫 |

`AGENTS.md` / `CLAUDE.md` 只指向这三份文档，不复制规则。

## 6. 代码、测试、CI 与引用的更新

- `scripts/check_docs.py`：必需文档改为新入口；移除 ADR 编号与外部权威 manifest 校验；
  保留链接、`lces` 命令、历史计划横幅检查。
- `tests/test_docs_governance.py`：按新入口重写；新增"干净树应无错误"用例。
- `scripts/build-review-packet.py`：移除学习者试测章节与目录复制；其余核验包能力保留。
- `scripts/audit-evidence-sources.py`、`scripts/preflight-scene-recordings.py`：示例输出路径从
  `docs/design/p9/` 改为 `var/`。
- `tests/test_regression_register.py`、`tests/test_p23_filesystem_boundaries.py`：更新失效的
  文档路径注释。
- ADR 0005/0006/0011/0012 中指向已归档文档的引用改为 `QUALITY.md` 或"已归档"。
- `docs/EVIDENCE_GOVERNANCE.md`：明确人工复核是发布时的可选项，不是正常生产前置条件。
- CI 无需改动：`.github/workflows/ci.yml` 仍运行 `python scripts/check_docs.py`，只是必需文档
  列表随代码更新。

## 7. 实际执行的检查

| 命令 | 结果 |
|---|---|
| `python scripts/check_docs.py` | 47 个 Markdown，**0 错误 / 0 警告** |
| `pytest --no-header -o addopts=""` | **663 passed, 49 skipped, 0 failed**（46.40s） |
| `ruff check src tests scripts` | 通过 |
| `ruff format --check src tests` | 122 个文件已格式化 |
| `mypy src` | 通过（56 个源文件） |
| `lces validate projects/attention-is-all-you-need` | 通过；浏览器 10/10；视觉回归 `warn`（10 张漂移，未变） |
| `lces audit-course projects/attention-is-all-you-need` | `passed`，blocker/major/advisory = 0/0/0 |
| 5 个保留脚本 `--help` | 全部退出码 0 |
| `python scripts/build-review-packet.py --project … --design docs/design/p6 --out var/handoff/…` | 生成 62 个文件、zip + 7z，退出码 0 |

**课程数据未被改动**（SHA-256 与冻结基线一致）：

```
d9326e536ad382bf  content/public_content.json
55166aff97f74a4e  content/reading_edition.json
4e27bcf44882e9b4  content/outline.json
1e3180b9da594d0e  internal/speaker_script.json
4369098523558ca4  build/slides/index.html
d634bb1c60c5a48d  build/reading_edition.html
ff5a2c13da1d6810  internal/evidence_ledger.csv
e44328cb8d3109d  internal/claims.json
```

`internal/plan/course_contract.json` 与 r1 基线不同，是清理前已存在的 1.3 修订，不是本轮改动。
QA 报告因重跑而更新了时间戳，结论未变（Gate B 仍为 `blocked`）。

## 8. 暂缓清理及必要性

| 内容 | 原因 |
|---|---|
| `docs/design/p6|p7/content-snapshot/**`、`evidence-packets/**` | 被 `course_audit.py`、`release.py`、`browser_qa.py` 及多个测试直接读取，是回归夹具 |
| `docs/design/structured-evidence-review-2026-10-24.json` | `tests/test_structured_review.py` 的固定输入 |
| `docs/design/evidence-remediation-2026-10-24.json`、P6 审读记录 | 核验包脚本的输入，且是来源处置证据 |
| `docs/design/p9/course-baseline-*.json` | 课程完整性基线，冻结/校验脚本的默认输入 |
| `docs/design/MOTION_CANVAS.md` | `timeline.py` 引用的帧时间规范 |
| 12 份 ADR | 现存的架构决策；被 `ARCHITECTURE.md` 索引，不属于重复方案 |
| `course_quality.py` 中的学习者试测字段与 `accept-course` | 仍服务于可选的发布验收；正常 `run/build/validate` 不依赖它。删除会改变 Gate B 语义并破坏大量测试，未在本轮做 |

## 9. 清理后的开发入口与日常流程

**入口：** `README.md` → `docs/PRODUCT.md` → `docs/ARCHITECTURE.md` → `docs/QUALITY.md`。
专项问题再查 `CONTENT_CONTRACTS` / `EVIDENCE_GOVERNANCE` / `ADR`。

**日常流程：**

```
ingest → research → outline → generate → build → validate
      → audit-course → audit-product（可选）→ 浏览器录屏
```

**提交前：** `pytest`、`ruff check`、`ruff format --check`、`mypy src`、
`python scripts/check_docs.py`。

**报告节奏：** 不再为每轮开发生成日期化状态报告。结论写入 `QUALITY.md`（质量标准与实测）、
`ARCHITECTURE.md`（实现变化）或 ADR（决策）。本报告是本次清理的唯一一次性报告。

## 10. 未做的事

- 没有创建提交或推送。
- 没有删除未跟踪的归档文件；它们仍可从 `var/archive/` 恢复。
- 没有删除发布门禁代码（`release.py`、`accept-course`、`approve-course-contract`）；
  它们现在是可选的发布能力，不是正常生产前置条件。
- 没有执行首轮指令中的功能开发（场景契约字段、单元级生成、录屏模式）。这些仍是
  `QUALITY.md` §6 的 Q-01…Q-07。
