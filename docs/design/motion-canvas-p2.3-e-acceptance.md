# Motion Canvas P2.3-E：安全验收

日期：2026-10-23
基线：`feat/motion-canvas-p2.3-d`（P2.3-D 网络边界）
范围：负向测试矩阵收口、证据脱敏与留档、P2.1/P2.2 回归。不新增场景能力，不进入 P2.4。

## 1. 本批交付

1. **N01–N18 矩阵收口**：逐项映射到仓库内的测试与 CI 证据；补齐 N17 缺失的
   画布/时长/场景文件上限负向测试。
2. **证据脱敏**（GATE-08 的前置）：
   - `encode_report.json` 1.2：FFmpeg `command` 改为构建相对路径
     （`<build>/...`，二进制只留 basename），新增 `command_paths`；
   - `lces doctor` 输出把当前用户 home 前缀脱敏为 `~`；
   - 新增 `scripts/audit-evidence.py` + `content_studio.evidence_audit`，
     扫描上传前的证据目录：用户 home 路径、API key/bearer/私钥模式；
   - CI 的 `motion-canvas-p1`、`graphviz` 与离线容器都在上传 artifact 前执行审计。
3. **真实发现并修复**：首次对既有 artifact 运行时，`graphviz-doctor.txt` 含
   `/home/runner/work/LCES/LCES/...`（GATE-08 要求排除的绝对用户路径）。
   `doctor` 现输出 `~/work/...`；新的 graphviz 证据目录会在上传前被审计。

## 2. N01–N18 矩阵

| ID | 用例 | 覆盖位置 |
|---|---|---|
| N01 | `scene_file` 越界/绝对路径 | `test_p23_filesystem_boundaries.py::test_scene_file_must_not_escape_content_scenes`；`test_production_animation.py::test_scene_file_must_stay_under_content_scenes` |
| N02 | 场景文件/目录符号链接 | `test_symlinked_scene_file_is_rejected_without_reading_it`、`test_symlinked_scene_directory_is_rejected`（WSL/Linux 执行） |
| N03 | `video.output_path` 非白名单路径 | `test_production_animation.py::test_wrong_video_output_path_is_rejected` |
| N04 | `render-scene --out` 越界 | `test_render_scene_rejects_out_outside_the_project`、`test_output_directory_must_stay_inside_the_project` |
| N05 | `LCES_BUILD_ID` 含路径/大写 | `test_build_id_cannot_carry_a_path` |
| N06 | `LCES_NODE_BIN` 非法 | `test_node_override_must_be_an_absolute_executable`、`test_render_fails_before_the_build_when_node_is_missing`、`test_subprocess_calls_do_not_use_a_shell` |
| N07 | 驱动 `OUTPUT_DIR` 越界/链接/非专用 | `motion/output-dir.test.mjs`；`test_output_directory_symlink_is_rejected` 等 |
| N08 | 取消/超时残留进程 | `tests/test_motion_canvas_process.py`（进程组）；E2E 取消/超时用例 |
| N09 | HOME/XDG/TMP 隔离 | `test_driver_environment_isolates_home_and_temp`；E2E HOME canary |
| N10 | 帧符号链接/清单篡改 | `test_symlinked_frame_is_rejected_when_building_the_manifest`、`test_verify_rejects_a_frame_replaced_by_a_symlink` |
| N11 | charts/staging 符号链接夹带 | `test_chart_symlink_is_rejected_before_copying`、`test_release_staging_rejects_a_chart_symlink`、`test_gate4_rejects_a_symlink_in_the_release_tree` 等 |
| N12 | 锁文件与已安装依赖不一致 | `test_dependency_problems_detect_a_rewritten_tree`、`test_dependency_mismatch_blocks_before_any_output`；SC-04 |
| N13 | Node 归档校验和不匹配 | `test_supply_chain.py::test_node_checksum_mismatch_fails`、`test_node_archive_without_verification_fails` |
| N14 | 镜像/action 与记录不符 | `test_supply_chain.py` 的镜像 digest、action tag/未记录 action 用例 |
| N15 | 渲染期外部请求被阻断 | `motion/network-policy.test.mjs`；E2E `blocked_count > 0`；离线 job 的 4/4 失败 |
| N16 | 非法 flow/compare 数据 | `test_flow_rejects_invalid_structure`、`test_compare_rejects_invalid_panels`、production 入口用例 |
| N17 | 超大画布/时长/场景文件 | `test_oversized_canvas_is_rejected`、`test_overlong_duration_is_rejected`、`test_oversized_scene_file_is_an_input_failure`（本批新增） |
| N18 | FFmpeg 不可用/版本不足 | 故障矩阵 `test_every_failure_publishes_nothing`（`encode_failed`）、`test_encode_failure_keeps_the_old_video`；`lces doctor` 环境检查 |

