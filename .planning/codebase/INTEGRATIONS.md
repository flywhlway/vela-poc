# External Integrations

**Analysis Date:** 2026-07-30

## APIs & External Services

**大模型（LLM）推理：**
- 火山引擎方舟（Volcengine Ark） — 生产首选大模型供应商，OpenAI 兼容协议
  - SDK/Client: 无第三方 SDK，纯标准库 `urllib.request` 实现于 `src/vela/gateway/openai_compat.py`；`src/vela/gateway/volcengine.py` 仅做语义别名封装（继承 `OpenAICompatProvider`）
  - Auth: `VELA_ARK_API_KEY`（Bearer token），端点 `VELA_ARK_BASE_URL`（默认 `https://ark.cn-beijing.volces.com/api/v3`）
  - 模型标识: `VELA_ARK_MODEL`（推理接入点 ID `ep-xxxxxxxx` 或模型名），可选按逻辑模型细分（`VELA_ARK_MODEL_PLANNER` 等，见 `src/vela/gateway/openai_compat.py::models_for`）
  - 降级链: `VELA_ARK_MODEL_FALLBACK` → `VELA_OPENAI_MODEL`（`config/llm.yaml` `providers.volcengine.fallback_chain`）
  - 向量接口: `/embeddings`，模型由 `VELA_ARK_EMBED_MODEL` 指定（`OpenAICompatProvider.embed`），当前未接入生产向量库，仅接口预留
  - 文档: `docs/LLM_PRODUCTION.md`

- 任意 OpenAI 兼容端点（`openai_compat`，覆盖 vLLM / One-API / 自建网关 / OpenAI 本体）
  - SDK/Client: 同上，`src/vela/gateway/openai_compat.py::OpenAICompatProvider`
  - Auth: `VELA_OPENAI_API_KEY`，端点 `VELA_OPENAI_BASE_URL`
  - 模型: `VELA_OPENAI_MODEL`

- Mock 供应商（默认，`VELA_LLM_PROVIDER=mock`）
  - 实现: `src/vela/gateway/mock.py::MockProvider`
  - 确定性规则引擎，零外部依赖，CI/演示/评测默认使用；支持故障注入开关 `inject_hallucinated_citations` 用于验证引用校验机制（`config/llm.yaml` `providers.mock`）

**统一网关抽象：**
- `src/vela/gateway/base.py::LLMGateway` / `Provider` — 所有 LLM 流量的唯一出口，切换供应商只改 `VELA_LLM_PROVIDER` 环境变量，业务代码零改动
- `build_gateway()` 按 `config/llm.yaml` 的 `providers.<name>.kind` 分发到 `mock` 或 `openai_compatible` 实现
- 网络请求特性（`OpenAICompatProvider._post`）: 超时 `timeout_s`（默认 120s），重试 `max_retries`（默认 2 次，指数退避 `retry_backoff_s`），4xx（400/401/403/404）不重试直接抛出，其余异常视为网络类错误可重试

## Data Storage

**Databases:**
- DuckDB（单文件、进程内嵌入式列式数据库，无独立服务端）
  - 连接方式: `duckdb.connect(path)`，出现于 `src/vela/query/api.py::LogQueryAPI.__init__`（只读模式 `read_only=True` 供查询平面）、`src/vela/evidence/pipeline.py`（Stage-6/7 写库，路径 `<workspace>/gold/analysis.duckdb`）、`src/vela/cli.py::cmd_evidence`（证据包 L1 库内验证）
  - Schema: 53 列 `log_lines` 表结构，详见 `docs/SCHEMA.md`
  - 无远程数据库/连接字符串/密码；纯本地文件路径

**File Storage:**
- 本地文件系统，无对象存储（S3/OSS 等）集成
  - Parquet 列式文件 — 由 `pyarrow` 写出，evidence pipeline 的中间产物
  - 原始日志压缩包（`.zip`）— 输入格式，`src/vela/evidence/unpack.py` 安全解包
  - JSON/JSONL — 会话检查点（`src/vela/agent/checkpoint.py::CheckpointStore`，原子写 tmp+`os.replace`）、事件流（`src/vela/obs/events.py`）、模型调用审计（`src/vela/gateway/audit.py`）、证据包（`evidencepack/builder.py`）

**Caching:**
- 无独立缓存服务；进程内使用 `functools.lru_cache` 缓存 YAML 配置加载（`src/vela/config.py::load_yaml`）

