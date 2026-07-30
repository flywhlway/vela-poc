# Codebase Structure

**Analysis Date:** 2026-07-30

## Directory Layout

```
vela-poc/
├── README.md                      项目说明（30 秒概览/五分钟跑起来/七层架构/CLI 全部命令）
├── pyproject.toml                 包定义（name=vela, CLI 入口 vela=vela.cli:main）
├── requirements.txt                必需依赖：duckdb / pyarrow / PyYAML / pytz
├── requirements-optional.txt        可选依赖：xxhash / blake3 / fastapi / uvicorn / pytest
├── .env.example                    环境变量样例（存在性确认，不读取内容）
├── Makefile                        常用任务封装（install/doctor/sim/build/agent/eval/test/serve/lint）
├── run_all.sh                      一键全流程脚本（自检→仿真→建库→诊断→评测→测试）
│
├── config/                        全部可调参数，业务代码不硬编码任何阈值
│   ├── pipeline.yaml               解包/发现/解析/时间/模板/写出/QA 全部阈值
│   ├── parsers.yaml                13 个日志格式解析器（正则+优先级）
│   ├── ota_phases.yaml             9 条阶段识别规则 + 15 个 UDS NRC 语义字典
│   ├── budget.yaml                 poc/production 双档预算（压缩/计量/护栏）
│   ├── llm.yaml                    模型网关：逻辑模型映射/供应商/脱敏规则/审计开关
│   └── skills/
│       └── builtin.yaml            12 个内置诊断技能（触发条件+探针+关键词）
│
├── src/vela/                      唯一 Python 包（`pyproject.toml` 的 `where = ["src"]`）
│   ├── cli.py                     统一 CLI 入口
│   ├── config.py                  YAML 加载 + BudgetProfile + config_hash
│   ├── version.py                 版本号 + schema 版本 + canon 规则版本
│   ├── py.typed                   PEP 561 类型标记（打包声明见 pyproject.toml）
│   │
│   ├── sim/                       仿真层：车队/场景/事件渲染/数据集生成
│   │   ├── fleet.py
│   │   ├── scenarios.py
│   │   ├── emitters.py
│   │   └── generate.py
│   │
│   ├── evidence/                  证据平面：Stage-0~8 全流程
│   │   ├── unpack.py               Stage-0 安全解包
│   │   ├── discover.py             Stage-1 清单/编码探测
│   │   ├── parsers.py              Stage-2 多格式解析器（YAML 驱动）
│   │   ├── reader.py               多行聚合
│   │   ├── fingerprint.py          Stage-3 三级指纹 + 去重 + 分词
│   │   ├── timeline.py             Stage-4 时间归一 + 置信度
│   │   ├── template.py             Stage-5 MiniDrain 模板挖掘
│   │   ├── writer.py               Stage-6 列存分片写出
│   │   ├── gold.py                 Gold 库建表（DuckDB schema）
│   │   ├── qa.py                   Stage-8 QA 校验
│   │   ├── models.py               记录模型/状态码常量
│   │   └── pipeline.py             build() 全流程编排入口
│   │
│   ├── query/                      查询平面：12 工具 + 护栏 + SQL 沙箱
│   │   ├── api.py                  LogQueryAPI（唯一门面）+ ToolResult
│   │   ├── tools.py                12 工具 JSON Schema 目录
│   │   └── guard.py                Guardrail + SqlGuard
│   │
│   ├── agent/                      推理平面：七节点图 + 压缩 + 技能 + 引用校验
│   │   ├── graph.py                AgentGraph（主循环 + 全部 node_* 方法）
│   │   ├── state.py                SessionState / RoundRecord
│   │   ├── skills.py                SkillRegistry（两段式技能检索）
│   │   ├── compress.py             EvidenceCompressor（预算感知压缩）
│   │   ├── citations.py            程序化引用校验
│   │   ├── checkpoint.py           CheckpointStore（会话持久化）
│   │   └── nodes/                  空目录（无 .py 文件；节点逻辑实际在 graph.py 内实现）
│   │
│   ├── evidencepack/               证据链：构建器 + 三级验证器 + 快照双源解析
│   │   ├── builder.py
│   │   ├── verifier.py
│   │   └── snapshot.py
│   │
│   ├── gateway/                    模型网关：mock / 火山引擎 / OpenAI 兼容 / 脱敏 / 计量 / 审计
│   │   ├── base.py                 LLMGateway / Provider / build_gateway
│   │   ├── mock.py                 确定性规则引擎供应商
│   │   ├── openai_compat.py        OpenAI 兼容端点供应商
│   │   ├── volcengine.py           火山引擎方舟供应商
│   │   ├── redact.py               出站脱敏
│   │   ├── budget.py               TokenLedger（预算硬切断）
│   │   ├── audit.py                Auditor（JSONL 调用审计）
│   │   └── prompts.py              5 个节点的系统提示 + user 构造函数
│   │
│   ├── obs/                        可观测：事件总线 + 指标
│   │   ├── events.py               EventBus / Severity
│   │   └── metrics.py              Metrics（计时器/计数器/量表）
│   │
│   ├── eval/                       评估：黄金用例 + 评测执行器 + 报告渲染
│   │   ├── golden.py                黄金用例定义 + 防答案泄漏校验
│   │   ├── runner.py                EvalRunner（跑全部场景诊断）
│   │   └── report.py                6 项核心指标计算 + Markdown 渲染
│   │
│   ├── server/                     本地 HTTP 服务（FastAPI 优先，标准库兜底）
│   │   └── app.py                  路由 + build_app()/serve()
│   │
│   └── util/                       通用工具
│       ├── hashing.py               哈希算法（含 fingerprint_algos）
│       ├── ids.py                   run_id/session_id 生成
│       ├── textutil.py              文本规范化 + VIN 脱敏 + token 估算
│       ├── timeutil.py              时间解析/格式化
│       └── jsonl.py                 JSONL 读写 + canonical_json
│
├── scripts/
│   ├── demo_end_to_end.py         一条命令跑通仿真→建库→诊断→验证全链路
│   └── bench.py                   建库吞吐 + 诊断延迟基准测量
│
├── tests/                         177 个用例，覆盖全部模块
│   ├── conftest.py                 共享 fixture
│   ├── test_agent.py                推理平面（压缩/引用校验/七节点图端到端）
│   ├── test_cli_and_server.py       CLI/服务全路径
│   ├── test_eval.py                 评估口径 + 防泄漏
│   ├── test_evidence_pipeline.py    证据平面安全解包/解析/QA
│   ├── test_evidencepack.py         证据包三级验证/快照双源解析
│   ├── test_gateway.py              模型网关脱敏/预算/mock 契约/火山引擎适配器
│   ├── test_obs_and_config.py       可观测/配置
│   ├── test_query_api.py            查询平面 12 工具+护栏+SQL 沙箱
│   ├── test_sim.py                  仿真器 VIN 校验与逐字节可复现性
│   └── test_util.py                 工具层哈希/ID/文本规范化确定性
│
├── data/                           数据目录（非源码）
│   ├── dataset/                    `vela sim generate` 产出的场景压缩包 + sidecar 真值（*.truth.json，永不进 zip 包）
│   └── incoming/                   生产日志接入落地目录（含 README.md 说明约定）
│
├── docs/                           设计与运维文档
│   ├── MECHANISM_MAPPING.md        两份原始技术文档的机制 → 代码位置映射表
│   ├── SCHEMA.md                   log_lines 等全部列式表结构说明
│   ├── TOOLS.md                    12 个 Agent 工具的完整契约与示例
│   ├── LLM_PRODUCTION.md           接入火山引擎方舟（生产级大模型）指引
│   └── PRODUCTION_MIGRATION.md     POC → 生产平台的过渡路线图
│
├── explore-docs/                  探索性分析文档（非正式设计文档，多为改造方案草稿）
│
└── .planning/                     GSD 规划元数据目录（本文档所在位置：.planning/codebase/）
```