退出码与错误码来自 `config/error_codes.json`；`invalid_input` 为 13，
`environment_unavailable` 为 11，`qa_failed` 为 14（详见共享错误表）。

## 3. 证据脱敏的边界

- 只扫描上传目录（`motion-evidence/`、`graphviz-evidence/`、离线 `/evidence`）。
  构建目录里的原始日志仍可能含 runner 路径；它们不作为 artifact 上传。
- 审计跳过二进制文件与符号链接；不会跟随链接去读目录外的内容。
- 识别的是“当前用户 home 前缀”和少量高置信密钥模式，不是通用 DLP；
  其它用户路径或变形密钥可能漏检，不能据此宣称“证据绝对无泄漏”。

## 4. 门禁收口

| ID | 状态 |
|---|---|
| P2.3-GATE-01 执行边界 | PASS（A/B/C/D 批 CI） |
| P2.3-GATE-02 文件系统边界 | PASS（B 批 + Linux pytest） |
| P2.3-GATE-03 供应链 | PASS（C 批 run `39888269698`） |
| P2.3-GATE-04 网络边界 | PASS（D 批 run `39893948581`） |
| P2.3-GATE-05 负向矩阵 | PASS（N01-N18 全部映射到测试；run `39899991262` 五 job 绿） |
| P2.3-GATE-06 P2.1/P2.2 回归 | PASS（D 批 CI）；本批重跑 |
| P2.3-GATE-07 五 job 全绿 | PASS for E（run `39899991262`）；合并后 main 需复跑确认 |
| P2.3-GATE-08 审计与证据留档 | PASS（矩阵 + 脱敏 + 审计脚本；三份 artifact 审计 0 findings） |

## 5. 实施记录（本机 + CI）

**实现**

- `encode_report.json` 1.2：`command` 相对 `<build>` 重写，二进制只留 basename，
  新增 `command_paths`；脱敏基准是项目 `build/` 根，因为 staging 视频位于
  `build/media/` 而不在单次构建目录内。
- `lces doctor` 的解释器、模板、数据库、路由路径均经过 `redact_home`。
- `content_studio.evidence_audit` + `scripts/audit-evidence.py`：扫描证据目录中的
  用户 home 路径与高置信密钥模式；`motion-canvas-p1`、`graphviz` 与离线容器
  在上传前执行。
- N17 补齐：画布超限、时长超限、场景文件超过 1 MB 的负向测试。

**本机验证（Windows 11）**

- `uv run pytest` → **386 passed, 39 skipped**；ruff / format / mypy 全绿；
  Node 三套测试 29 tests（26 pass，3 个符号链接用例跳过）。
- 证据审计对既有 artifact：`graphviz-doctor.txt` 2 条 home-path
  （`/home/runner/...`，修复前），p1 与离线证据 0 条；修复后 `doctor` 输出 `~/...`。
- 本机离线镜像 `sha256:dbc5d643…`：`--network none` 运行 → **13 passed / 0 failed**
  （34.6 s）；负控制 `fetch_exit=1 npm_exit=1`；证据审计 **0 findings**；
  `encode_report.json` 为 1.2，`command_paths=build-relative`。
- 校验：`scripts/ci-local.sh offline` 新增 CRLF 预检（一次真实故障：脚本被写回
  CRLF 后容器内 `set -euo pipefail` 失败）。

**E 批 CI 证据（run `39899991262`，commit `504cd25`，PR #20）**：五个 job 全绿。

- `motion-canvas-p1`：JUnit 19/0/0（62.4 s），Node 契约 TAP 29/29；真实
  `encode_report.json` 为 1.2、`command_paths=build-relative`、无 `/home/`。
- `motion-canvas-offline`：JUnit 13/0/0（34.8 s），镜像
  `sha256:d64ce8ac…046f`，负控制 `fetch_exit=1 npm_exit=1`。
- 三份 `evidence-audit.txt`（p1、graphviz、离线）均为 **0 finding(s)**；
  graphviz `doctor.txt` 已脱敏为 `~/work/LCES/LCES/...`。
- artifact 已下载到 `var/ci-run-e/`（git 忽略）并独立复核。
