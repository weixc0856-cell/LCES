# 本地模型运行配置（课程开发）

本文件记录 LCES 课程开发时使用的本地模型、启动方式与对应的 LCES 配置。
模型 ID、上下文和档位都属于**可核验的运行参数**，不是建议值：换模型或换档位
必须同时更新本文件、`.env` 和启动器选择。

本机路径一律用占位符表示，实际值由操作者在本地设置，不写入仓库：

- `<LLAMA_HOME>`：llama.cpp 构建目录（含 `llama-server` / `llama-server.exe`）；
- `<MODELS_DIR>`：GGUF 模型目录；
- `<LAUNCHER>`：可选的交互式启动脚本。

## 当前配置（2026-10-23 起）

| 项目 | 值 |
|---|---|
| 启动器 | `<LAUNCHER>`（交互式菜单，可选） |
| 模型文件 | `<MODELS_DIR>/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf` |
| 模型别名（`/v1/models`） | `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M`，另含 `default` |
| 后端 | SYCL（菜单 `[2]`，直接回车即默认） |
| 档位 | `[4] CPU-MoE 48 层 @ 32K` |
| 有效上下文 | 32768 tokens，`--parallel 1` |
| 服务地址 | `http://127.0.0.1:8080/v1` |
| 认证 | llama-server 以 `--api-key` 启动，必须设置 `LCES_LOCAL_API_KEY` |

启动脚本是交互式的：先选后端，再从 `<MODELS_DIR>/*.gguf` 列表里选模型，
最后为 Qwen3-30B-A3B 系列选择档位。课程开发固定走 **SYCL → Coder 模型 → 档位 [4]**。

## 启动步骤

1. 运行本机的 llama-server 启动脚本（或使用下文的按需启动命令）。
2. 后端提示 `请选择 [1-2]，直接回车使用 SYCL`：直接回车（或输入 `2`）。
3. 在模型列表中找到 `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf`，输入对应编号。
4. 档位提示 `选择档位 [1-4]`：输入 `4`（CPU-MoE 48 层 @ 32K）。
5. 等控制台打印服务地址与配置摘要后，另开终端执行：

```powershell
uv run lces models          # 只探测 /health 与 /v1/models，不产生生成调用
uv run lces models --test   # 发送一次最小生成请求，验证结构化输出链路
```

`lces models` 会额外打印 `模型固定: ...（已加载）` 或红色的“模型不匹配”，
后者说明启动器加载的模型与 `.env` 的 `LCES_LOCAL_MODEL` 不一致。确认列表里是
`Qwen3-Coder-30B-A3B-Instruct-Q4_K_M`、`n_ctx` 为 32768，再开始 `lces run`。

## 按需启动（非交互）

课程制作时由 LCES 侧按需拉起模型，不依赖人工点菜单。与档位 `[4]` 等价的命令
（SYCL 构建）：

```powershell
$env:LCES_LOCAL_API_KEY = "<从 .env 读取；服务端未加 --api-key 时可省略>"
<LLAMA_HOME>/llama-server.exe `
  -m "<MODELS_DIR>/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf" `
  --host 127.0.0.1 --port 8080 `
  -dev SYCL0 -ngl 99 `
  -c 32768 --parallel 1 `
  -b 256 -ub 128 `
  -fa on --metrics `
  --alias "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M,default" `
  --jinja `
  --n-cpu-moe 48
