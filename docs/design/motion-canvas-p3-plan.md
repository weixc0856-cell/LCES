# Motion Canvas P3 计划：生产级验证

日期：2026-10-23
基线：`main` @ `8498178`（P2.4 A–D 全部合并；P2 冻结为已验收基线）
范围：验证现有管线在接近真实课程生产的条件下是否稳定。不新增渲染能力，
不引入 Remotion，不做 Web 界面与 Windows 原生渲染。

## 1. 要回答的三个问题

1. 真实课程素材能否持续、稳定地完成渲染？
2. 复杂度与运行时间增加时，内存、磁盘与进程行为是否可控？
3. 失败、重试与重复构建是否仍遵守 P2 建立的发布与证据契约？

## 2. 非目标

- Remotion / 第二套管线：没有证据表明 Motion Canvas 的能力边界已成瓶颈；
- Web 界面：先把后端构建、故障恢复与资源行为证明清楚；
- Windows 原生渲染：当前明确 Linux-only，按实际需求再评估；
- 新增场景模板或内容模型。

## 3. 测试规模策略

| 阶段 | 规模 | 目的 |
|---|---|---|
| Smoke | 每个模板一个小样例 | 快速发现基本回归 |
| Representative | 每个模板覆盖典型与边界素材 | 验证课程内容适用性 |
| Stress | 长时长、连续构建 | 测量性能与资源峰值 |
| Recovery | 故障注入、取消、重跑 | 验证状态与发布安全 |

所有测试必须区分：正常成功、预期失败、测试基础设施故障。基础设施故障不得
被记成产品 PASS 或 FAIL。

## 4. P3-A：真实素材回归

### 4.1 素材集（本批已建立）

`tests/fixtures/motion/` 下 7 份完整场景契约，`manifest.json` 记录模板、用途、
标签、画布、帧率、时长、预期帧数与 sha256：

| 素材 | 模板 | 覆盖点 | 画布 | 时长 |
|---|---|---|---|---|
| `title-zh-long` | title | 中文长标题/副标题 | 1920×1080 | 2 s |
| `title-en-short` | title | 英文 smoke | 640×360 | 1 s |
| `title-boundary-max` | title | 标题 200 字符边界 | 640×360 | 1 s |
| `flow-zh-6nodes` | flow | 6 节点（上限）、长标签、中文 | 1920×1080 | 2 s |
| `flow-en-tb` | flow | 英文、`tb` 方向 | 1920×1080 | 1 s |
| `compare-zh-long` | compare | 6 条目（上限）、长条目、中文 | 1920×1080 | 2 s |
| `compare-en` | compare | 英文、1080p | 1920×1080 | 1 s |

素材是“输入”而非“期望截图”。哈希冻结输入，任何修改都必须同时更新 manifest
并接受 diff 审查。

### 4.2 每份素材必须核对的项

- 实际帧数等于 `duration_ms × fps ÷ 1000`；
- 分辨率与帧率与契约一致；
- 视频可通过 `verify_video_against_manifest` 解码核对；
- `visual_qa.json` 为 `pass`，并记录采样帧指标；
- 失败时报告素材 id、阶段（render / encode / qa）与退出码，而不是只报“渲染失败”。

### 4.3 人工关键帧（P3-A 之后）

每份代表性素材至少抽看首帧、中段帧、末帧；记录审阅人、日期、帧索引与结论。
自动指标通过不替代这一步。

### 4.4 本批第一步（已完成）

- 建立 7 份素材与 manifest；
- `tests/test_motion_materials.py` 校验哈希、契约、预期帧数与模板覆盖；
- **不修改渲染器**。渲染执行测试在下一步加入。

## 5. P3-B：长时间渲染与资源观测

- 时长阶梯：1 s、10 s、60 s（按硬件与课程需求再扩展）；
- 记录：总耗时、渲染耗时、编码耗时、峰值 RSS、磁盘峰值、临时目录大小、
  子进程数量、帧数；
- 故障注入：超时、取消、磁盘空间不足（受控目录/配额模拟）；
- 先建立基线数据，再由数据决定是否需要硬配额；不预先写性能目标。

## 6. P3-C：重复构建与故障恢复

- 相同输入连续构建 3 次：视频哈希、FrameManifest、编码记录、环境信息；
- 区分字节级一致、视觉一致、仅元数据一致；
- 中断后重跑、已有产物、失败重试、`.build-in-progress` 标记恢复；
- 检查临时文件泄漏、旧产物误用、错误的成功记录。

## 7. 验收门禁（草案）

