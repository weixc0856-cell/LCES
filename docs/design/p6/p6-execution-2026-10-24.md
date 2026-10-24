# LECS P6 执行报告：人工验收准备、争议核查与学习者试测准备

日期：2026-10-24  
分支：`feat/course-content-audit-release-gate`  
起始提交：`703dc5a71e7b399425ccccea73c099dd064d6a6c`（本地与 `origin` 一致，工作区干净）  
对象：`projects/attention-is-all-you-need`  
最终状态：**P6 工程准备完成；Gate A / B / C 均未通过，保持 NO-GO。没有创建 v2、没有审批、没有发布。**

> 本轮只做可由工程与研究代理完成的准备工作：审核包、来源核查、内容审读、试测材料、视觉表、
> 内容快照与回归。所有人工签署、学习者数据、视觉确认和发布授权仍为空。

## 0. 交付物索引

| 交付物 | 位置 |
|---|---|
| P6 执行报告 | 本文件 |
| 8 项证据审核包 + 索引 | [`evidence-packets/index.md`](evidence-packets/index.md)、`evidence-packets/*.json` |
| 来源争议与核心主张核查 | [`source-dispute-review-2026-10-24.md`](source-dispute-review-2026-10-24.md) |
| 8 节课程内容审读 | [`course-content-review-2026-10-24.md`](course-content-review-2026-10-24.md) |
| 学习者试测材料 | [`learner-trial/README.md`](learner-trial/README.md)（题目、答案、日志、反馈、结果模板） |
| 视觉审核表 | [`visual-review-2026-10-24.md`](visual-review-2026-10-24.md)、`.json` |
| 候选内容快照 + 哈希清单 | [`content-snapshot/manifest.json`](content-snapshot/manifest.json) |
| 证据整改逐条记录 | [`../evidence-remediation-2026-10-24.json`](../evidence-remediation-2026-10-24.json) |

## 1. P6-A：证据审核包

新增只读命令 `lces export-review-packets`（`src/content_studio/review_packets.py`，5 个测试）。
每个包包含：稳定 review ID、原始主张、来源名称/版本/章节/区块、原文切片及 SHA-256、课程使用位置、
支持范围、反证/冲突、局限、歧义、审核问题、结论选项、空签署字段与 CLI 模板。

- 审核记录文件 SHA-256：`1060f134131716167e99649daf34ebbb8bef8a887d5c99aa9f4667bbbcb0d7ea`
- 本地来源文本 SHA-256：`c27a7d19619add42f30e61303d0b7e658a55d783b7353b1eb088e6243ba12c7d`
- 8/8 包均可定位；`unresolved=0`；所有 `current_conclusion=pending`。
- 本地来源版本明确为 **arXiv HTML v7**；NeurIPS 2017 作为 `external_source_*` 单独记录，
  不与本地文本混写。

| review_id | 包 SHA-256（前 12） | 人工结论 |
|---|---|---|
| review-table2-base-27.3 | `ab6f20f646ef` | pending |
| review-table2-big-ende-28.4 | `8fbc72ff2cea` | pending |
| review-table2-big-enfr-conflict | `6f522d99e4a5` | pending |
| review-table3-big-26.4 | `0bf6dad5b76c` | pending |
| review-table3-base-25.8 | `7f01d71e3576` | pending |
| review-formula-attention | `dc6e884253b5` | pending |
| review-formula-multihead | `2daa8ba1ade9` | pending |
| review-formula-positional | `b9d9428f00e1` | pending |

局限：本轮没有重新下载 NeurIPS PDF；外部版本信息来自既有研究核验记录。

## 2. P6-B：争议与核心主张

详见 [source-dispute-review-2026-10-24.md](source-dispute-review-2026-10-24.md)。摘要：

| 问题 | 来源核对 | 状态 |
|---|---|---|
| EN-FR 41.0 / 41.8 | 本地 arXiv v7 Table 2/摘要 41.8，§6.1 41.0；NeurIPS 记录 41.0 | 来源已核对；**待人工裁决** |
| claim-001 取代循环层 | evidence-033（§7）直接支持 | 待人工核验 |
| claim-023 摒弃卷积 | evidence-034（摘要）直接支持 | 待人工核验 |
| 三个公式 | 与 §3.2.1/§3.2.2/§3.5 逐项一致 | 待人工签署 |
| Table 2/3 行列 | 本地表行/脚注已核对 | 待人工确认列语义 |
| 优化器/EN-FR dropout 细节 | 原文存在，但**证据台账无对应行** | 发现缺口，待整改 |

没有自动裁决冲突，没有修改任何 `conclusion`。

## 3. P6-C：课程内容审读

详见 [course-content-review-2026-10-24.md](course-content-review-2026-10-24.md)。8 节均可审读，
公式解释、实验口径与局限达到结构完整；发现：

- **F-01（major）**：口播含 Adam/ warmup/ EN-FR `P_drop` 等台账未覆盖的具体数值。
- **F-02（minor）**：幻灯片未写 `d_model=512`/`d_ff=2048`，口播写了。
- **F-03（minor）**：口播“正弦编码不参与梯度更新”未在证据中点明。
- **F-04（minor）**：课程只写“arXiv 版本”，未写 `v7`。
- **F-05（advisory）**：部分检查答案过短。
- **F-06（major，验收项）**：19.96 分钟是 TTS 实测，不是学习者时长。
- **F-07（advisory）**：10 张截图与旧基线不同。