## Directory Purposes

**`config/`:**
- Purpose: 全部业务可调参数的唯一来源；`src/vela/config.py::load_yaml()` 从此目录加载（可用 `VELA_CONFIG_DIR` 环境变量覆盖路径）。
- Contains: YAML 配置文件，无 Python 代码。
- Key files: `budget.yaml`（预算/护栏双档 profile）、`llm.yaml`（供应商与脱敏规则）、`skills/builtin.yaml`（技能库）。

**`src/vela/sim/`:**
- Purpose: 仿真车队 OTA 升级日志，产出与生产压缩包同结构的 `.zip` + sidecar `.truth.json`（真值，仅评测使用，永不打包进 zip）。
- Contains: 场景定义、车队/VIN 生成、逐条日志事件渲染、数据集写出编排。
- Key files: `scenarios.py`（`SCENARIOS` 字典，`vela sim generate --list` 的数据源）。

**`src/vela/evidence/`:**
- Purpose: 把原始日志压缩包转化为列式取证库（Bronze/Silver/Gold）的全部 Stage-0~8 实现。
- Contains: 每个 Stage 对应一个模块（解包/发现/解析/多行聚合/指纹/时间/模板/写出/QA），`pipeline.py` 是唯一编排入口。
- Key files: `pipeline.py::build()`（外部唯一调用入口）、`gold.py`（DuckDB 表结构定义，改列需同步更新 `docs/SCHEMA.md`）。

