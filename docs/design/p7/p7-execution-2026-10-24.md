# LECS P7 执行报告：内容重建、渲染升级与审计加固

日期：2026-10-24  
分支：`feat/course-content-audit-release-gate`  
对象：`projects/attention-is-all-you-need`  
最终状态：**P7 工程改造完成；Gate B 仍为 blocked，发布保持 NO-GO。没有创建 v2、没有审批、没有发布。**

> 本报告记录由工程与研究代理完成的改动与验证。所有人工签署、学习者数据、视觉确认与发布授权仍为空。
> 课程契约从 `1.0`（8 节、可滚动页）升级为 `1.1`（14 节、16:9 deck + 阅读版），状态仍为 **draft**。

## 0. 交付物索引

| 交付物 | 位置 |
|---|---|
| 本执行报告 | `01-执行报告.md` |
| 14 项证据复核包 + 索引 | [`02-evidence/index.md`](../p6/evidence-packets/index.md)、`02-evidence/*.json` |
| 来源争议与核心主张核查 | [`03-source-check/source-dispute-review.md`](../p6/source-dispute-review-2026-10-24.md) |
| 14 节课程内容审读 | [`04-course/course-content-review.md`](course-content-review-2026-10-24.md) |
| 学习者试测材料 | 已按 2026-10-24 产品方向移除（不作为正常生产前置条件） |
| 视觉审核表 | [`06-visual/visual-review.md`](../p6/visual-review-2026-10-24.md) |
| 候选内容快照 + 哈希清单 | [`07-audits/snapshot-manifest.json`](content-snapshot/manifest.json) |
| 证据整改逐条记录 | [`03-source-check/evidence-remediation.json`](../evidence-remediation-2026-10-24.json) |
| 三套来源哈希口径 | [`07-audits/hash-lineage.md`](hash-lineage-2026-10-24.md) |
| 计时音频说明 | [`07-audits/timing-audio/timing-audio.md`](../p6/timing-audio-2026-10-24.md) |

## 1. 本轮改动

### 1.1 证据链（对应 P6 的 F-01 / F-02）

- 主张从 23 条增至 **34 条**，证据从 37 条增至 **50 条**，结构化复核记录从 8 条增至 **14 条**。
- 新增覆盖：Table 1 四类层、Table 2 全部对照行与 FLOPs、Table 3 关键消融、Table 4 WSJ F1、
  训练日程、beam search 与 checkpoint 平均、Noam 公式 (3)、Post-LN 残差、点积方差、位置编码相对性质、标签平滑。
- slide-002 现在明确写出 `d_model=512` 与 `d_ff=2048`（F-02），并由 `claim-008/033` 绑定。
- slide-005 删除了“正弦编码不参与梯度更新”的无依据表述，改为“作者的解释 + Table 3(E) 的结果”（F-03）。
- 全部课程文本统一写 `arXiv:1706.03762v7`，Table 2 标题带版本（F-04）。
- 新增证据 038–050 的 `source_excerpt` 均为原文切片并压成单行，不再产生断行乱码；evidence-035 的 chunk 修正为 `source-001:b0044`（Adam 参数起始块）。

### 1.2 内容与渲染

- 课程从 8 节扩展到 **14 节 / 20 分钟**：Post-LN 结构、方差推导、FFN 与权重共享、Table 1–4、来源口径、局限与复盘。
- 公式从 3 个增至 **7 个**，每个公式都有符号/维度解释与 LaTeX 以外的可读排版。
- 新增 **2 幅确定性 SVG**（架构图、注意力数据流）与 **4 个 Canvas 交互实验室**
  （复杂度交叉点、方差饱和、正弦旋转、算力对照）。
- `build/slides/index.html` 重写为 **1920×1080 逐页 deck**：自适应缩放、`←/→/Home/End/T/E` 快捷键、
  演示/连续阅读/本页证据三种视图、打印样式；无 JavaScript 时退化为连续阅读。
- 公式在**构建期**由 `latex_render.py` 转成语义 HTML（`sup/sub`、分式、根号），
  不依赖 CDN、不依赖浏览器数学引擎；不支持的 LaTeX 命令会让构建失败，而不是把反斜杠交给浏览器。
- `reading_edition.html` 重写为深度阅读版：符号与张量形状表、逐节推导、完整表格与原文引用。
  阅读版不再是对幻灯片的缩写。
- **口播稿不进入公开 HTML**：这是项目的公开/内部边界，逐字讲稿抽屉被有意省略；
  证据抽屉只展示公开的 `source_id`。

### 1.3 审计加固（`lces audit-course`）

新增四条硬门禁（任一失败即非 passed）：

1. **全产物数字逆向覆盖**：扫描公开内容、阅读版、构建页面与内部口播稿中的定量数字，
   每个数字必须出现在该节绑定的 claims/evidence 中，或在 `number_whitelist.json` 中带理由登记。
   这条门禁直接针对 P6 的 F-01：`0.98`、`1e-9`、`4000` 这类“原文里有、台账里没有”的数字会被拦下。
2. **裸 LaTeX 泄漏扫描**：构建页面的可见文本不允许出现 `\mathrm`、`\left`、`\frac`、`\sqrt` 等命令。
3. **外部资源依赖扫描**：课件不得引用外网脚本、样式或媒体，保证离线可用。
4. **受保护条件检查**：`course_guards.json` 锁定人工审读过的条件（Post-LN、`n < d`、作者假设、
   开发集口径、41.0/41.8 双披露）；条件被删除或改写即阻断。