```

- 只在需要时启动，用完停止；`.env` 里的 `LCES_LOCAL_MODEL` 与
  `LCES_LOCAL_API_KEY` 必须与启动参数一致。
- 交互式启动脚本仍然可用（人工试探不同档位时更方便），但不是课程
  流程的必要条件；两种方式不能同时占用 8080。
- 启动后必须通过 `uv run lces models` 确认 `模型固定: ...（已加载）`。

## 启动器实际下发的参数

档位 `[4]` 展开后，`llama-server` 的实际参数为：

```
-m <MODELS_DIR>/Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf
--host 127.0.0.1 --port 8080
-dev SYCL0 -ngl 99
-c 32768 --parallel 1
-b 256 -ub 128
-fa on --metrics
--alias "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M,default"
--jinja
--n-cpu-moe 48
```

要点：

- `--n-cpu-moe 48` 把 48 层 MoE 专家放在 CPU，降低 30B-A3B 在 GPU 上的显存压力；
  这是档位 2/3/4 的共有参数，档位 1 不设置它（可能 OOM）。
- `-c 32768` 是档位 `[4]` 的上下文；档位 2 为 8192，档位 3 为 16384。
- `-b 256 -ub 128` 与 `--jinja` 是 Qwen3-30B-A3B 专用配置；Jinja 使用 GGUF 内置模板，
  不再强制 `chatml`。
- 只监听回环地址；端口 8080 不对外暴露。

## LCES 侧配置

`.env`（永不提交）：

```dotenv
LCES_PROVIDER=local
LCES_LOCAL_BASE_URL=http://127.0.0.1:8080/v1
# 与启动器加载的模型一致；加载了别的模型时宁可报错，也不要静默用错模型。
LCES_LOCAL_MODEL=Qwen3-Coder-30B-A3B-Instruct-Q4_K_M
# 由启动器 --api-key 决定；从启动终端或进程参数获取，不写入仓库。
LCES_LOCAL_API_KEY=
# 32K 上下文：给提示词留约 20000 字符，其余留给输出与模板开销。
LCES_LOCAL_PROMPT_CHAR_BUDGET=20000
```

- `LCES_LOCAL_MODEL` 为空时，适配器取 `/v1/models` 的第一个 ID。
  **llama-server 会忽略请求中的 `model` 字段**，照常使用已加载的模型；因此固定后
  适配器在每次生成前比对 `/v1/models`，不匹配即以 `ProviderError` 失败，
  不会静默用错模型。
- `LCES_LOCAL_JSON_MODE=false`：仅当该 llama-server 版本不支持 `response_format`
  时使用；结构化输出仍由提示词 + Pydantic 校验兜底。
- 上下文预算：32K 档位下 `LCES_LOCAL_PROMPT_CHAR_BUDGET` 建议 16000–20000。
  超出上下文时适配器会报 provider 错误，不会悄悄截断资料。
- 路由文件（`config/routing.yaml`）可以把 `research` 指向云端模型、`generate`
  留在本地；`ingest/build/validate` 永远不调用模型。

## 已知模型清单（同一启动器可切换）

| 文件 | 用途 |
|---|---|
| `Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf` | **课程开发现行模型**（本文件） |
| `Qwen3-30B-A3B-Instruct-2507-Q4_K_M.gguf` | 通用写作/说明文对照模型 |
| `Qwen3-8B-Q4_K_M.gguf` | 轻量对照，32K 上下文档位 |
| `DeepSeek-R1-Distill-Llama-8B-Q4_K_M.gguf` | 推理类对照 |
| `Phi-3.5-mini-instruct.q8_0.gguf` | 轻量英文对照 |
| `gemma-4-E2B_q4_0-it.gguf` | 轻量多语言对照 |
| `Qwen3.5-4B_Q4_k_m.gguf` | 早期基线（历史验证记录使用过） |

切换模型时必须同时更新：

1. 启动器里的模型选择；
2. `.env` 的 `LCES_LOCAL_MODEL`；
3. 若上下文档位不同，调整 `LCES_LOCAL_PROMPT_CHAR_BUDGET`；
4. 本文件的“当前配置”表格与日期。

## 验证与排错

| 现象 | 检查 |
|---|---|
| `401` / `Unauthorized` | 启动器带了 `--api-key`；设置 `LCES_LOCAL_API_KEY` |
| `configured model ... is not loaded` | `.env` 的 `LCES_LOCAL_MODEL` 与服务端 `/v1/models` 不一致：换模型或改 .env |
| 上下文不足 / 截断类报错 | 减小 `LCES_LOCAL_PROMPT_CHAR_BUDGET`，或把档位提到 32K |
| 显存不足 | 确认档位不是 `[1]`；`[1]` 不设置 `--n-cpu-moe` |
| 看不到模型 | `lces models` 会同时报告 `/health` 与 `/v1/models` |

`curl http://127.0.0.1:8080/props`（带 `Authorization: Bearer <key>`）可以核对
服务端实际加载的 `model_path` 与 `n_ctx`，这是启动器菜单之外的独立证据。
