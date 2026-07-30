# POC → 生产平台过渡路线图

本文档回答："这个 POC 里哪些部分可以直接进生产，哪些需要替换，替换成本大概多大。"
每一层都按"可插拔"设计，替换点集中且接口清晰。

---

## 总览：不需要改的部分（可直接进生产）

| 模块 | 原因 |
|---|---|
| `evidence/models.py`（Schema） | 与具体存储引擎无关，ClickHouse/StarRocks 建表可直接照搬列定义 |
| `evidence/fingerprint.py`（三级指纹） | 纯函数，语言无关的哈希算法（BLAKE3/xxh3），迁移零成本 |
| `evidence/timeline.py`（时间归一） | 纯计算逻辑，与存储层解耦 |
| `evidence/template.py`（MiniDrain） | 纯规则算法，性能已验证（单核 3,000+ 行/秒） |
| `query/guard.py`（护栏与 SQL 沙箱） | 逻辑与具体 SQL 引擎解耦（略调整方言即可） |
| `agent/citations.py`（引用校验） | 纯规则校验，与推理引擎无关 |
| `agent/compress.py`（预算压缩） | 纯规则分级，配置驱动 |
| `gateway/redact.py` / `budget.py` / `audit.py` | 纯规则/纯计量，无外部依赖 |
| `config/*.yaml` | 生产可直接复用，按需调阈值 |

---

## 分层替换指南

### 1. 列式存储：DuckDB → ClickHouse / StarRocks

**现状**：`evidence/writer.py::ShardWriter` 写 Bronze Parquet，`evidence/gold.py::build`
用 DuckDB SQL 建 Silver/Gold 表 + 索引 + 视图 + FTS。

**替换成本：中**。DuckDB 的 SQL 方言与 ClickHouse/StarRocks 高度相似（都是 MPP 风格
分析型 SQL），主要改动点：
- `writer.py::SILVER_SQL` 里的窗口函数（`row_number() OVER`）语法基本通用
- FTS 索引换成 ClickHouse 的 `ngrambf_v1`/`tokenbf_v1` 或 StarRocks 的倒排索引
- `query/api.py::LogQueryAPI._q` 的连接层需要换成对应的 Python 客户端
  （`clickhouse-driver` / `pymysql` 兼容层），但 `_where`/`_match_condition` 等
  SQL 拼装逻辑基本不用动（都是标准 SQL）

**不建议**：迁移前先跑 `scripts/bench.py` 建立当前吞吐基线，迁移后对比，
避免"分布式了但单条查询延迟反而上升"的陷阱（DuckDB 单机场景下的低延迟优势
在千万级以下数据量时很难被分布式方案超越）。

### 2. 向量召回：本地哈希向量 → 方舟 Embeddings + 向量库

**现状**：`agent/skills.py::embed_local` 是确定性哈希向量（字符 n-gram 哈希 + 余弦），
零外部依赖，12 个技能量级下完全够用。

**替换成本：低**。`gateway/openai_compat.py::OpenAICompatProvider.embed()` 已实现
`/embeddings` 端点调用；改动范围仅 `SkillRegistry.__init__` 里
`self._vec = {s["id"]: embed_local(...)}` 一行，换成调用网关的 `embed()` 并选一个
向量库（FAISS 单机版起步足够，技能规模到千级再上 Milvus/Qdrant）。

**何时值得做**：技能库规模超过 ~100 个、且技能描述语义相近（哈希向量在语义细微
差别上的区分度不如真实 embedding）时。12 个技能的当前规模下，`SkillRegistry.retrieve`
的混合召回（稠密 ∪ 词面）已能保证 100% 正确技能命中率（见评测报告）。

### 3. 大模型：mock → 火山引擎方舟

**替换成本：零代码改动**。见 [`LLM_PRODUCTION.md`](LLM_PRODUCTION.md)——
只改环境变量。这是本系统"网关统一出口"设计从一开始就要保证的能力。

### 4. 事件总线：JSONL 文件 → Kafka / Pulsar

**现状**：`obs/events.py::EventBus` 关键事件（MILESTONE/ALERT）同步落盘 JSONL + fsync，
进度事件（PROGRESS）可选落盘。

**替换成本：低**。`Event` dataclass 已经是"结构化事件"的标准形态
（`event_id`/`ts_utc`/`session_id`/`severity`/`kind`/`round_no`/`payload`），
`EventBus.emit()` 内部的 `append_jsonl` 调用替换为 Kafka producer 即可，
订阅者接口（`subscribe(fn)`）不用变。`since(last_event_id)` 的断线重连语义
直接对应 Kafka 的 offset 语义。

### 5. 会话检查点：本地 JSON → Redis / 数据库

**现状**：`agent/checkpoint.py::CheckpointStore` 每轮结束原子写一个 JSON 文件
（`SessionState.to_dict()` / `from_dict()` 互逆）。

**替换成本：低**。`save`/`load`/`exists` 三个方法签名不变，内部实现换成
Redis `SET`/`GET` 或数据库 upsert 即可；`SessionState` 本身已是可 JSON 序列化的
纯数据结构。

### 6. HTTP 服务：单进程 FastAPI → 多副本 + 鉴权网关

**现状**：`server/app.py::build_app` 提供 `/health` `/tools` `/describe` `/call`
`/diagnose` `/events` `/metrics` 六类路由；FastAPI 缺失时自动降级标准库
`http.server`（保证"任何装了 Python 的机器都能跑"这一 POC 诉求）。

**替换成本：中**。路由语义已经定义清楚，生产化主要是加：
- 鉴权中间件（当前 `_STATE` 是进程内全局单库单租户假设，多租户需要按请求
  路由到对应租户的库连接池）
- 反向代理 + 多副本（`LogQueryAPI` 的 DuckDB 连接目前是单进程内单连接，
  需要评估 DuckDB 的多进程只读并发访问模型，或迁移到步骤 1 的分布式存储后
  天然支持多副本无状态服务）

### 7. 知识自增强闭环：候选 JSONL → 复核工作流

**现状**：`agent/graph.py::node_distill` 产出的技能候选写入
`workspace/knowledge/candidates.jsonl`（`status: pending_review`），
**不自动生效**——这是刻意设计（新技能未经复核直接影响后续诊断判断存在风险）。

**替换成本：中**。需要补一个人工复核 UI/流程：从 `candidates.jsonl` 读取候选，
人工确认后 `merge` 进 `config/skills/builtin.yaml`（格式已完全一致，字段直接对应）。

---

## 迁移优先级建议（若要分阶段做）

1. **第一阶段（零风险）**：直接接入真实大模型（步骤 3），验证真实推理质量；
   继续用 DuckDB + 本地哈希向量，因为在中小规模数据量下它们本就不是瓶颈。
2. **第二阶段（数据量驱动）**：当单日日志量超过千万行级、DuckDB 单机 I/O 成为
   建库吞吐瓶颈时，做步骤 1（列式存储迁移）。用 `scripts/bench.py` 的建库吞吐
   指标作为触发迁移的量化依据，而不是"感觉应该上大数据组件"的直觉决策。
3. **第三阶段（运营规模驱动）**：当需要多团队/多产线共用一套诊断平台时，
   做步骤 6（服务多副本化）+ 步骤 7（知识复核工作流），把"人工经验持续沉淀"
   变成真正的组织能力而不是单机 POC 的副产品。