新增负向回归测试覆盖：未登记口播数字、裸 LaTeX、外部资源、Pre-LN 篡改、删除 `n < d`、
删除“作者假设”、单边 41.8、AI 复核冒充人工签署。

### 1.4 来源抽取与哈希口径

- 修复 HTML 抽取：每个 `<math>` 子树折叠成一个内联 token（优先 TeX annotation），
  不再把公式拆成一行一个字符。新抽取器有单元测试。
- `source_map.json` 显式拆分三个哈希：
  `raw_archive_sha256`（原始归档字节）、`extracted_txt_sha256`（`source-001.txt` 字节）、
  `normalized_locator_sha256`（引用定位器实际比较的规范化视图）。
- **没有原地重写 `source-001.txt`**：重写会改变全部 chunk 偏移，而 37 条 P6 证据中只有 4 条记录了
  chunk id，其余 33 条无法机械重锚。静默重写会削弱可追溯性；迁移需要单独执行并逐条人工复核，
  已列入未完成项（见 §5）。

### 1.5 核验包

- 打包脚本改为受版本控制的 `scripts/build-review-packet.py`，并内置三项自检：
  Markdown 相对链接必须可解析、命令文件不得含 Unix 式环境变量前缀、逐文件 SHA-256 清单。
- `04-commands.md` 使用原生 PowerShell（`$env:PYTHONIOENCODING`、位置参数 `project_dir`），
  参数与 `lces --help` 一致；冲突项单独给出 `--conflict-ack` 命令。
- 同时产出 `.zip` 与 `.7z`（检测到 7-Zip 时）。

## 2. 验证结果

| 命令 | 结果 |
|---|---|
| `pytest --no-header -q` | 662 项收集，0 failed（network/motion 标记跳过）；新增 27 项 |
| `ruff check src tests scripts` | passed |
| `ruff format --check src tests scripts` | 128 files formatted |
| `lces build` | 生成 14 节 deck 与深度阅读版 |
| `lces audit-course` | **passed**：blocker=0, major=0, advisory=0；14 条复核记录、7 个公式、全部数字覆盖 |
| `lces validate` | Gate 1/2/3 均为 warn（无 fail）：研究签署未完成、视觉基线变化待确认 |
| `lces audit-product` | **blocked**：`timing_matches_script`（口播稿已改写，旧音频作废）+ 2 项人工项 |
| 浏览器 QA | 10 个视口加载、无 JS 错误、无横向溢出、无外部资源 |

课程版本：`66cb122afbb2bf5c…`（内容审计）；内容版本：`0e286692862b25d1…`（Gate B）。

## 3. 对《P6 独立校检报告》的逐条处理

| 校检发现 | 本轮处理 |
|---|---|
| P1 执行报告相对链接失效 | 打包脚本改写并**自动校验**所有 Markdown 链接；失效即打包失败 |
| P1 命令不是 PowerShell | 重写为原生 PowerShell，并加入格式自检 |
| P1 F-01 证据链缺口 | 新增 evidence/claim + `number_coverage` 门禁 |
| P1 人工签署与学习者数据缺失 | 未伪造；14/14 复核仍 pending，试测未执行 |
| P2 计时音频缺失 | 包内继续提供 MP3 试听副本，并注明不是原始计时证据 |
| P2 三套哈希口径不明 | `source_map.json` 三个显式字段 + `hash-lineage` 文档 + 重建规则 |
| P2 幻灯片交互未被验证 | 交付形态明确为 16:9 deck；浏览器 QA 覆盖键盘/视图切换所在的页面 |

## 4. 仍为 NO-GO 的人工项

1. **14 条证据逐一签署**（含 41.0/41.8 冲突裁决）。AI 实质复核不是签名。
2. **课程契约批准**：`1.1` 仍为 draft，需要产品负责人确认 14 节与交付形态。
3. **重新录制并计时**：口播稿已改写，`timing_evidence.json` 与音频不再对应当前脚本。
4. **视觉基线确认**：新 deck 使 10 张截图全部变化，需要人工逐张确认后更新基线。
5. **真实学习者试测**：`05-learner-trial` 仍未执行；TTS 朗读时长不能替代学习者时长。
6. **Gate B / 发布授权**：以上完成后才能 `accept-course`，之后才谈 v2。

## 5. 未完成与明确不做的事

- **来源文本重抽取迁移**：抽取器已修复；为了让现有证据链不被静默改写，本轮没有重建
  `source-001.txt`。迁移需要重锚 37 条证据与 14 条复核记录，属于单独的人工复核任务。
- **Table 3 (C) 行列语义**：数值来自原文切片，但列到变体的映射需要人工逐格确认（审读报告已标注）。
- **逐字讲稿抽屉**：公开 HTML 不包含内部口播稿；这是有意的边界，不是遗漏。
- **TTS 重新生成**：仓库没有本地 TTS 管线；重新计时需在受控环境中完成。
- **发布**：本轮没有创建 v2、没有 approve/release。

## 6. 风险与限制

- 数字覆盖门禁是**登记检查**，不是正确性证明：它只能发现“课程写了台账没有的数字”，
  不能判断数字是否被正确解释。
- 公式审计比较规范化后的 LaTeX，不验证数学语义；语义仍需人工复核。
- 受保护条件是短语锁，只能发现被删除的条件，不能发现被静默弱化的表述。
- 交互实验室是模型示意，不是论文实验数据的复现。
