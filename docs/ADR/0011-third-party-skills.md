# ADR 0011: 第三方 Skills 的引入审查

对应 SAD-001 §12 ADR-009。状态：Accepted。

## 背景

PRD §6.5 要求建立 LECS 自有 Skills 规范；§6.6 与 §16 列出若干科研 Skills 仓库
（Supervisor-Skills、Light Skills、academic-humanizer）作为**方法参考**。
这些仓库的许可证、数据流向与实际收益都未核实，且部分内容可能不适合商业交付。
仓库现有 `skills/` 下的五个 studio 定义是 LECS 自有的流程说明，不是第三方代码。

## 备选方案

1. 直接引入第三方 Skills 作为系统主体：许可证与执行行为不可控，且会把
   "一套提示词"当成生产系统（PRD §6.5 明确禁止）。
2. 完全不看外部项目：会重复已被验证的方法。
3. 只读参考 + 自研实现 + 记录（当前）。

## 决定

- 不直接复制第三方 Skills 的代码或文本到产品中。
- 引入任何第三方组件前必须在 `LICENSE-THIRD-PARTY.md` 与 ADR 中记录：
  官方仓库、版本/commit、许可证、实际采用的规则、兼容与安全风险、与现有模块的重叠、
  测试结果、引入成本与回滚方法。
- Skills 的职责边界：Handbook 解释方法，Skill 描述任务，程序做确定性校验，
  人工承担判断与批准。Skill 不能替代 Gate。
- 非商业许可（NC）内容不得进入可商业化的交付物。

## 后果

- 正面：供应链审计（`lces supply-chain-check`）覆盖所有已引入的固定版本；
  没有"来源不明"的提示词或代码。
- 负面：需要自行实现方法，短期效率低于直接复制。
- 监测点：每次引入外部资产都重新评估；许可证变化时重新审查。

## 证据

`LICENSE-THIRD-PARTY.md`、`config/supply-chain.json`、`tests/test_supply_chain.py`、
已归档的实现日志中的 supply-chain 行。

## 回滚

移除对应组件与锁文件条目，重新运行 supply-chain 审计与受影响测试。
