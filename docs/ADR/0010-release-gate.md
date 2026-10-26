# ADR 0010: 版本绑定的发布门禁

对应 SAD-001 §12 ADR-008。状态：Accepted（2026-10-24 强化）。

## 背景

发布是唯一不可回滚的错误：把未审的课程当成已验收课程交付，会同时破坏证据链
与产品信誉。现有门禁已覆盖：Gate 1–3 QA、Gate B 课程产品验收、课程内容审计、
结构化证据签署、来源冲突披露、视觉验收、人工审批、白名单与哈希。

缺口是**绑定**：QA 报告过去只记录检查结果，不记录它检查了哪些字节。内容在
`lces validate` 之后被编辑（或重新构建）时，旧报告仍可被 `lces release` 复用；
发布清单也没有记录课程契约版本、代码版本、输入哈希与决定理由（SAD-001 §9.2）。

## 备选方案

1. 依赖操作纪律（"发布前记得重跑"）：PRD §7.4 明确禁止静默复用失效审核。
2. 每次发布无条件重跑全部检查：成本高，且仍不能证明清单与决定绑定。
3. 报告自绑定 + 清单记录血缘（当前）。

## 决定

- `QAReport.content_version` 是 `content/public_content.json`、`reading_edition.json`、
  `outline.json`、`internal/speaker_script.json`、`build/slides/index.html`、
  `build/reading_edition.html` 的聚合 SHA-256。
- `build_release` 在打包前重算该值：报告缺失绑定或与当前字节不一致即拒绝发布。
- `ReleaseManifest` 2.0 记录：`content_version`、`course_version`、`code_version`（Git HEAD）、
  `input_sha256`（来源登记）、`quality_sha256`（Gate B 报告）、`acceptance_sha256`
  （人工验收）、`course_product`、`decision`、`disclosures`、`limitations`（所有 `NOT_RUN` 项）。
- `decision` 只能取 `approved` / `approved_with_disclosures`；存在来源冲突披露**或**
  任一 `NOT_RUN` 检查时必须是后者（`approved` 表示"没有被遗留未证明的项"）。
  `release_decision()` 仍负责在拒绝时区分 `blocked` 与 `needs_human_review`。
- 1.0 清单（2026-10-24 之前构建的发布，如 `release/v1`）保持只读兼容，继续用旧规则验证；
  新构建一律写 2.0。不得把旧清单"升级"成 2.0。

## 后果

- 正面：任何"改了内容但没重验"的发布都会被拒绝；发布包能自证它对应哪次课程、代码与审核。
- 负面：编辑内容后必须重跑 `lces validate`；旧项目首次发布前需要一次重新验证。
- 遗留缺口：`code_version` 在非 Git 工作区为空，此时清单记 `warn` 而不是伪造版本；
  `release/v1` 本身仍是历史非合规发布，不得重新标记为通过。

## 证据

`release.py`（绑定检查与清单构造）、`validation.py::content_version`、
`validation.py::run_release_checks`（`manifest_lineage`）；
`tests/test_release.py`：无绑定报告被拒、内容变更后被拒、清单血缘完整、
血缘缺失被 `release-check` 检出。

## 回滚

若绑定检查阻断合法流程，只能通过重跑 `lces validate` 解决；不得添加跳过开关。
回滚清单 2.0 需要新 ADR，并说明如何保持已发布包的证据可读。
