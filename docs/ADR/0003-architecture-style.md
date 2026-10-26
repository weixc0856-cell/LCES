# ADR 0003: 模块化单体与分层边界

对应 SAD-001 §12 ADR-001。状态：Accepted（2026-10-24 复核）。

## 背景

LECS 目前是本地优先的单进程工具链：CLI 调用 `orchestrator`/`release` 等业务模块，
业务模块通过 `models.py` 的 Pydantic 契约交换数据，SQLite 只记录任务、阶段运行、
资产与审批。`docs/ARCHITECTURE.md` 的模块表与 SAD-001 §3 的目标分层一一对应。

真正的问题不是"要不要微服务"，而是边界是否会随时间塌陷：模板曾经可以拿到
`SpeakerScript`，渲染器可能直接改写课程数据，发布可能绕过门禁。这些靠类型边界
和测试而不是靠部署拓扑解决。

## 备选方案

1. 微服务 + 远程队列：第一阶段没有并发、多租户或远程执行的真实需求；
   引入后每个边界都要处理序列化、重试和版本漂移。
2. 单文件脚本：无法隔离公开/内部模型，也无法为每个门禁写独立负向测试。
3. 模块化单体（当前）：一个 Python 进程、明确模块职责、契约在 `models.py`。

## 决定

保持模块化单体。依赖方向固定为 `cli → application/orchestration → domain → adapters`；
渲染器不得写课程主数据，审计器不得静默改写被审计内容，`release/` 只由 `release.py` 组装。
新增服务化接口必须有真实运行证据（并发、远程 worker、多人协作）并另立 ADR。

## 后果

- 正面：每个模块可以脱离完整工作流单独测试；安全边界可以用进程内测试证明。
- 负面：长流程仍受单机资源限制；`--from-stage` 之外没有分布式恢复。
- 监测点：当单次完整课程生产超过单机预算，或需要多人同时写入同一课程工作区时，
  重新评估本 ADR。

## 证据

- `docs/ARCHITECTURE.md` 模块表；`src/content_studio/` 模块划分。
- `tests/test_p23_filesystem_boundaries.py`、`tests/test_release.py`、`tests/test_models.py`
  分别证明文件边界、发布边界和契约边界。
- 2026-10-24 P8 基线：712 项测试收集，663 passed / 49 skipped / 0 failed。

## 回滚

按模块拆出独立进程不改动契约；本 ADR 的回滚成本低，风险在于过早拆分。
