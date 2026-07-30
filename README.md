# VELA —— 车端 OTA 日志证据化诊断平台（POC）

**V**ehicle **E**vidence & **L**og **A**nalytics

本地优先、纯 Python 实现的车联网 OTA 升级日志智能诊断系统。把海量、多格式、多编码的车端日志，
转化为**可查询、可压缩、可核验、可追溯**的诊断证据链，供 Agent 自动定位根因并产出带引用的诊断报告。

工程统一实现了两份技术输入文档的全部内容：
- 《OTA车端日志预处理与列式取证库技术方案》—— 数据层：解析、指纹、时间归一、列式存储、查询工具
- 《基于预算感知证据压缩与可追溯证据链的车联网海量日志智能诊断系统及方法》专利技术交底书 —— 推理层：
  七大机制（预算压缩、引用校验、两段式技能检索、鸟瞰-下钻护栏、时间置信度、双层编排、知识自增强）

两者的映射关系见 [`docs/MECHANISM_MAPPING.md`](docs/MECHANISM_MAPPING.md)。

---

## 目录

- [30 秒看懂它做什么](#30-秒看懂它做什么)
- [五分钟跑起来](#五分钟跑起来)
- [七层架构](#七层架构)
- [目录结构](#目录结构)
- [核心概念速查](#核心概念速查)
- [配置说明](#配置说明配置全部在-config)
- [生产数据接入](#生产数据接入替换仿真器)
- [接入真实大模型（火山引擎方舟）](#接入真实大模型火山引擎方舟)
- [评测体系](#评测体系)
- [测试](#测试)
- [CLI 全部命令](#cli-全部命令)
- [向生产平台过渡](#向生产平台过渡)
- [已知局限](#已知局限-poc-诚实声明)
- [常见问题排查](#常见问题排查)

---

## 30 秒看懂它做什么

```
原始日志压缩包（多格式/多编码/跨 ECU）
        │  Stage-0~8：安全解包 → 编码探测 → 逐格式解析 → 三级指纹 → 时间归一 → 模板挖掘 → 列存
        ▼
DuckDB + Parquet 列式取证库（53 列 schema，行级 row_hash 引用锚点）
        │  12 个只读工具（鸟瞰 6 个 + 下钻 6 个），全部经 SQL 沙箱 + 护栏收口
        ▼
Agent 七节点推理图：plan → retrieve → compress → verify → report（+ human_gate / unanswerable）
        │  预算感知压缩（白名单封顶/稀有豁免/模板配额→滑窗摘要）+ 系统级引用校验（不信任模型自述）
        ▼
中文诊断报告（每个结论带 [[EV:row_hash]] 引用）+ 证据包（Merkle 根，L0/L1/L2 三级离线可验证）
```

一句话：**日志证据的"取证-压缩-推理-验证"全链路，本地全跑通，不依赖任何外部服务，且随时可切换到真实大模型。**

---

## 五分钟跑起来

```bash
cd vela-poc
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[all]"              # 或 pip install -r requirements.txt -r requirements-optional.txt

# 1. 环境自检
vela doctor

# 2. 生成仿真数据集（10 个场景：9 个故障 + 1 个健康负样本，约 23 万条记录，几秒钟）
vela sim generate --out ./data/dataset

# 3. 建立列式取证库（对某一个场景）
vela build ./data/dataset/OTA_988574_TASK-10069.zip ./workspace/demo

# 4. 跑 Agent 诊断（默认 mock 大模型，确定性、零外部依赖）
vela agent diagnose --db ./workspace/demo/gold/analysis.duckdb --workspace ./workspace/demo

# 5. 一条命令看完整链路（仿真→建库→诊断→证据验证）
python scripts/demo_end_to_end.py --scenario S3_UDS_NRC72

# 6. 跑全部黄金评测（10 场景，验证 Top-1 命中率/假阳性率/悬空引用率等指标）
python -m vela.cli eval run --dataset ./data/dataset --workspace ./workspace/eval

# 7. 跑全部单元测试（177 个用例）
pytest tests/ -q
```

没有 Docker，没有外部数据库，没有网络依赖（mock 供应商下）。`pip install`
之后从第一条命令到看到诊断报告，全程本地、几十秒内完成。

---

## 七层架构

```
┌─────────────────────────────────────────────────────────────────────┐
│  仿真/接入层  src/vela/sim/            10 场景仿真器；生产日志见下方  │
├─────────────────────────────────────────────────────────────────────┤
│  证据平面    src/vela/evidence/        Stage-0~8：解包→解析→列存→QA │
├─────────────────────────────────────────────────────────────────────┤
│  查询平面    src/vela/query/           12 工具 + SQL 沙箱 + 护栏     │
├─────────────────────────────────────────────────────────────────────┤
│  推理平面    src/vela/agent/           七节点图 + 压缩 + 引用校验    │
├─────────────────────────────────────────────────────────────────────┤
│  证据链平面  src/vela/evidencepack/    Merkle 证据包 + 三级验证     │
├─────────────────────────────────────────────────────────────────────┤
│  模型网关    src/vela/gateway/         mock/火山引擎/OpenAI 兼容    │
├─────────────────────────────────────────────────────────────────────┤
│  可观测/评估  src/vela/obs/  src/vela/eval/  事件总线+指标+黄金评测  │
└─────────────────────────────────────────────────────────────────────┘
        入口：src/vela/cli.py（CLI）  src/vela/server/app.py（HTTP 服务）
```

约 7,100 行 Python（不含测试），61 个源文件，177 个单元/集成测试。

---

## 目录结构

```
vela-poc/
├── README.md                      本文件
├── pyproject.toml                 包定义（name=vela, CLI 入口 vela=vela.cli:main）
├── requirements.txt                必需依赖：duckdb / pyarrow / PyYAML / pytz / python-dotenv / openai
├── requirements-optional.txt        可选加速/服务依赖：xxhash / blake3 / fastapi / uvicorn / pytest
├── .env.example                    环境变量样例（含火山引擎方舟接入变量）
│
├── config/                        全部可调参数，业务代码不硬编码任何阈值
│   ├── pipeline.yaml               解包/发现/解析/时间/模板/写出/QA 全部阈值
│   ├── parsers.yaml                13 个日志格式解析器（正则+优先级）
│   ├── ota_phases.yaml             9 条阶段识别规则 + 15 个 UDS NRC 语义字典
│   ├── budget.yaml                 poc/production 双档预算（压缩/计量/护栏）
│   ├── llm.yaml                    模型网关：逻辑模型映射/供应商/脱敏规则/审计开关
│   └── skills/builtin.yaml         12 个内置诊断技能（触发条件+探针+关键词）
│
├── src/vela/
│   ├── cli.py                     统一 CLI：sim / build / query / agent / eval / evidence / serve / doctor
│   ├── config.py                  YAML 加载 + BudgetProfile + config_hash
│   ├── version.py                 版本号 + schema 版本 + canon 规则版本
│   │
│   ├── sim/                       仿真器：车队/场景/事件渲染/数据集生成
│   ├── evidence/                  证据平面：Stage-0~8 全流程
│   ├── query/                     查询平面：12 工具 + 护栏 + SQL 沙箱
│   ├── agent/                     推理平面：七节点图 + 压缩 + 技能 + 引用校验
│   ├── evidencepack/              证据链：构建器 + 三级验证器 + 快照双源解析
│   ├── gateway/                   模型网关：mock / 火山引擎 / OpenAI 兼容 / 脱敏 / 计量 / 审计
│   ├── obs/                       可观测：事件总线 + 指标
│   ├── eval/                      评估：黄金用例 + 评测执行器 + 报告渲染
│   ├── server/                    本地 HTTP 服务（FastAPI 优先，标准库兜底）
│   └── util/                      哈希 / ID / 文本规范化 / 时间 / JSONL
│
├── scripts/
│   ├── demo_end_to_end.py         一条命令跑通仿真→建库→诊断→验证全链路
│   └── bench.py                   建库吞吐 + 诊断延迟基准测量
│
├── tests/                         177 个用例，覆盖全部 10 个模块
│
└── docs/
    ├── MECHANISM_MAPPING.md       两份原始文档的机制 → 代码位置映射表
    ├── SCHEMA.md                  log_lines 等全部列式表结构说明
    ├── TOOLS.md                   12 个 Agent 工具的完整契约与示例
    ├── LLM_PRODUCTION.md          接入火山引擎方舟（生产级大模型）指引
    └── PRODUCTION_MIGRATION.md    POC → 生产平台的过渡路线图
```

---

## 核心概念速查

| 概念 | 一句话 | 代码位置 |
|---|---|---|
| **row_hash** | 每行日志的引用锚点：`H(原文 \| 文件路径 \| 行号)`，16 位十六进制 | `util/hashing.py` |
| **raw_hash / norm_hash** | 三级指纹之二：原始字节 BLAKE3-128 / 规范化后 xxh3-64（去重/聚类用） | `evidence/fingerprint.py` |
| **ts_confidence** | 时间置信度 0~1；WALL≈0.95，MONOTONIC≈0.8，DERIVED≈0.6，跳变/乱序会扣分 | `evidence/timeline.py` |
| **template_id** | MiniDrain 模板聚类 ID；`top_templates(rare)` 专门把低频模板顶到前面——根因常在那里 | `evidence/template.py` |
| **压缩痕迹（compression_trace）** | 告诉模型"哪些内容被折叠了、怎么取回"，而不是让模型在不知情下基于残缺证据下结论 | `agent/compress.py` |
| **row_hash 悬空引用（dangling citation）** | 报告引用了证据集里不存在/库里查不到的 row_hash——程序化校验，不信任模型自述 | `agent/citations.py` |
| **程序化历史规避** | 已执行过探针的技能从候选集**物理剔除**，不是"提示模型别选" | `agent/state.py::excluded_skills` |
| **证据包三级验证** | L0 自洽（仅需证据包）/ L1 库内（需 gold 库）/ L2 溯源（需原始压缩包重算字节指纹） | `evidencepack/verifier.py` |

---

## 配置说明（配置全部在 `config/`）

业务代码**不硬编码任何阈值**；改行为只改 YAML，不改代码。

### `budget.yaml` —— 预算与护栏（机制一 + 机制四）

```yaml
active_profile: poc          # 可用环境变量 VELA_PROFILE 覆盖
profiles:
  poc:                       # 缩小 20 倍，方便在小数据集上就能触发/观测各项机制
    compression:
      whitelist_cap_per_template: 8      # 白名单模板每模板最多保留几条
      rare_template_max_count: 5         # 出现 ≤5 次的模板整体豁免（根因常在此）
      template_quota_lines: 3            # 普通高频模板每类保留几条
    budget:
      round_evidence_tokens: 12000       # 单轮证据 token 预算
      round_llm_tokens: 8000             # 单轮大模型 token 预算（硬切断）
      max_rounds: 6
    guardrail:
      detail_fetch_hard_limit: 5000      # 单次明细拉取硬上限
      sql_max_rows: 2000
  production:                # 生产档：交底书原始量级
    ...
```

切换到生产量级：`export VELA_PROFILE=production` 或 `vela agent diagnose --profile production ...`。

### `parsers.yaml` —— 13 个日志格式解析器

覆盖：`iso_bracket_comp`（ISO+组件括号）、`iso_pid_tid`（PID/TID 结构化）、
`logcat_threadtime`（Android logcat）、`dmesg_monotonic`（内核单调时钟）、
`syslog_rfc3164`（BSD syslog）、`dlt_verbose`、`glog_style`、`json_line`、
`cn_bracket_level`（中文【错误】级别）、`kv_structured`（key=value）、
`short_nodate`、`uptime_relative`（纯 uptime，无墙钟）、`fallback_raw`（兜底）。

新增一种日志格式：在 `parsers.yaml` 加一条正则规则，无需改代码（`ParserRegistry` 是 YAML 驱动的）。

### `ota_phases.yaml` —— 阶段识别 + NRC 语义字典

9 条阶段规则（INIT/QUERY/DOWNLOAD/VERIFY/TRANSFER/FLASH/ACTIVATE/ROLLBACK/REPORT）+
15 个 UDS 否定响应码（0x10~0x93）的名称与排查提示，`error_code_lookup` 工具直接查这个字典。

### `skills/builtin.yaml` —— 12 个内置诊断技能

每个技能：`trigger`（触发条件）+ `summary`（一句话摘要）+ `probes`（探针工具与参数）+
`keywords`（检索关键词）+ `root_cause_label`（对应根因标签）。新增诊断经验：加一个技能条目
（YAML），不用改 Agent 代码——这就是"知识自增强闭环"机制的落地方式。

---

## 生产数据接入（替换仿真器）

系统从设计之初就把"仿真数据"和"生产数据"当作**同一个输入接口**的两种来源：

```bash
# 仿真数据（本仓库默认演示路径）
vela sim generate --out ./data/dataset
vela build ./data/dataset/OTA_xxx.zip ./workspace/xxx

# 生产数据 —— 完全一样的命令，换一个压缩包路径即可
vela build /path/to/real_vehicle_upload_package.zip ./workspace/real-case-001
```

**唯一约定**：压缩包根目录放一个 `package_meta.json`（可选，缺失则走推断兜底）：

```json
{
  "vin": "LSVxxxxxxxxxxxxx",
  "timezone": "Asia/Shanghai",
  "collected_at": "2026-07-20T11:15:00Z"
}
```

- `collected_at` 用于年份推断与"纯 monotonic 时间戳缺乏强锚点时"的兜底反推——
  务实建议：**真实生产环境应尽量提供**，否则退化为按压缩包内文件的时间戳反推（见
  `evidence/pipeline.py` 的 `ref_time` 计算与 `evidence/timeline.py` 的 `_anchor_base`）。
- 若压缩包内没有这个文件，13 个解析器 + `discover.py` 的编码探测（UTF-8/GB18030/UTF-16/Latin-1）
  会尽力从日志内容本身解析出时间与组件归属；`qa_report.json` 会如实报告解析成功率与时间置信度分布。
- 压缩包内部目录结构、文件命名、编码**不需要跟仿真器输出一致**——13 个解析器与组件归属规则
  （`pipeline.yaml` 的 `discover.component_rules`）按内容/路径特征匹配，不依赖固定目录树。

---

## 接入真实大模型（火山引擎方舟）

默认 `VELA_LLM_PROVIDER=mock`（确定性规则引擎，零外部依赖，CI/演示/评测全部用它）。
生产切换**只改环境变量，不改一行业务代码**：

```bash
cp .env.example .env
# 编辑 .env：
#   VELA_LLM_PROVIDER=volcengine
#   VELA_ARK_API_KEY=<你的方舟 API Key>
#   VELA_ARK_MODEL=ep-xxxxxxxxxxxx        # 推理接入点 ID，或直接填模型名
#   VELA_ARK_MODEL_FALLBACK=ep-yyyyyyyy   # 可选：主接入点故障时自动降级

source .env
vela agent diagnose --db ./workspace/demo/gold/analysis.duckdb --provider volcengine
```

网关自动完成：出站脱敏（VIN/GPS/手机号/IMEI/身份证/邮箱/IP）→ 三级 token 预算硬切断
（轮次/会话/租户）→ 调用（超时+重试+降级链）→ 全量审计（JSONL，默认只落 prompt 哈希不落明文）。

也支持任意 OpenAI 兼容端点（vLLM / One-API / 自建网关）：把 `VELA_LLM_PROVIDER` 设为
`openai_compat`，配置 `VELA_OPENAI_BASE_URL` / `VELA_OPENAI_API_KEY` / `VELA_OPENAI_MODEL` 即可。

详见 [`docs/LLM_PRODUCTION.md`](docs/LLM_PRODUCTION.md)。

---

## 评测体系

```bash
vela sim generate --out ./data/dataset          # 若尚未生成
python -m vela.cli eval run --dataset ./data/dataset --workspace ./workspace/eval
```

评测口径的核心纪律：**仿真器写入的 sidecar 真值（`*.truth.json`）永远不进 zip 包**，
Agent 只能通过 12 个工具查询列式库——评测时才拿真值来对答案，杜绝答案泄漏
（`tests/test_eval.py::test_truth_narrative_never_reaches_agent_context` 专门校验这一点）。

6 项核心指标与目标线（`src/vela/eval/report.py` 的 `_TARGETS`）：

| 指标 | 目标 | 含义 |
|---|---|---|
| `top1_root_cause_accuracy` | ≥ 0.80 | 故障场景 Top-1 根因命中率 |
| `healthy_specificity` | ≥ 1.00 | 健康会话正确识别为"无故障"的比例 |
| `false_positive_rate` | ≤ 0.00 | 健康会话被误判出故障的比例 |
| `dangling_citation_rate` | ≤ 0.015 | 报告引用中悬空（不可验证）引用的比例 |
| `illegal_skill_reselect_total` | = 0 | 模型试图重选已剔除技能的次数（应恒为 0） |
| `evidence_pack_verify_pass` | ≥ 1.00 | 证据包 L0/L1/L2 三级验证全部通过的比例 |

当前 10 场景实测：6 项全部达标（Top-1 = 1.0，见 `workspace/eval/report/eval_report.md`）。

---

## 测试

```bash
pytest tests/ -q                              # 全部 177 个用例，约 15 秒
pytest tests/test_agent.py -q                 # 只跑推理平面（压缩/引用校验/七节点图端到端）
pytest tests/ -k "citation" -q                # 按关键词过滤
pytest tests/ -m determinism -q               # 确定性回归标记（pyproject.toml 已注册）
```

测试覆盖：工具层哈希/ID/文本规范化确定性（25）、仿真器 VIN 校验与逐字节可复现性（12）、
证据平面安全解包/解析/QA（24）、查询平面 12 工具+护栏+SQL 沙箱（27）、模型网关脱敏/预算/
mock 契约/火山引擎适配器（15）、推理平面技能召回/压缩分级/引用校验/端到端诊断（23）、
证据包三级验证/快照双源解析（16）、可观测/配置（12）、评估口径与防泄漏（9）、
CLI/服务全路径（14，含两个真实发现并修复的 CLI 端到端缺陷的回归用例）。

---

## CLI 全部命令

```bash
vela doctor                                          # 环境自检：配置文件/依赖/预算档位
vela sim generate --out DIR [--scenarios S1 S2 ...] [--list]
vela build ARCHIVE WORKSPACE [--keep-raw] [--quiet]
vela query --db DB --tool NAME [--args '{"k":"v"}'] [--limit N] [--list]
vela agent diagnose --db DB [--workspace DIR] [--provider mock|volcengine|openai_compat]
                     [--profile poc|production] [--question "..."] [--max-rounds N] [--json-out FILE]
vela eval run --dataset DIR --workspace DIR --out DIR [--provider ...] [--profile ...]
vela evidence verify --pack FILE.json [--db DB] [--archive ARCHIVE.zip]
vela serve --db DB [--workspace DIR] [--host 127.0.0.1] [--port 8848]
```

---

## 向生产平台过渡

POC 的每一层都按"生产可替换"设计，具体路线图见
[`docs/PRODUCTION_MIGRATION.md`](docs/PRODUCTION_MIGRATION.md)，摘要：

| 层 | POC 实现 | 生产替换方向 |
|---|---|---|
| 列式库 | DuckDB 单机文件 | ClickHouse / StarRocks（Schema 与 SQL 基本兼容） |
| 向量召回 | 本地哈希向量（`agent/skills.py::embed_local`） | 火山引擎方舟 `/embeddings` + 向量库；接口已预留 |
| 大模型 | mock / 火山引擎方舟 | 生产直接切 `VELA_LLM_PROVIDER=volcengine`，零代码改动 |
| 事件总线 | JSONL 文件 | Kafka / Pulsar；`obs/events.py` 的 `Event` 结构直接映射 |
| 会话存储 | 本地 JSON 检查点 | Redis / 数据库；`agent/checkpoint.py` 接口不变 |
| 服务 | FastAPI 单进程 | 加鉴权/多租户网关；路由已在 `server/app.py` 定义 |

---

## 已知局限（POC 诚实声明）

- **单机单进程**：DuckDB 为单文件数据库，未做分布式；生产量级（数亿行/天）需迁移列式库。
- **技能库仅 12 个**：覆盖交底书列举的主要故障模式；新故障模式需要新增技能条目（配置层面，非代码）。
- **monotonic 时间锚点的兜底精度有限**：完全没有强锚点（同行双时间戳）时，`_anchor_base` 退化为
  "文件 mtime 前 1 小时"的粗粒度假设（`evidence/timeline.py`），量级正确但不追求分钟级精度；
  生产环境应尽量提供 `package_meta.json` 的 `collected_at` 或车端预写时间锚点行。
- **中文分词是轻量规则**（中文 bigram + 英文词切分，`evidence/fingerprint.py::tokenize_for_search`），
  非成熟分词器；FTS 检索在中文长句上的召回率弱于工业级方案。
- **mock 大模型是确定性规则引擎**，不是真实 LLM 能力的替代——它的价值在于让整条链路
  （压缩、护栏、引用校验、评测）可以离线、确定性地跑通与回归，真实推理质量取决于接入的模型。

---

## 常见问题排查

**Q: `vela build` 报 `duckdb.duckdb.CatalogException` 或类似 SQL 错误？**
先跑 `vela doctor` 确认 `config_hash` 与依赖版本；再检查 `workspace/qa/qa_report.json` 里
`checks` 列表的 `ok`/`detail` 字段（不是 `passed`——这曾是一个真实存在过的 CLI bug，见
`tests/test_cli_and_server.py::test_cli_build_command_produces_parseable_qa_json`）。

**Q: 交付/复制文件后打开报错？**
优先直接核查目标目录里文件是否真实存在（`ls`/`os.listdir` 等独立于写入动作的复核），
而不是假设是操作问题——参见本项目自身在开发过程中就踩过并修复的同类问题。

**Q: 火山引擎调用报 401/403？**
检查 `VELA_ARK_API_KEY` 是否正确导出到当前 shell（`source .env` 而非只 `cat .env`），
以及 `VELA_ARK_MODEL` 填的是推理接入点 ID（`ep-xxxxxxxx`）而非模型族名称。

**Q: 想看某一次诊断的完整决策轨迹？**
`--json-out session.json` 落盘完整 `DiagnosisResult`（含每轮 `tool_calls`/`compression_trace`/
`llm_tokens`）；`workspace/*/obs/events.jsonl` 是结构化事件流水（含 MILESTONE/ALERT 分级）；
`workspace/*/obs/llm_audit.jsonl` 是全量模型调用审计（默认只落 prompt 哈希，不落明文）。
