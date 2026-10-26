# ADR 0005: 场景契约

对应 SAD-001 §12 ADR-003。状态：Accepted（目标）；实现 Partial。

## 背景

PRD §5 要求场景成为内容、动画、口播、证据与录制操作之间的基本单位，并列出 14 个
必须字段（稳定 ID、目标、结论、证据引用、动画状态、起止状态、复位规则、验收规则等）。

现状是分散的：

- 教学单位：`LearningUnit`（objectives/key_concepts/claim_ids/evidence_ids）——规划契约，
  尚未驱动正文。
- 交付单位：`PublicSlide`（正文）+ `ScriptSection`（口播，按 `slide_id` 对齐）。
- 动画单位：`SceneContract`（`scene_id`、`duration_ms`、`transition_in/out`、
  `evidence_refs`、`data`），但没有 `objective_ids`、`claim_refs`、`entry_state`、
  `exit_state`、`reset_policy`、`required_checks`、`scene_version`。

## 备选方案

1. 立刻把 `SceneContract` 扩成 PRD 全集并要求所有场景填写：现有 14 节课程没有这些
   数据，强制会让构建失败或产生大量空字段（"看起来实现了"）。
2. 维持分散模型、只在文档里声称已满足：违反 ADR-002 与 PRD §14.10。
3. 增量收敛（当前）：先统一 ID 与引用，再补状态字段，最后启用门禁。

## 决定

- 短期：`slide_id` 是课程、口播、阅读版、审计之间的公共键；`SceneContract.scene_id`
  是渲染与录制的公共键；两者通过 `AnimationBlock.scene_file` 关联。
- 中期（P0-B3）：新增 `Scene` 聚合或扩展 `SceneContract`，补齐 PRD §5.1 的 14 项；
  在数据齐备前以 `required_checks` 记录"未填"而不是默认通过。
- 任何新字段必须同时进入 JSON Schema、测试和 Gate 检查；不接受"仅为文档"的字段。

## 后果

- 正面：录制、重录、局部重跑已经能按 `slide_id`/`scene_id` 定位。
- 负面：PRD §5.1 的场景状态（entry/exit/reset）目前只在模板与渲染器行为中隐含，
  不能机器验证"场景可独立复位"。这是已知 P1 缺口。
- 监测点：P0-B3 单元队列落地时，若仍无 Scene 聚合，则本 ADR 升级为 Blocked。

## 证据

- `models.py::SceneContract`、`LearningUnit`、`PublicSlide`、`ScriptSection`。
- `tests/test_contracts.py`、`tests/test_course_plan.py`、`tests/test_production_animation.py`。
- `docs/QUALITY.md` Q-02：单元队列未实现。

## 回滚

若选择"一个 Scene 聚合替代现有模型"，必须保留 `PublicContent` 的公开性边界，
并提供迁移脚本与旧产物只读兼容；否则维持增量方案。