**`src/vela/query/`:**
- Purpose: Gold 库的唯一合法读接口；任何需要"查日志"的代码（Agent/HTTP 服务/CLI）都必须经过 `LogQueryAPI`，禁止直连 DuckDB。
- Contains: 门面实现、工具 Schema 目录、护栏。
- Key files: `api.py::LogQueryAPI.call()`（统一入口，含租户校验与调用轨迹记录）。

**`src/vela/agent/`:**
- Purpose: 七节点诊断图与其支撑组件（状态、技能、压缩、引用校验、检查点）。
- Contains: `graph.py` 是最大最核心的文件（全部节点方法 + 主循环），其余文件是被 `graph.py` 组合使用的独立能力模块。
- Key files: `graph.py::AgentGraph`（唯一编排类）、`state.py::SessionState`（唯一可变状态容器）。
- Note: `nodes/` 子目录存在但为空——不要假设节点逻辑分散在此目录下的文件中。

**`src/vela/gateway/`:**
- Purpose: 大模型调用的统一出口，隔离业务代码与具体供应商 SDK/API 差异。
- Contains: 网关核心（`base.py`）+ 供应商适配器（mock/openai_compat/volcengine）+ 横切能力（脱敏/预算/审计/提示词）。
- Key files: `base.py::build_gateway()`（按 `VELA_LLM_PROVIDER` 环境变量或 `llm.yaml::active` 选择供应商）。

**`src/vela/evidencepack/`:**
- Purpose: 诊断结论的可离线验证载体（证据包），独立于运行中的 DuckDB 库也能自洽校验（L0 级）。
- Contains: 构建、三级验证、双源（库/原始压缩包）行内容解析。

**`src/vela/obs/`, `src/vela/eval/`:**
- Purpose: 横切的可观测能力（事件/指标）与端到端评估能力（黄金评测）。
- Contains: 事件总线与指标收集；黄金用例、评测执行、报告渲染。

**`tests/`:**
- Purpose: 单元/集成测试，按源码模块一一对应命名（`test_<module>.py`）。
- Contains: 177 个用例；`conftest.py` 提供跨文件共享 fixture（数据库/临时目录等）。
- Generated: 否；Committed: 是。