| ID | 验收项 | 状态 |
|---|---|---|
| P3-GATE-01 | 素材集冻结且契约有效 | PASS（manifest 哈希 + 契约 + `data_problems`；所有平台运行） |
| P3-GATE-02 | 每个模板都有真实渲染回归 | PASS（run `39928254503`：JUnit 8/0/0，七份素材全部通过） |
| P3-GATE-03 | 失败可定位 | NOT_RUN（错误信息包含素材 id 与阶段；尚无真实的失败注入用例） |
| P3-GATE-04 | 资源基线可复现 | 记录环境、时长阶梯与峰值；结论限定环境 |
| P3-GATE-05 | 故障行为可审计 | 超时/取消/磁盘不足不留半成品、不误报成功 |
| P3-GATE-06 | 重复构建契约明确 | 字节/视觉/元数据三级结论分开记录 |
| P3-GATE-07 | 全量回归 | P1/P2 测试与五个 CI job 保持绿 |

## 8. CI 策略

- PR：smoke + 素材契约校验（低成本）；
- 手动触发：representative 渲染（每模板真实素材）；
- 手动或独立 job：stress 与 recovery（高成本，不进每个 PR）。

## 9. P3-A 第二步：渲染回归（本机；实测 job 待触发）

- `tests/test_motion_canvas_materials.py`：
  - 参数化地对每份素材调用适配器的 `validate_input`（所有平台、低成本）；
  - `LCES_MC_MATERIALS=1` 时在 Linux 真实渲染全部素材，核对帧数、分辨率、
    帧率、视频解码、`visual_qa` 状态，并写出逐素材报告（耗时、字节数、视觉指标）
    到 `LCES_MATERIALS_OUT`；
  - 失败信息包含素材 id 与阶段，避免只报“渲染失败”。
- CI：`workflow_dispatch` 新增 `materials` 输入；p1 job 在该输入为真时运行
  素材渲染，报告进入 `motion-canvas-p1-evidence`。
- `scripts/ci-local.sh render` 支持 `LCES_MC_MATERIALS=1`。

**本机验证**：素材契约校验 7/7 通过；真实渲染仅能在 Linux + 固定工具链运行。

**materials 实测（workflow_dispatch run `39928254503`，commit `bbca37b`）**：
`motion-canvas-p1` 的 materials JUnit **8/0/0**（62.5 s），七份素材全部渲染成功：

| 素材 | 帧数 | 画布 | 耗时 | 前景 / 边缘（采样） |
|---|---|---|---|---|
| title-zh-long | 60 | 1920×1080 | 10.2 s | 7.3–7.6% / 7.1–7.6% |
| title-en-short | 30 | 640×360 | 6.8 s | 10.6% / 13.6% |
| title-boundary-max | 30 | 640×360 | 6.8 s | 11.1% / 14.5% |
| flow-zh-6nodes | 60 | 1920×1080 | 10.2 s | 6.1–6.2% / 2.3–2.4% |
| flow-en-tb | 30 | 1920×1080 | 7.7 s | 6.6% / 1.1% |
| compare-zh-long | 60 | 1920×1080 | 10.3 s | 4.5–5.1% / 3.7–4.2% |
| compare-en | 30 | 1920×1080 | 8.6 s | 2.2% / 2.4% |

帧数、分辨率、帧率、解码与 `visual_qa` 全部通过；报告在
`motion-evidence/materials.json`（artifact `motion-canvas-p1-evidence`），
已下载到 `var/ci-materials/` 复核。

## 10. P3-B 阶段 A/B 实施记录（本机；实测 job 待触发）

**实现**

- `src/content_studio/resource_probe.py`：后台线程按固定间隔采样进程树 RSS、
  子进程数与构建目录大小，记录采样方法、间隔与次数；**采集失败记 `None` 并写入
  `unavailable`，不当作 0**。
- `tests/test_motion_canvas_stress.py`：`LCES_MC_STRESS=1` 时渲染
  1 s / 10 s / 60 s（1920×1080，30 fps）三档；10 s 与 60 s 重复两次。
  记录总耗时、渲染耗时（driver 报告）、编码耗时（包装 `encode_frames`）、
  Gate 4 校验耗时、峰值 RSS、峰值子进程数、峰值目录大小、帧目录/视频大小、
  运行前后可用空间、帧数/分辨率/帧率/解码/哈希，以及环境与素材契约哈希。
- CI：`workflow_dispatch` 新增 `stress` 输入，p1 job 在该输入为真时运行，
  报告写入 `motion-evidence/stress.json`；`ci-local.sh render` 支持
  `LCES_MC_STRESS=1`。

**本机验证**：`uv run pytest` → 436 passed, 53 skipped；ruff / format / mypy 全绿。
真实三档仅在 Linux + 固定工具链执行。

**未执行**：stress 实测 job；故障注入（阶段 C）尚未开始。P3-GATE-04/05 保持
`NOT_RUN`。
