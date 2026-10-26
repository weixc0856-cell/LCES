# ADR 0009: 自动视觉 QA、基线与人工验收相互独立

对应 SAD-001 §12 ADR-007。状态：Accepted。

## 背景

"渲染成功"不等于"画面可读"，"与基线一致"不等于"画面正确"。TDD-001 §8.4 要求
视觉回归区分 `missing/matched/drifted/failed`；§9.4 要求人工验收记录审核者、
时间、工具链与被检查的帧。

## 备选方案

1. 只做像素比较：环境差异会制造噪声，且无法发现"基线本身是错的"。
2. 只做人工验收：不可扩展，也无法在 CI 中拦截空白帧。
3. 三层独立（当前）：自动 QA 拦技术缺陷，基线记录漂移，人工记录教学判断。

## 决定

- `visual_qa.py`：抽样帧的前景/边缘指标，空白构建在编码前失败。
- `visual_baseline.py`：每模板/尺寸/帧率的采样指标与帧哈希；缺失记为 `missing`，
  漂移只 `warn`，永不当作通过。
- `visual_acceptance.py`：唯一写入方 `lces accept-visual`；Gate 4 在有人工验收
  且工具链匹配时才放行动画媒体。
- 三层记录互不替代；任何一层缺失都必须是显式状态。

## 后果

- 正面：CI 能拦住空白帧；人工只需判断"是否值得发布"。
- 负面：模板或字体变化会让基线全部漂移，需要人工逐张确认（P7 已出现 10 张变化）。
- 监测点：若漂移频率高到无法人工处理，需要引入像素差分工具，但仍不能替代人工结论。

## 证据

`tests/test_visual_qa.py`、`tests/test_visual_baseline.py`、`tests/test_visual_acceptance.py`；
`docs/design/motion-canvas-p2.4-plan.md` 与 CI run `39925848804`。

## 回滚

可以停用基线比较（记录为 `missing`），但不能把停用描述为通过。