**`data/`:**
- Purpose: 运行期数据资产，非源码。
- Contains: `dataset/` 仿真数据集输出（脚本可重新生成）；`incoming/` 生产日志落地目录（含使用说明）。
- Generated: `dataset/` 内容是生成产物（`vela sim generate`）；`incoming/README.md` 为手写说明。
- Committed: 视 `.gitignore` 而定（`.zip`/`.truth.json` 属大体积生成产物，通常不建议提交仓库，但当前仓库已包含示例数据）。

**`docs/`:**
- Purpose: 面向开发者的设计文档，与代码保持同步（如 `SCHEMA.md` 对应 `evidence/gold.py` 的表结构）。
- Contains: 机制映射、Schema 说明、工具契约、生产接入指引、迁移路线图。

**`workspace/`（未纳入版本控制，运行期生成）:**
- Purpose: `vela build`/`vela agent diagnose`/`vela eval run` 等命令的输出目录（Bronze/Silver/Gold 数据、会话检查点、事件日志、审计日志、评测报告）。
- Generated: 是；Committed: 否（不在上文目录树中，因为是运行期产物，未在本次探索中枚举）。

## Key File Locations

**Entry Points:**
- `src/vela/cli.py`: CLI 统一入口，`pyproject.toml` 注册为 `vela` 命令。
- `src/vela/server/app.py`: HTTP 服务入口，`vela serve` 调用其 `serve()`。
- `scripts/demo_end_to_end.py`: 端到端演示脚本入口。

**Configuration:**
- `src/vela/config.py`: 配置加载与覆盖优先级实现（函数参数 > 环境变量 > YAML > 代码默认值）。
- `config/*.yaml`: 实际配置内容。
- `.env.example`: 环境变量样例（生产大模型接入等），实际使用需 `cp .env.example .env`。

**Core Logic:**
- `src/vela/evidence/pipeline.py`: 建库全流程编排。
- `src/vela/agent/graph.py`: 诊断全流程编排。
- `src/vela/query/api.py`: 数据访问唯一门面。

**Testing:**
- `tests/`: 全部测试，`pyproject.toml` 的 `[tool.pytest.ini_options]` 声明 `testpaths = ["tests"]`。
- `pytest.ini` 等价配置内嵌在 `pyproject.toml`，标记 `slow`/`determinism` 已注册。

## Naming Conventions

**Files:**
- 模块名用 snake_case 且高度语义化，直接对应技术方案中的阶段/机制名（如 `fingerprint.py`、`timeline.py`、`checkpoint.py`）。
- 测试文件固定前缀 `test_` + 被测源码目录/模块名（如 `test_evidence_pipeline.py` 对应 `evidence/pipeline.py`，`test_query_api.py` 对应 `query/api.py`）。

**Directories:**
- 顶层子包名即架构层名的英文缩写（`sim`/`evidence`/`query`/`agent`/`evidencepack`/`gateway`/`obs`/`eval`/`server`/`util`），与 README 的"七层架构"图一一对应，新增顶层能力时应遵循"一个架构层 = 一个顶层子包"的映射。

**Classes/Functions:**
- 核心编排类用领域名词 + 无后缀（`AgentGraph`、`LogQueryAPI`、`SkillRegistry`、`EvidenceCompressor`），而非 `*Manager`/`*Service` 等泛化后缀。
- 数据契约用 `@dataclass`（`ToolResult`、`SessionState`、`RoundRecord`、`BudgetProfile`、`LLMRequest`/`LLMResponse`），大量使用 `frozen=True` 表达不可变配置对象。
- 工厂函数用 `build_*` 前缀（`build_gateway`、`build_app`、`build_parser`）；顶层编排函数用动词短语（`diagnose()`、`build()`、`generate_dataset()`）。

## Where to Add New Code

