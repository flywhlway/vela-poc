<!-- refreshed: 2026-07-30 -->
# Architecture

**Analysis Date:** 2026-07-30

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────┐
│  仿真/接入层 (Simulation / Ingestion)          `src/vela/sim/`           │
│  10 场景车队仿真器；生产环境替换为真实压缩包（同一输入接口）             │
└──────────────────────────────────┬────────────────────────────────────-─┘
                                    ▼  原始日志压缩包 (.zip)
┌─────────────────────────────────────────────────────────────────────────┐
│  证据平面 (Evidence Plane)                     `src/vela/evidence/`      │
│  Stage-0~8：安全解包 → 编码探测 → 逐格式解析 → 三级指纹 → 时间归一       │
│  → 模板挖掘 → 列存 → QA                                                  │
│  编排入口：`evidence/pipeline.py::build()`                               │
└──────────────────────────────────┬─────────────────────────────────────-┘
                                    ▼  DuckDB + Parquet 列式取证库（Gold）
┌─────────────────────────────────────────────────────────────────────────┐
│  查询平面 (Query Plane)                        `src/vela/query/`         │
│  12 个只读工具（6 鸟瞰 + 6 下钻），全部经 `LogQueryAPI.call()` 唯一收口  │
│  SQL 沙箱（`query/guard.py::SqlGuard`）+ 护栏（`Guardrail`）+ 租户校验    │
└──────────────────────────────────┬─────────────────────────────────────-┘
                                    ▼  ToolResult（rows/summary/notes）
┌─────────────────────────────────────────────────────────────────────────┐
│  推理平面 (Reasoning Plane)                    `src/vela/agent/`         │
│  七节点图：plan → retrieve → compress → verify → report (+ distill)     │
│  (+ human_gate / unanswerable 分支)                                      │
│  编排入口：`agent/graph.py::AgentGraph.run()`                            │
└───────────┬──────────────────────┬───────────────────────┬─────────────-┘
            ▼                      ▼                        ▼
┌───────────────────┐   ┌──────────────────────┐   ┌────────────────────-─┐
│ 模型网关            │   │ 证据链平面             │   │ 可观测/评估          │
│ `gateway/`         │   │ `evidencepack/`       │   │ `obs/` `eval/`       │
│ mock/火山引擎/      │   │ Merkle 证据包 +        │   │ 事件总线 + 指标 +    │
│ OpenAI 兼容/脱敏/   │   │ L0/L1/L2 三级验证      │   │ 黄金评测             │
│ 计量/审计           │   │                       │   │                     │
└───────────────────┘   └──────────────────────┘   └────────────────────-─┘

  入口：`src/vela/cli.py`（CLI 统一入口）  `src/vela/server/app.py`（本地 HTTP 服务）
