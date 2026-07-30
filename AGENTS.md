# AGENTS.md

本文件是 AI Coding 智能体的项目核心记忆，遵循 [agents.md](https://agents.md) 公共规范。所有智能体改动代码前必读。

## 项目概览

VELA —— 车联网 OTA 日志证据化与智能诊断 POC。Python ≥ 3.11，`src/` 布局，**本地优先**：DuckDB 单文件列存 + Parquet，无 Docker、无外部服务依赖。

- 架构总览（七层管道 + 图编排）：`.planning/codebase/ARCHITECTURE.md`
- 领域文档：`README.md`、`docs/`（SCHEMA、TOOLS、生产迁移）

## 环境与安装

```bash
make install-dev          # 建 .venv + 安装依赖 + 可编辑安装（含 pytest/fastapi 等可选项）
cp .env.example .env      # 环境变量全部可选，未设置时走 config/*.yaml 默认值
```

所有 CLI / 测试命令均需 `PYTHONPATH=src VELA_CONFIG_DIR=config`（Makefile 已内置）。

## 常用命令

| 命令 | 用途 |
|------|------|
| `make doctor` | 环境自检 |
| `make demo` | 仿真 → 建库 → 诊断 → 证据验证 全链路冒烟 |
| `make test` / `make test-fast` | 全量 177 个测试 / 快速子集 |
| `make sim` | 生成 10 场景仿真数据集到 `data/dataset/` |
| `make build ARCHIVE=x.zip WS=workspace/xxx` | 建立列式取证库（DuckDB Gold） |
| `make eval` | 跑 10 场景黄金评测 |
| `make serve DB=.../analysis.duckdb` | 本地 HTTP 服务（FastAPI，缺失时降级 stdlib） |
| `make lint` | 仅 AST 语法检查（项目无 ruff/mypy 门禁） |

pytest 标记：`slow`（端到端）、`determinism`（确定性回归，要求 `PYTHONHASHSEED=0`）、`realllm`（需要真实 LLM 端点的付费用例，默认被 addopts 排除，显式 `-m realllm` 才跑）。

## 架构铁律（改动前必读）

1. **查询唯一收口**：Gold 库只经 `LogQueryAPI.call()`（`src/vela/query/api.py`）访问，禁止绕过门面直连 DuckDB。
2. **配置驱动**：阈值/预算/解析规则一律放 `config/*.yaml`，业务代码不硬编码。注意 `config.py::load_yaml` 有 `lru_cache`，改配置须重启进程生效。
3. **模型可插拔**：供应商只经 `gateway/base.py::Provider` 抽象接入，切换只改环境变量 `VELA_LLM_PROVIDER`；禁止在业务代码写 provider 专属逻辑。
4. **程序化校验优先于模型自述**：引用校验（`agent/citations.py`）、证据包 L0/L1/L2 验证等确定性路径独立于 LLM 输出，不得用模型自述替代。
5. **图节点即方法**：七节点逻辑全部是 `AgentGraph.node_*` 方法（`agent/graph.py`）；`agent/nodes/` 是空目录，新增节点不要在其中建文件。

## 代码约定

- 单线程/单进程同步模型，不引入并发框架；DuckDB 以 `read_only=True` 连接。
- 三方库优先：能用成熟三方开源库解决的一律不手写实现（2026-07-31 Phase 1 D-01 项目级永久变更）；新增依赖只需满足纯本地可安装、不引入必须联网才能跑通主链路的服务。当前运行期依赖：duckdb / pyarrow / PyYAML / pytz / python-dotenv / openai。
- 日志纪律：不使用 `logging` 模块；结构化事件走 `obs/events.py::EventBus`，CLI 输出用 `print()`。
- 错误处理：分层显式 + 优雅降级（模型降级链 / `BudgetExceeded` → `unanswerable` / `ToolResult.notes` 负反馈），不吞异常。
- 解析失败的日志标记状态码（`PARSE_UNPARSED` 等）入库留痕，不丢弃。

## 安全边界

- 禁止提交 `.env` 及任何 API key、接入点 ID。
- 出站数据必须经过 `gateway/redact.py` 脱敏（VIN/GPS/手机号/IMEI 等）。
- 保持本地优先：不引入必须联网或依赖外部服务才能跑通主链路的改动。

## 完成判据

改动完成后：`make test-fast` 通过；涉及建库/查询/推理链路的改动须 `make test` 全量通过；行为变化须同步 `config/*.yaml` 与相关文档。
