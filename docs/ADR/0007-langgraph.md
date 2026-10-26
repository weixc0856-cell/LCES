# ADR 0007: 暂不强制引入 LangGraph

对应 SAD-001 §12 ADR-005。状态：Accepted（2026-10-24 复核）。

## 背景

PRD §6.4 把 LangGraph 列为目标编排层，SAD §8.2 改为"先比较现有控制器"。
现有控制器是 `orchestrator.py` + SQLite `stage_runs`：阶段串行、`--from-stage`
局部重跑、provider 失败一次 fallback、每阶段记录 provider/model/usage/错误。
尚无跨进程恢复、人工暂停节点或复杂条件分支的持久化需求。

## 备选方案

1. 立即引入 LangGraph：需要新的状态存储、节点幂等策略与第二套阶段状态机，
   且必须证明它不绕过 `validate`/Gate 4。
2. 保持现有控制器，记录缺口（当前）。
3. 自研 DAG 引擎：与方案 1 同样的成本，没有生态收益。

## 决定

- 不引入 LangGraph。继续以 CLI + `orchestrator` 为唯一阶段状态机。
- 允许的演进：在不改变业务校验的前提下，补充运行记录（run_id、输入哈希、
  错误分类、重试次数、未核算成本）与显式人工暂停点。
- 引入条件：真实基线出现"跨进程恢复不可靠、条件分支需要持久化、现有记录不足以
  定位失败"的证据，并且 LangGraph 原型在相同输入上通过 `FLOW-RECOVERY-*` /
  `FLOW-IDEMPOTENCY-*` 对照测试。届时另立 ADR。

## 后果

- 正面：只有一套状态机；CLI 与业务模块保持可独立测试。
- 负面：长流程中断后仍以阶段为单位重跑；没有 graph 级别的可视化。
- 监测点：若一个阶段内出现需要多次人工介入的分支，重新评估。

## 证据

`orchestrator.py`、`storage.py`（`stage_runs`/`events`）、`lces run --from-stage`；
`tests/test_pipeline.py`、`tests/test_storage.py`。

## 回滚

不适用（未引入）。若未来引入，保留现有 CLI 路径作为对照实现。