**新增日志格式解析器:**
- 只需在 `config/parsers.yaml` 增加一条正则规则，不需要改 `src/vela/evidence/parsers.py`（`ParserRegistry` 是 YAML 驱动的）。

**新增诊断技能:**
- 在 `config/skills/builtin.yaml` 增加一个技能条目（`trigger`/`summary`/`probes`/`keywords`/`root_cause_label`），不需要改 `src/vela/agent/skills.py`。

**新增 Agent 查询工具:**
- Schema 定义: `src/vela/query/tools.py`（追加到 `TOOL_SPECS`，标注 `BIRDSEYE`/`DRILLDOWN`）。
- 实现: `src/vela/query/api.py`（`LogQueryAPI` 增加对应的 `_tool_<name>` 方法并在 `call()` 分发）。
- 测试: `tests/test_query_api.py`。

**新增诊断图节点/推理逻辑:**
- 实现: `src/vela/agent/graph.py`（新增 `node_*` 方法，遵循现有的方法级组织；不要在空的 `agent/nodes/` 目录下创建文件，除非明确决定要重构拆分）。
- 状态字段: 如需持久化新状态，扩展 `src/vela/agent/state.py::SessionState`。
- 测试: `tests/test_agent.py`。

**新增模型供应商:**
- 实现: `src/vela/gateway/` 下新建模块，继承 `Provider`（`gateway/base.py`）并实现 `models_for()`/`complete()`。
- 注册: `config/llm.yaml` 增加 `providers.<name>`，在 `gateway/base.py::build_gateway()` 的 `kind` 分支中接入。
- 测试: `tests/test_gateway.py`。

**新增证据平面 Stage/字段:**
- 实现: `src/vela/evidence/` 下对应模块；新增列需同步 `evidence/gold.py`（建表）与 `docs/SCHEMA.md`（文档）。
- 测试: `tests/test_evidence_pipeline.py`。

**新增评测指标:**
- 实现: `src/vela/eval/report.py`（扩展 `_TARGETS` 与指标计算函数）。
- 测试: `tests/test_eval.py`。

**通用工具函数（跨层复用）:**
- 位置: `src/vela/util/`，按职责选择既有模块（哈希→`hashing.py`，ID→`ids.py`，文本→`textutil.py`，时间→`timeutil.py`，JSONL→`jsonl.py`），避免在业务层模块内重复实现。

## Special Directories

**`src/vela/agent/nodes/`:**
- Purpose: 当前为空，无 `.py` 文件；推测为节点拆分的预留位，实际未使用。
- Generated: 否
- Committed: 是（空目录，Git 通常不追踪空目录，需确认是否有 `.gitkeep`）

**`config/skills/`:**
- Purpose: 技能库配置目录，支持多个 `*.yaml` 文件合并加载（`config.py::load_skills()` 会 glob 该目录下所有 YAML）。
- Generated: 否
- Committed: 是

**`data/dataset/`:**
- Purpose: 仿真数据集输出；`.zip` 是压缩包（Agent 唯一可见输入），`.truth.json` 是评测真值 sidecar（绝不进入 `.zip`，`tests/test_eval.py::test_truth_narrative_never_reaches_agent_context` 专门校验隔离性）。
- Generated: 是（`vela sim generate` 产出）
- Committed: 是（当前仓库已包含示例场景数据）

**`workspace/`（不在当前目录树中，运行期生成，未纳入版本控制）:**
- Purpose: 每次 `build`/`diagnose`/`eval` 运行的输出根目录，内部结构为 `bronze/ silver/ gold/ qa/ evidence/ sessions/ obs/ knowledge/`。
- Generated: 是
- Committed: 否

**`explore-docs/`:**
- Purpose: 探索性/草稿性质的改造方案文档（技能知识库分析、LLM 准确率归因、双驱动架构升级等），与 `docs/` 下的正式设计文档区分开。
- Generated: 否
- Committed: 是

---

*Structure analysis: 2026-07-30*
