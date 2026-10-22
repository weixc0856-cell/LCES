# Motion Canvas Windows 本地验证清单

状态：**P1 范围外（方案 B：仅 Linux，2026-10-22）**；模板保留，供未来
Windows 原生准入使用。
用途：P1-GATE-02（未采用）。本地 Linux 开发使用 **WSL2（Ubuntu 24.04）**，
不属于“Windows 原生”，也不由本清单覆盖。

> Docker Desktop / WSL2 在 Windows 上运行的是 Linux 用户态，不能作为 Windows
> 原生验证。若将来要声明 Windows 支持，必须在 Windows 原生进程中重新执行
> 本清单，不能引用 WSL 或容器结果。

部分证据（2026-10-22，**有网环境**）：

- `node --test contract.test.mjs`：**10/10 通过**（约 61 s）
- `node driver.mjs`：**300 帧 / 5.45 s**，完成信号正常

以上只证明契约与驱动在 Windows 主机可用；断网隔离、负控制、完整清单仍未执行。

## WSL2 本地运行时（P1 Linux 范围）

- 已安装 Ubuntu 24.04.4 LTS（WSL2），用于本地 Linux 开发。
- 现有 Node `v22.22.2` / npm `10.9.7`；**P1 要求精确 Node 24.22.1**，
  版本不符时入口应报 `environment_unavailable`。
- Node、Chromium、FFmpeg 与依赖由用户维护；LCES **不自动安装**这些组件。
- WSL 是 Linux 用户态，不是 Windows 原生；不能用于声明 Windows 支持。
- P0 的离线/负控制证据仍以 Linux CI（run `39750119050`）为准，不由 WSL 替代。

## 0. 执行记录

| 项 | 值 |
|---|---|
| 执行人 | 待填 |
| 日期 | 待填 |
| Windows 版本 / 架构 | 待填（例如 11 Pro 10.0.26300 x64） |
| 仓库基线 commit | 待填 |
| 结论 | 待填（GO / CONDITIONAL_GO / NO_GO） |

## 1. 环境与版本

- [ ] 记录 Windows 版本与架构。
- [ ] 记录精确 Node 版本（应为 24.22.1）与 npm 版本。
- [ ] 记录 Motion Canvas core/2d/ui/vite-plugin 版本（应为 3.17.2）。
- [ ] 记录 Playwright Chromium 版本与可执行文件路径/来源。
- [ ] 记录 FFmpeg/ffprobe 版本。
- [ ] 校验 `spike/motion-canvas/package-lock.json` 的 sha256 与仓库一致。
- [ ] 校验 `driver.mjs`、`contract.mjs`、`contract.test.mjs` 的 sha256。
- [ ] 记录依赖安装方式（npm ci）、npm 缓存位置与是否使用 `allowScripts`。
- [ ] 记录任何由安全策略导致的安装/网络阻塞；阻塞即记录，不绕过。

## 2. 功能验证

- [ ] 运行 1080p / 30 fps / 10 s 最小场景，帧数恰好 **300**。
- [ ] 核对 `shared.range` 换算（帧 299 → 秒）与帧序号 000000–000299。
- [ ] 抽查首/中/尾帧尺寸为 1920×1080。
- [ ] 计算若干帧的 SHA-256 并记录。
- [ ] 全帧解码通过（`ffmpeg -framerate 30 -i %06d.png -f null -`）。
- [ ] 渲染完成状态可判定（Abort 消失、Render 回来、帧数稳定）。
- [ ] 取消：中途 Abort，部分帧保留，状态 `cancelled`。
- [ ] 超时：注入超时并停止，状态 `timed_out`，保留证据。
- [ ] 损坏输出：截断一帧后，结构检查与 FFmpeg 解码均失败。
- [ ] 辅助文件（截图、report.json）不计入帧序列。

## 3. 安全与隔离

- [ ] 在实际执行渲染的 Windows 进程中验证断网渲染
      （防火墙出站规则或等价的可证明隔离）。
- [ ] 断网负控制：浏览器 `fetch` 与 `npm install` 均失败，保存退出码。
- [ ] 保存渲染期间的请求审计（URL、失败数），不得只凭应用日志。
- [ ] 取消/超时/失败后，发布目录无新产物、不覆盖旧有效资产。
- [ ] 临时目录与诊断文件被明确标记为不可发布。

## 4. 证据与判定

- [ ] 保存命令、退出码、日志、FrameManifest 与环境版本。
- [ ] 保存成功场景与至少三个失败场景的证据 artifact。
- [ ] 记录与 Linux CI（run `39742834259`）的差异（字体、布局、性能）。
- [ ] 给出平台适用范围：Windows 原生 / Windows 主机 + Linux 容器 / 不支持。
- [ ] 给出最终判定（GO / CONDITIONAL_GO / NO_GO）及日期。

## 5. 建议执行命令（Windows 原生）

```powershell
# 使用项目内精确 Node（或确认系统 Node 为 24.22.1）
$env:Path = "D:\Project\LECS\var\spike\node-v24.22.1\node-v24.22.1-win-x64;$env:Path"
Set-Location D:\Project\LECS\spike\motion-canvas
npm ci --no-audit --no-fund
npx playwright install chromium
node --version; npm --version

# 正常渲染（300 帧）
node driver.mjs
# 取消 / 超时
$env:MODE="cancel"; node driver.mjs
$env:MODE="timeout"; node driver.mjs

# 契约测试（真实编辑器）
node --test --test-reporter=tap contract.test.mjs
```

断网验证需要管理员权限配置 Windows 防火墙出站规则；若当前策略不允许，
记录为阻塞并保留命令与错误，不用 Docker 的 Linux 结果替代 Windows 原生结论。

## 6. 准入规则（与设计文档一致）

**已选择方案 B（2026-10-22）：P1 仅 Linux。** 本清单不参与 P1 准入。

- 方案 A：Windows + Linux 都支持 —— 未采用。
- **方案 B：仅 Linux** —— 已在 P1 入口以 `assertSupportedPlatform` 显式拒绝
  Windows；文档、CI、发布范围限定 Linux（含 WSL2）。
- 若将来要改为方案 A，必须重新执行本清单并重新判定；旧结果不继承。