本轮没有修订课程内容；这些问题需要人工决定后再改动，避免在验收准备阶段悄悄改变候选版本。

## 4. P6-D：学习者试测准备

[`learner-trial/`](learner-trial/README.md) 已包含：

- `questions.md`：10 道独立作答题目（无答案）。
- `answer-key.md`：参考答案、评分依据、0/0.5/1 评分规则；7 分只是建议观察线，不是验证过的合格线。
- `session-log-template.csv`：匿名参与者、课程起止、逐题得分、错误类型、备注。
- `feedback.md`：6 个开放式问题。
- `results-template.json`：`status=not_executed`，`participants=[]`，`summary=null`。
- `README.md`：协议与数据规则（匿名、不得用 TTS 代替学习者时长、不得写入模拟数据）。

**状态：准备完成，试测未执行。没有参与者，也没有任何学习者结果。**

## 5. P6-E：视觉与版本追溯

- 视觉审核表：10 个视口（slides/reading × desktop/mobile/hd/qhd/uhd），每项含截图与基线
  SHA-256、自动化结果、空的人工结论。自动化：加载/JS/资源/溢出 pass；视觉基线 warn。
- **10/10 待人工审核**，没有自动批准基线。
- 候选内容快照：`content-snapshot/` 含公开内容、阅读版、大纲、契约、计时、内容审计、
  Gate B 审计、复核记录与构建 HTML；`manifest.json` 记录逐文件 SHA-256 与版本：
  - `course_version`：`7bf523070d268657…`
  - `content_version`：`249d2f580996a0da…`
  - 契约 `1.0`，状态 `draft`
  - 复核记录 SHA-256：`1060f13413171616…`
  - 来源文本 SHA-256：`c27a7d19619add42…`
  - 构建 HTML SHA-256：`slides 05f6a1068b61…`，`reading 78934d5891b7…`
- **讲解稿 `internal/speaker_script.json` 不进入快照**（公开/内部边界），只记录其
  SHA-256 `1d54ef0a5158…` 与大小；恢复时需单独保管并校验。
- 明确：`projects/` 不进入 Git，快照是候选版本的恢复辅助，不是 Git 可重建的替代品。

## 6. P6-F：回归验证

| 命令 | 退出码 | 结果 |
|---|---|---|
| `pytest --no-header` | 0 | **587 passed, 49 skipped**（新增 5 个审核包测试） |
| `ruff check src tests scripts` | 0 | passed |
| `ruff format --check` | 0 | 123 files formatted |
| `mypy src` | 0 | passed（54 files） |
| `lces build` | 0 | 8 节构建成功 |
| `lces validate` | 0 | Gate 1/2/3 warn，无阻断；Gate B 状态 warn |
| `lces audit-course` | 0 | passed，`7bf523070d26`，0/0/0 |
| `lces audit-product` | 2 | `needs_human_review`，blocker=0，human=2 |
| `lces release-check v1` | 1 | `decision=blocked`（签署、冲突、v1 资产、Gate B 人工项） |

Gate B 的 2 个人工项：契约未批准、课程产品验收记录缺失。

## 7. 状态分类

| 类别 | 内容 |
|---|---|
| **已由自动化验证** | 587 测试、ruff/format/mypy、内容审计 0/0/0、Gate B 自动检查 0 blocker、页面溢出/加载检查、审计哈希绑定 |
| **已由来源核对、仍待人工裁决** | 41.0/41.8 冲突、claim-001/023、三个公式、Table 2/3 行列；见 P6-B |
| **已由真实审核者签署** | **无**（8/8 pending） |
| **需要真实学习者试测** | 10 道检查题与课程完成时长；见 P6-D |
| **尚未执行 / 无法验证** | 学习者数据、人工视觉确认、NeurIPS PDF 重新下载、Gate B 人工验收、发布审批 |

## 8. 人工待办与阻塞

1. **产品契约批准**：`lces approve-course-contract --by <产品负责人>`；当前 `draft`。
2. **八条证据签署**：真实审核者逐条核对审核包后运行 `lces review-evidence`；
   冲突项必须 `--conflict-ack` 并写明 41.0 口径。
3. **F-01 整改**：为 §5.3 优化器设置与 EN-FR `P_drop=0.1` 补证据，或从口播删除；
   F-02/F-03/F-04 同步修订。
4. **真实学习者试测**：至少一名真实参与者按 `learner-trial/README.md` 执行，填写真实数据。
5. **人工视觉确认**：逐项审核 10 张截图，确认后更新基线。
6. **Gate B 验收**：`lces accept-course --by <验收人> --timing-confirmed --visual-confirmed --checks-confirmed`。
7. **Gate C**：签署与验收完成后 `lces approve --version v2`、`lces release`、`lces release-check`。

在 1–6 完成前，Gate A/B/C 均不通过；`release/v2` 不创建，`release/v1` 保持历史状态。

## 9. 结论

- P6 的人工验收**准备**已完成：审核包、争议核查、内容审读、试测材料、视觉表、内容快照、
  回归结果均可复核。
- 工程与自动化层通过；证据与课程产品层仍待人工；没有任何签署或学习者数据。
- **最终状态：NO-GO。**