```

约 7,100 行 Python（不含测试），61 个源文件，177 个单元/集成测试（`tests/`）。

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| 仿真器 | 生成/管理 10 个场景的车队日志数据集与 sidecar 真值 | `src/vela/sim/generate.py`, `src/vela/sim/scenarios.py`, `src/vela/sim/fleet.py`, `src/vela/sim/emitters.py` |
| 安全解包 | 压缩包解压，限制字节数/文件数/嵌套深度，禁止符号链接 | `src/vela/evidence/unpack.py` |
| 编码/清单发现 | 探测文件编码（UTF-8/GB18030/UTF-16/Latin-1）、组件归属规则匹配、解析顺序编排 | `src/vela/evidence/discover.py` |
| 多格式解析 | 13 个正则驱动解析器（YAML 配置，无需改代码新增格式） | `src/vela/evidence/parsers.py` |
| 多行聚合 | 按续行模式把多行异常/堆栈合并为单条逻辑记录 | `src/vela/evidence/reader.py` |
| 三级指纹 | `row_hash`（引用锚点）/ `raw_hash`（BLAKE3-128）/ `norm_hash`（xxh3-64，去重聚类） | `src/vela/evidence/fingerprint.py` |
| 时间归一 | 多时钟源归一到 UTC，附带 `ts_confidence`（WALL/MONOTONIC/DERIVED） | `src/vela/evidence/timeline.py` |
| 模板挖掘 | MiniDrain 日志模板聚类，`top_templates(rare)` 顶起低频模板 | `src/vela/evidence/template.py` |
| 列存写出 | Bronze/Silver/Gold 三层 Parquet 分片写出 | `src/vela/evidence/writer.py` |
| QA 校验 | 建库后结构化质量检查（`qa_report.json` + 人读 `.md`） | `src/vela/evidence/qa.py` |
| 建库编排 | Stage-0~8 全流程串联，产出 `BuildResult` | `src/vela/evidence/pipeline.py` |
| Gold 库 Schema | DuckDB 表结构定义与建表逻辑（53 列 `log_lines` 等） | `src/vela/evidence/gold.py`, `src/vela/evidence/models.py` |
| 查询门面 | 12 工具唯一实现，统一 `ToolResult`，租户校验、调用轨迹记录 | `src/vela/query/api.py` |
| 工具契约 | 12 工具的 JSON Schema 定义（鸟瞰/下钻分类） | `src/vela/query/tools.py` |
| 护栏与 SQL 沙箱 | 明细拉取硬上限、宽结果告警、SQL 白名单与行数上限 | `src/vela/query/guard.py` |
| 诊断图编排 | 七节点主循环、会话状态机、路由分支 | `src/vela/agent/graph.py` |
| 会话状态 | 可序列化/可 checkpoint 的 `SessionState` + `RoundRecord` | `src/vela/agent/state.py` |
| 技能检索 | 两段式技能库检索（本地哈希向量召回 + LLM 选择） | `src/vela/agent/skills.py` |
| 证据压缩 | 预算感知压缩：白名单封顶/稀有豁免/模板配额→滑窗摘要 | `src/vela/agent/compress.py` |
| 引用校验 | 程序化校验模型输出中的 `[[EV:row_hash]]` 引用，剔除悬空引用 | `src/vela/agent/citations.py` |
| 会话检查点 | 每轮结束落盘 `SessionState`，支持续跑 | `src/vela/agent/checkpoint.py` |
| 提示词 | 五个节点（planner/verifier/reporter/distiller）的系统提示与 user 构造函数 | `src/vela/gateway/prompts.py` |
| 模型网关 | 逻辑模型映射、脱敏、预算硬切断、降级链、审计的统一出口 | `src/vela/gateway/base.py` |
| 供应商适配器 | mock 确定性规则引擎 / OpenAI 兼容 / 火山引擎方舟 | `src/vela/gateway/mock.py`, `src/vela/gateway/openai_compat.py`, `src/vela/gateway/volcengine.py` |
| 出站脱敏 | VIN/GPS/手机号/IMEI/身份证/邮箱/IP 正则脱敏 | `src/vela/gateway/redact.py` |
| Token 预算 | 轮次/会话/租户三级 token 硬切断 | `src/vela/gateway/budget.py` |
| 调用审计 | JSONL 全量模型调用审计（默认仅落 prompt 哈希） | `src/vela/gateway/audit.py` |
| 证据包构建 | 把 `line_id`/`row_hash` 集合打包为含 Merkle 根的可离线验证证据包 | `src/vela/evidencepack/builder.py` |
| 证据包验证 | L0（自洽）/L1（库内）/L2（溯源重算字节指纹）三级验证 | `src/vela/evidencepack/verifier.py` |
| 快照双源解析 | 证据包引用行的双源（库/原始压缩包）解析 | `src/vela/evidencepack/snapshot.py` |
| 事件总线 | 结构化事件流（MILESTONE/PROGRESS/ALERT 分级），落盘 JSONL | `src/vela/obs/events.py` |
| 指标 | 计时器/计数器/量表的轻量指标收集 | `src/vela/obs/metrics.py` |
| 评测执行器 | 跑黄金评测集，逐场景执行诊断并计分 | `src/vela/eval/runner.py` |
| 评测口径 | 黄金用例定义、防答案泄漏校验 | `src/vela/eval/golden.py` |
| 评测报告 | 6 项核心指标计算与 Markdown 渲染 | `src/vela/eval/report.py` |
| 配置加载 | YAML 加载 + `BudgetProfile` + `config_hash`，环境变量覆盖收敛点 | `src/vela/config.py` |
| HTTP 服务 | 查询工具 REST 化 + 诊断会话 + SSE 事件流；FastAPI 优先，stdlib 兜底 | `src/vela/server/app.py` |
| CLI | 统一命令行入口（`sim`/`build`/`query`/`agent`/`eval`/`evidence`/`serve`/`doctor`） | `src/vela/cli.py` |
| 通用工具 | 哈希/ID 生成/文本规范化/时间处理/JSONL 读写 | `src/vela/util/` |

## Pattern Overview

**Overall:** 七层管道式（Pipeline）+ 有状态图编排（Graph Orchestration）混合架构。数据侧是单向流水线（仿真/接入 → 证据平面 → 查询平面），推理侧是带状态机与循环的图（推理平面），两者通过一个**唯一查询门面**（`LogQueryAPI`）解耦——推理层完全不知道底层是 DuckDB。

**Key Characteristics:**
- **本地优先、单机单进程**：DuckDB 单文件数据库 + Parquet 列存，无外部服务依赖；`vela doctor` 环境自检。
- **配置驱动，业务代码不硬编码阈值**：全部可调参数在 `config/*.yaml`（`pipeline.yaml`/`parsers.yaml`/`ota_phases.yaml`/`budget.yaml`/`llm.yaml`/`skills/builtin.yaml`），改行为不改代码。
- **供应商可插拔**：模型网关通过 `Provider` 抽象基类（`gateway/base.py`）统一 mock/OpenAI 兼容/火山引擎，切换只改环境变量 `VELA_LLM_PROVIDER`。
- **程序化校验优先于模型自述**：引用校验（`agent/citations.py`）、技能历史规避（`agent/state.py::excluded_skills`）、证据包三级验证均是独立于 LLM 输出的确定性代码路径。
- **鸟瞰-下钻两段式检索**：12 个工具按 `BIRDSEYE`/`DRILLDOWN` 分类（`query/tools.py`），推理图先鸟瞰后下钻，避免一开始就在明细数据里检索。

## Layers

**仿真/接入层 (`src/vela/sim/`):**
- Purpose: 生成确定性可复现的车队 OTA 日志数据集（10 场景：9 故障 + 1 健康），或接受生产日志压缩包作为等价输入。
- Location: `src/vela/sim/`
- Contains: `fleet.py`（车队/VIN 生成）、`scenarios.py`（场景定义）、`emitters.py`（逐条日志渲染）、`generate.py`（数据集编排 + sidecar 真值写出）。
- Depends on: `util/`（哈希/ID/文本）。
- Used by: 无上游依赖，是数据流起点；生产环境跳过此层，直接提供压缩包给证据平面。

**证据平面 (`src/vela/evidence/`):**
- Purpose: 把原始日志压缩包转化为可查询、可核验的列式取证库（Bronze/Silver/Gold 三层）。
- Location: `src/vela/evidence/`
- Contains: 解包（`unpack.py`）、发现/编码探测（`discover.py`）、解析器（`parsers.py`）、多行聚合（`reader.py`）、指纹（`fingerprint.py`）、时间归一（`timeline.py`）、模板挖掘（`template.py`）、写出（`writer.py`）、QA（`qa.py`）、Gold 库建表（`gold.py`）、编排（`pipeline.py`）。
- Depends on: `config.py`（YAML 配置）、`util/`。
- Used by: 查询平面（读取产出的 DuckDB Gold 库）、`evidencepack/`（L2 溯源验证时重算字节指纹）。

**查询平面 (`src/vela/query/`):**
- Purpose: 是 Gold 库的唯一合法访问入口，提供 12 个受护栏约束的只读工具。
- Location: `src/vela/query/`
- Contains: `api.py`（`LogQueryAPI` 门面 + `ToolResult`）、`tools.py`（工具 JSON Schema 目录）、`guard.py`（`Guardrail` + `SqlGuard`）。
- Depends on: `config.py`（`BudgetProfile`）、`duckdb`。
- Used by: 推理平面（`agent/graph.py` 通过 `LogQueryAPI.call()` 调用全部工具）、HTTP 服务（`server/app.py`）、CLI `vela query`。

**推理平面 (`src/vela/agent/`):**
- Purpose: 七节点图驱动的诊断编排：预算感知压缩、技能检索、程序化引用校验、双层编排（探测轮 + 蒸馏轮）。
- Location: `src/vela/agent/`
- Contains: `graph.py`（`AgentGraph` 主循环与全部节点方法）、`state.py`（`SessionState`/`RoundRecord`）、`skills.py`（`SkillRegistry` 两段式检索）、`compress.py`（`EvidenceCompressor`）、`citations.py`（引用校验）、`checkpoint.py`（会话持久化）。
- Depends on: `query/api.py`（工具调用）、`gateway/`（模型调用）、`obs/`（事件/指标）、`config.py`（预算配置）。
- Used by: CLI `vela agent diagnose`、HTTP 服务 `/diagnose`、评测执行器 `eval/runner.py`。

**模型网关 (`src/vela/gateway/`):**
- Purpose: 统一模型调用出口：逻辑模型→物理模型映射、出站脱敏、三级 token 预算硬切断、降级链、全量审计。
- Location: `src/vela/gateway/`
- Contains: `base.py`（`LLMGateway`/`Provider`/`build_gateway`）、`mock.py`（确定性规则引擎）、`openai_compat.py`、`volcengine.py`、`redact.py`、`budget.py`（`TokenLedger`）、`audit.py`、`prompts.py`。
- Depends on: `config.py`（`llm.yaml`）。
- Used by: 推理平面（每个 LLM 节点通过 `AgentGraph._llm()` 调用）。

**证据链平面 (`src/vela/evidencepack/`):**
- Purpose: 把诊断结论引用的行集合打包为带 Merkle 根的证据包，支持离线三级验证。
- Location: `src/vela/evidencepack/`
- Contains: `builder.py`（构建）、`verifier.py`（L0/L1/L2 验证）、`snapshot.py`（双源行解析）。
- Depends on: `evidence/fingerprint.py`（重算字节指纹）、`query/api.py`（L1 库内校验）。
- Used by: 推理平面（`node_report` 调用 `build_evidence` 工具）、CLI `vela evidence verify`。

**可观测/评估 (`src/vela/obs/`, `src/vela/eval/`):**
- Purpose: 结构化事件与指标采集；黄金评测集全链路评测与达标判定。
- Location: `src/vela/obs/`, `src/vela/eval/`
- Contains: `obs/events.py`（`EventBus`/`Severity`）、`obs/metrics.py`（`Metrics`）、`eval/golden.py`（黄金用例+防泄漏）、`eval/runner.py`（`EvalRunner`）、`eval/report.py`（6 项指标+`_TARGETS`+Markdown 渲染）。
- Depends on: `agent/graph.py`（评测执行器直接跑诊断图）。
- Used by: CLI `vela eval run`、HTTP 服务 `/metrics` `/events`。

## Data Flow

### 主诊断路径（`vela agent diagnose`）

1. CLI 解析参数，构造 `AgentGraph`（`src/vela/cli.py::cmd_agent`）
2. `AgentGraph.__init__` 装配 `LogQueryAPI`、`SkillRegistry`、`EventBus`、`TokenLedger`、`build_gateway()`、`CheckpointStore`（`src/vela/agent/graph.py:88-109`）
3. `AgentGraph.run()` 主循环，每轮：
   - `node_plan`：第一轮先跑 4 个鸟瞰探针（`BIRDSEYE_PROBES`），吸收信号到 `st.signals`；再做技能检索（`SkillRegistry.retrieve`）+ LLM 规划，程序化剔除已用/失效技能（`src/vela/agent/graph.py:129-166`）
   - `node_retrieve`：按规划的 actions 调用 `LogQueryAPI.call()` 下钻取证据（`src/vela/agent/graph.py:168-192`）
   - `node_compress`：`EvidenceCompressor.compress()` 做预算感知压缩，更新 `st.evidence_pool`/`st.seen_row_hashes`（`src/vela/agent/graph.py:194-208`）
   - `node_verify`：LLM 生成 claim 判定 + 程序化 `verify_citations()` 独立校验引用（`src/vela/agent/graph.py:210-239`）
   - 决定性判据满足（`decisive and productive`）→ `node_report`；连续 2 轮无新证据 → `node_human_gate`；否则进入下一轮
4. `node_report`：构建证据链（`_build_chain`）、判定根因（`_root_cause`）、LLM 生成中文报告、`verify_citations()` 剔除悬空引用、调用 `build_evidence` 工具生成证据包（`src/vela/agent/graph.py:241-267`）
5. 会话结束（`answered`）后异步跑 `node_distill`：知识蒸馏候选写入 `knowledge/candidates.jsonl`（`src/vela/agent/graph.py:269-281`）
6. 每轮结束 `CheckpointStore.save(st)` 落盘，支持中断续跑

### 建库路径（`vela build`）

1. `evidence/pipeline.py::build()` 编排 Stage-0~8（`src/vela/evidence/pipeline.py:66-`）
2. Stage-0 安全解包（`evidence/unpack.py::extract`）→ 读取 `package_meta.json`（可选，缺失走 mtime 推断）
3. Stage-1 清单与编码探测（`evidence/discover.py::inventory`）
4. Stage-2~5 逐文件解析（`ParserRegistry`）→ 多行聚合（`MultilineAggregator`）→ 指纹（`fingerprints`）→ 阶段/级别推断
5. 模板挖掘（`MiniDrain`）→ 分片写出（`ShardWriter`）→ Gold 库建表（`evidence/gold.py`）
6. QA 校验产出 `qa_report.json`/`.md`

**State Management:**
- 会话状态（`SessionState`）是唯一的可变推理状态，全字段可序列化（`to_dict`/`from_dict`），每轮落盘至 `{workspace}/sessions/`，支持跨进程续跑。
- 底层数据状态在 DuckDB 文件中，`LogQueryAPI` 以只读模式连接（`read_only=True`），推理平面不修改列式库。

## Key Abstractions

**ToolResult (`src/vela/query/api.py`):**
- Purpose: 12 个查询工具的统一返回契约，承载 rows/summary/护栏 notes/token 估算。
- Examples: `src/vela/query/api.py:31-52`
- Pattern: dataclass + `to_dict()` 序列化；`notes` 字段把护栏降级信息注入模型上下文，形成"在环负反馈"。

**SessionState / RoundRecord (`src/vela/agent/state.py`):**
- Purpose: 推理图的全部可变状态；`excluded_skills()` 是程序化历史规避的核心方法。
- Examples: `src/vela/agent/state.py:29-86`
- Pattern: 可序列化 dataclass，每轮 `RoundRecord` 追加到 `rounds` 列表，供审计与蒸馏使用。

**Provider (`src/vela/gateway/base.py`):**
- Purpose: 模型供应商适配器接口，新增供应商只需实现 `complete()`。
- Examples: `MockProvider`（`gateway/mock.py`）、`OpenAICompatProvider`（`gateway/openai_compat.py`）、火山引擎（`gateway/volcengine.py`）
- Pattern: 策略模式；`build_gateway()` 按 `VELA_LLM_PROVIDER` 环境变量或 `llm.yaml` 动态选择实现。

**BudgetProfile (`src/vela/config.py`):**
- Purpose: 机制一/机制四（预算压缩+护栏）的全部可调参数，从 `budget.yaml` 的某个 profile（poc/production）实例化。
- Examples: `src/vela/config.py:48-100`
- Pattern: frozen dataclass，贯穿 `EvidenceCompressor`、`Guardrail`、`TokenLedger` 三处消费者。

**TOOL_SPECS 工具目录 (`src/vela/query/tools.py`):**
- Purpose: 12 工具的 JSON Schema 定义，按 `BIRDSEYE`/`DRILLDOWN` 分类驱动"先鸟瞰后下钻"的检索纪律。
- Examples: `src/vela/query/tools.py:7-99`
- Pattern: 静态数据表 + 查询函数（`birdseye_tools()`/`drilldown_tools()`/`compact_catalog()`）。

## Entry Points

**CLI (`src/vela/cli.py`):**
- Location: `src/vela/cli.py`
- Triggers: `vela <subcommand>`（通过 `pyproject.toml` 的 `[project.scripts] vela = "vela.cli:main"` 注册），或 `python -m vela.cli`。
- Responsibilities: 子命令路由（`sim`/`build`/`query`/`agent`/`eval`/`evidence`/`serve`/`doctor`），每个 `cmd_*` 函数负责参数到内部 API 的转换与结果打印（`src/vela/cli.py:202-281`）。

**HTTP 服务 (`src/vela/server/app.py`):**
- Location: `src/vela/server/app.py`
- Triggers: `vela serve --db DB [--workspace DIR]`；FastAPI 可用则用之（自动 OpenAPI 文档），否则降级到标准库 `http.server`。
- Responsibilities: 路由 `/health` `/tools` `/describe` `/call` `/diagnose` `/metrics` `/events`（SSE），业务逻辑全部委托 `_handle()`（`src/vela/server/app.py:27-71`），不重复实现。

**脚本入口 (`scripts/`):**
- `scripts/demo_end_to_end.py`：一条命令跑通仿真→建库→诊断→证据验证全链路演示。
- `scripts/bench.py`：建库吞吐 + 诊断延迟基准测量。

## Architectural Constraints

- **单线程/单进程：** 无并发模型；`AgentGraph.run()` 是同步阻塞循环，DuckDB 连接单进程持有。
- **DuckDB 单文件数据库：** 无分布式能力；`query/api.py::LogQueryAPI` 以 `read_only=True` 连接单一 `.duckdb` 文件，生产量级（数亿行/天）需迁移 ClickHouse/StarRocks（见 `docs/PRODUCTION_MIGRATION.md`）。
- **全局可变状态：** `src/vela/server/app.py` 用模块级字典 `_STATE` 保存单一数据库连接与工作区路径（`src/vela/server/app.py:13`），服务进程只能绑定一个 db/workspace，不支持多租户并发挂载。
- **`@lru_cache` 配置缓存：** `config.py::load_yaml()` 用 `lru_cache(maxsize=32)` 缓存 YAML 内容（`src/vela/config.py:28`），进程内修改配置文件后需重启才能生效（测试中需注意缓存穿透风险）。
- **空目录 `src/vela/agent/nodes/`：** 存在但无 `.py` 文件，实际七节点逻辑全部以方法形式实现在 `agent/graph.py`（`AgentGraph.node_*`），未拆分为独立模块——新增节点时应遵循现状（方法级组织），而非误以为需要在 `nodes/` 目录下新建文件。

## Anti-Patterns

### 无（未发现明显反模式）

代码库整体遵循"配置驱动 + 程序化校验 + 统一门面"的一致纪律；查询门面（`LogQueryAPI`）、模型网关（`Provider` 接口）、护栏（`Guardrail`/`SqlGuard`）均做到了单一实现来源，未发现绕过唯一收口的旁路调用。

## Error Handling

**Strategy:** 分层显式处理 + 优雅降级，不用异常吞没关键失败。

**Patterns:**
- 模型调用失败走"降级链"（`gateway/base.py::LLMGateway.chat`，`src/vela/gateway/base.py:113-148`）：逐个尝试 `provider.models_for()` 返回的物理模型列表，全部失败才抛 `LLMError`。
- 预算超限用专用异常 `BudgetExceeded`（`gateway/budget.py`），在 `AgentGraph.run()` 中被捕获并转为 `node_unanswerable`（诚实作答"证据不足"），而非静默中断（`src/vela/agent/graph.py:313-317, 380-381`）。
- 查询工具的护栏失败通过 `ToolResult.error`/`notes` 字段返回，不抛异常打断推理循环，允许模型看到降级说明并调整策略。
- 证据平面遇到解析失败的记录会标记 `PARSE_UNPARSED`/`PARSE_ENCODING_ERROR` 等状态码写入 Gold 库，而非丢弃（`src/vela/evidence/models.py`），保证"不可解析的日志也留痕"。

## Cross-Cutting Concerns

**Logging:** 无标准 `logging` 模块使用；采用结构化事件总线（`obs/events.py::EventBus`）落盘 JSONL，按 `Severity`（PROGRESS/MILESTONE/ALERT）分级，CLI/服务打印走 `print()`。

**Validation:** 输入侧靠 JSON Schema（`query/tools.py`）描述工具参数（未见运行时强校验库，如 jsonschema）；输出侧靠程序化引用校验（`agent/citations.py::verify_citations`）与证据包三级验证（`evidencepack/verifier.py`）。

**Authentication:** 无用户级鉴权；仅有"租户校验"（`query/api.py::_check_tenant`，比对 `runs.tenant_id` 与 `VELA_TENANT` 环境变量），面向多租户数据隔离而非访问控制。

---

*Architecture analysis: 2026-07-30*
