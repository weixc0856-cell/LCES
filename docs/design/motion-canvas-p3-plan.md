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
| P3-GATE-03 | 失败可定位 | PASS（faults JUnit 断言 `render_timeout` / `cancelled` / `encode_failed` 终态；素材用例失败时带素材 id 与阶段） |
| P3-GATE-04 | 资源基线可复现 | PASS（run `39931887360`：三档两轮，环境与峰值留档，差异 <2%） |
| P3-GATE-05 | 故障行为可审计 | PASS（run `39932938615`：超时/取消/重试通过；磁盘映射由合成用例覆盖；无 staging 残留） |
| P3-GATE-06 | 重复构建契约明确 | PASS（10 s/60 s 两轮视频哈希相同；结论限定环境；视觉指标由 P2.4-A/B 记录） |
| P3-GATE-07 | 全量回归 | PASS（materials/stress/faults 三个手动 job 与常规五 job 均绿） |

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

**stress 实测（run `39931887360`，commit `6c02777`）**：2 核/4 vCPU GitHub runner，
Node 24.22.1、Motion Canvas 3.17.2、Playwright 1.64.0、FFmpeg 6.1.1：

| 档位 | 帧数 | 总耗时 | 渲染 | 编码 | Gate 4 | 峰值 RSS | 峰值磁盘 | 视频 |
|---|---|---|---|---|---|---|---|---|
| 1 s | 30 | 7.8 s | 1.2 s | 0.6 s | 0.2 s | 1.40 GB | 2 MB | ~40 KB |
| 10 s (r0) | 300 | 17.4 s | 6.2 s | 3.2 s | 0.9 s | 1.44 GB | 22 MB | ~100 KB |
| 10 s (r1) | 300 | 17.3 s | 5.9 s | 3.3 s | 0.9 s | 1.43 GB | 22 MB | ~100 KB |
| 60 s (r0) | 1800 | 66.5 s | 32.2 s | 18.1 s | 4.3 s | 1.53 GB | 136 MB | ~200 KB |
| 60 s (r1) | 1800 | 66.5 s | 32.3 s | 18.0 s | 4.4 s | 1.51 GB | 136 MB | ~200 KB |

观察（仅限该环境）：

- 总耗时近似线性（每帧约 0.036 s 总成本，其中渲染约 0.018 s），两轮差异 <2%；
- 峰值 RSS 稳定在 1.4–1.5 GB，60 s 档未见持续增长；
- 帧目录约每帧 75 KB（1080p PNG），60 s 档峰值 136 MB；最终视频很小，因为画面压缩率高；
- 子进程峰值 10 个；所有指标通道均可用（`unavailable=[]`）；
- 1 s 档的磁盘峰值受 0.5 s 采样间隔限制，可能低估瞬时峰值；可用空间差值是更可靠的信号。

结论：当前不需要硬配额；若扩展到 5 分钟档，先按 136 MB/60 s 估算磁盘并复核
RSS 曲线。P3-GATE-04 的证据已产生，但仍按计划在完整报告审阅后收口。

## 11. P3-C 实施记录（本机；实测 job 待触发）

**实现**

- 编码可取消：`encode_frames(..., cancel=threading.Event)` 使用 `Popen` 轮询，
  取消时终止整个 FFmpeg 进程组并抛 `RenderCancelled`；超时同样终止并报
  `encode_failed`。适配器把 `self._cancel` 传入编码阶段，取消不再等到编码完成。
- 磁盘写入失败映射：staging 目录创建、编码与最终 `os.replace` 的 `OSError`
  统一映射为 `encode_failed`；失败路径通过 `finally` 删除暂存视频与
  `.staging-*` 目录，发布视频保持不变。
- `tests/test_motion_canvas_faults_p3.py`（`LCES_MC_FAULTS=1`）：
  渲染超时（1.5 s）、渲染中取消（2 s）、编码中取消、超时后重试成功、
  POSIX 只读 media 目录导致的真实写入失败；每条都断言终态、旧视频哈希不变、
  无 `.staging-*` 残留。
- 单位测试补充：`encode_frames` 的非零退出/超时/取消/缺产物，以及
  “磁盘满” `OSError` 映射为 `encode_failed` 且保留旧视频。
- CI 新增 `faults` 输入；`ci-local.sh render` 支持 `LCES_MC_FAULTS=1`。

**本机验证**：`uv run pytest` → **438 passed, 58 skipped**；ruff / format / mypy 全绿。
真实故障用例仅在 Linux 执行。

**faults 实测（run `39932938615`，commit `16593ec`）**：五个 job 全绿；
faults JUnit **5 tests / 0 failures / 1 skipped**（25.2 s）：

- 通过：渲染超时、渲染中取消、编码中取消、超时后重试；
- 跳过：只读目录用例在容器内以 root 运行（root 绕过权限位），
  磁盘写入失败映射由 `test` job 的合成 `OSError(ENOSPC)` 用例覆盖；
- CI 与离线 job 同时通过，说明编码取消没有破坏真实渲染路径。

**重复构建观察（stress run `39931887360` 的报告）**：10 s 与 60 s 两轮的
视频 SHA-256 完全相同（1 s 档只有一轮）。这是同一环境下的字节级一致，
不构成跨环境承诺；GATE-06 的证据按此记录。
