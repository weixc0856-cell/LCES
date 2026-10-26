# ADR 0004: 课程单一事实来源

对应 SAD-001 §12 ADR-002。状态：Accepted；"场景级真源"仍为 Partial（见 ADR 0005）。

## 背景

同一门课同时存在 `CourseMaster`（内部）、`PublicContent`、`SpeakerScript`、
`ReadingEdition`、`claims.json`、`evidence_ledger.csv` 与构建产物。若允许两份文件
各自成为同一事实的写入源，课件与口播就会长期漂移（PRD §3.3、§14.9）。

## 备选方案

1. 一个巨大 JSON 包含全部内容：破坏公开/内部边界，模板一旦拿到它就会泄漏口播。
2. 每类产物各自生成、人工保证一致：这正是要消除的失败模式。
3. 分实体真源 + 明确派生方向（当前）：课程主数据、场景/单元、来源证据、研究判断、
   人工审核、构建清单、发布决定各自有唯一写入方，派生关系由代码和测试约束。

## 决定

- 课程正文：`content/public_content.json`；口播：`internal/speaker_script.json`（永不渲染）。
- 阅读版：`content/reading_edition.json`，与幻灯片按 `slide_id` 对齐，Gate B 强制集合相等。
- 来源与证据：`internal/source_registry.json` + `internal/evidence_ledger.csv`。
- 研究判断：结构化复核记录；人工结论只在 `ReviewItem.conclusion`，AI 不能写。
- 发布：`release.py` 从显式来源重建 staging，禁止复制工作目录。
- `CourseMaster`/`LearningUnit` 是**规划契约**，尚未成为正文派生源；在 P0-B3 之前
  不得声称"正文由课程主数据派生"。

## 后果

- 正面：公开/内部边界由类型保证；Gate B 能机器检查幻灯片、阅读版、口播三者的一致性。
- 负面：同一内容在三个交付形态中各有一份，重复段落是"阅读版必须更详细"的代价；
  单元级生成（unit queue → PublicContent/SpeakerScript）仍未实现。
- 监测点：出现第四份"同一事实"的权威文件时，必须先删除旧写入方。

## 证据

- `tests/test_rendering.py`（模板只接受 `PublicContent`）、`tests/test_course_quality.py`
  （`reading_matches_slides`、`narration_matches_slides`）、`tests/test_release.py`。
- P7 报告 §1.3：口播稿不进入公开 HTML 是边界，不是遗漏。

## 回滚

若未来由 `CourseMaster` 派生正文，必须先提供按单元重建 `PublicContent`/
`SpeakerScript` 的确定性装配器与等价性测试，再切换写入方；不得双写。