## Authentication & Identity

**Auth Provider:**
- 无用户身份认证/登录系统（POC 单机单进程，无多租户 UI）
- "租户"概念仅用于查询护栏的强制谓词隔离：`VELA_TENANT` 环境变量（默认 `demo-tenant`），见 `src/vela/config.py::tenant_id`，用于 SQL 沙箱层面的数据隔离而非用户认证
- HTTP 服务（`src/vela/server/app.py`）当前**无鉴权中间件**；`docs/PRODUCTION_MIGRATION.md` 建议生产环境"加鉴权/多租户网关"

## Monitoring & Observability

**Error Tracking:**
- 无第三方错误追踪服务（Sentry 等）；异常通过标准 Python 异常处理 + 事件总线记录

**Logs / 事件系统:**
- 自研结构化事件总线 `src/vela/obs/events.py::EventBus`
  - 双通道设计：`PROGRESS`（高频可丢弃）、`MILESTONE`/`ALERT`（低频必达，同步落盘 + fsync）
  - 落盘路径: `<workspace>/obs/events.jsonl`，事件带单调递增 `event_id` 支持断线续传
- 指标: `src/vela/obs/metrics.py`
- 模型调用审计: `<workspace>/obs/llm_audit.jsonl`（`src/vela/gateway/audit.py::Auditor`），默认只落 `prompt_sha256` 摘要哈希，不落明文 prompt/completion（`config/llm.yaml` `audit.log_prompt=false`）

## CI/CD & Deployment

**Hosting:**
- 无云平台部署配置检测到（无 Dockerfile、无 k8s manifests、无 Terraform）
- 本地/裸机部署：`pip install` 后 `vela` CLI 或 `vela serve` 直接运行

**CI Pipeline:**
- 未检测到（无 `.github/workflows/`、`.gitlab-ci.yml`、`.circleci/` 等目录）
- 测试通过 `Makefile` `test`/`test-fast` 目标或 `pytest tests/ -q` 手动/脚本触发（`run_all.sh` 第 6 步）

## Environment Configuration

**Required env vars（均可选，未设置时走 `config/*.yaml` 默认值）：**
- `VELA_LLM_PROVIDER`（默认 `mock`）
- `VELA_ARK_API_KEY` / `VELA_ARK_BASE_URL` / `VELA_ARK_MODEL` / `VELA_ARK_MODEL_FALLBACK` / `VELA_ARK_EMBED_MODEL`
- `VELA_OPENAI_API_KEY` / `VELA_OPENAI_BASE_URL` / `VELA_OPENAI_MODEL`
- `VELA_WORKSPACE`（默认 `./workspace`）
- `VELA_PROFILE`（`poc|production`，默认 `poc`）
- `VELA_TENANT`（默认 `demo-tenant`）
- `VELA_LOG_LEVEL`（默认 `INFO`）
- `PYTHONHASHSEED=0`（确定性要求）
- `VELA_CONFIG_DIR`（覆盖 `config/` 目录）

**Secrets location:**
- `.env`（本地文件，被 `.gitignore` 排除；`.env.example` 提交到仓库作为模板，不含真实密钥）
- 无密钥管理服务集成（Vault/AWS Secrets Manager/KMS 等）

## Webhooks & Callbacks

**Incoming:**
- 无 Webhook 接收端点；HTTP 服务仅提供 REST + SSE 风格路由：`GET /health /tools /describe /events /metrics`，`POST /call /diagnose`（`src/vela/server/app.py::_handle`）
- 服务实现双轨：FastAPI 可用则用（自动生成 OpenAPI 文档于 `/docs`），否则自动降级到标准库 `http.server.ThreadingHTTPServer`（零第三方依赖兜底）

**Outgoing:**
- 仅有的出站网络调用是 LLM 供应商的 Chat Completions / Embeddings API（见上文"APIs & External Services"），通过 `urllib.request` 发起 POST 请求，出站前统一经过 `src/vela/gateway/redact.py::Redactor` 脱敏（覆盖 VIN/GPS/手机号/IMEI/身份证/邮箱/IPv4，规则见 `config/llm.yaml` `redaction.rules`）
- 无其他出站集成（无短信/邮件/消息推送/第三方通知服务）

---

*Integration audit: 2026-07-30*
