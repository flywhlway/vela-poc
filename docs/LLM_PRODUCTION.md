# 接入生产级大模型（优先适配火山引擎方舟）

## 为什么默认是 mock

`config/llm.yaml` 的 `active: mock` 不是"占位符"，而是一个**确定性规则引擎**：
解析提示词中嵌入的 `[[VELA_STATE]]{json}[[/VELA_STATE]]` 结构化状态块，按与真实模型
完全相同的契约（同样的 system prompt、同样的 JSON 输出格式）做规则化推理。这意味着：

- 整条 Agent 链路（预算压缩、护栏、引用校验、报告生成、知识蒸馏）在**无任何外部依赖**时
  即可完整跑通与回归测试（`tests/` 里绝大多数用例基于 mock，几秒钟跑完，不消耗任何
  真实 API 配额）。新增的 `realllm` 标记用例默认被 `pyproject.toml` 的
  `addopts = "... -m 'not realllm'"` 排除，因此 `make test` / 默认 pytest **仍然零 API
  调用、零配额消耗**；只有显式 `pytest -m realllm` 才会打真实端点。
- mock 与真实供应商共享同一份提示词模板（`gateway/prompts.py`），切换供应商时
  **提示词不变**，只是"谁来读懂这段结构化状态"变了。
- `inject_hallucinated_citations` 开关可以让 mock 故意伪造一个不存在的 `row_hash`，
  用来验证"系统级引用校验"这道安全网真的能抓住模型幻觉——这是校验器的自测能力，
  不依赖真实模型出错的偶然性。

## 一、火山引擎方舟（Volcengine Ark）接入步骤

### 1. 准备工作

1. 登录 [火山引擎控制台](https://console.volcengine.com/ark)，开通"方舟大模型服务"
2. 创建推理接入点（Endpoint），选择需要的基础模型，记下接入点 ID（形如 `ep-xxxx`）
3. 生成 API Key

### 2. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`：

```bash
VELA_LLM_PROVIDER=volcengine
VELA_ARK_API_KEY=<你的 API Key>
# 方舟两类合法入口（须择一；均以 /api/v3 或 /api/plan/v3 结尾）：
VELA_ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
# VELA_ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/plan/v3
VELA_ARK_MODEL=ep-xxxx                                        # 你的推理接入点 ID
```

`.env` 由 `src/vela/config.py` 在模块导入时自动加载一次（`override=False`，已存在的
进程环境变量恒定优先）。任意 CLI 子命令与 `pytest` 均自动生效，**无需 `source` 也无需
手工 `export`**。临时覆盖走 shell 前置赋值，例如
`VELA_LLM_PROVIDER=volcengine vela agent diagnose ...`。

```bash
vela doctor        # 确认本地配置与连通性（见下一节）
```

### 环境自检（`vela doctor`）

`vela doctor` 做四项连通性自检（在本地硬检查通过之后）：

1. 端点可达
2. 鉴权有效
3. 模型可用
4. 四个逻辑模型（`planner` / `verifier` / `reporter` / `distiller`）映射完整

探测时机按 provider **自动判定**：`mock` 跳过全部网络探测；`volcengine` /
`openai_compat` 自动联网。可用双向强制覆盖：

| 参数 | 作用 |
|------|------|
| `--offline` | 强制跳过网络探测（即使 provider 非 mock） |
| `--online` | 强制联网探测（即使 provider 为 mock） |
| `--json` | 结构化 JSON 输出（stdout 可被 `json.loads` 直接消费） |

`--offline` 与 `--online` 互斥，同时传入返回码 `2`。

**退出码语义（有意偏离「失败即非零」惯例）：**

- 本地硬错误（配置缺失 / 必需依赖缺失 / `.env` 形态错误，例如 `base_url` 不是
  `/api/v3` 或 `/api/plan/v3` 结尾）→ 返回 `1`
- 连通性四项任一失败 → 人读输出显著标 ❌，但返回 `0`，以免一次限流或临时断网中断
  `run_all.sh` 的整条链路

```bash
vela doctor --json
```

`--json` 顶层键包括：`vela_version` / `python` / `config_dir` / `config_hash` /
`provider` / `probed` / `dotenv` / `checks` / `checks_passed` / `local_ok`。
其中 `dotenv` 只含键名（`path` / `loaded` / `keys` / `shadowed`），永不含值。

**掩码约定：** API key 在人读与 `--json` 两种输出形态下均只显示前 4 后 4；
`base_url` 与 `ep-xxxx` 接入点 ID 明文展示，以便对照排查。

### 3. 按逻辑模型分别指定接入点（可选，更精细的成本/质量控制）

系统内部有 4 个"逻辑模型角色"：`planner`（规划下钻）/ `verifier`（引用校验）/
`reporter`（报告撰写）/ `distiller`（知识蒸馏），可以分别接不同的物理接入点
（例如 planner 用小模型省成本、reporter 用大模型保证报告质量）：

```bash
VELA_ARK_MODEL_PLANNER=ep-xxxx-lite
VELA_ARK_MODEL_VERIFIER=ep-xxxx-lite
VELA_ARK_MODEL_REPORTER=ep-xxxx-pro
VELA_ARK_MODEL_DISTILLER=ep-xxxx-lite
```

未单独指定的逻辑模型会退回 `VELA_ARK_MODEL`（见 `gateway/openai_compat.py::models_for`
的解析顺序：逻辑模型专属变量 → 通用变量 → `model_default` → 降级链）。

### 4. 故障降级链（可选）

```bash
VELA_ARK_MODEL_FALLBACK=ep-yyyy-backup    # 主接入点全部重试耗尽后自动切换
```

`config/llm.yaml` 的 `providers.volcengine.timeout_s` 与 `max_retries` 分别映射到
openai SDK 客户端的 `timeout` 与 `max_retries`；退避策略由 SDK 内置且不可配，
`retry_backoff_s` 已随 SDK 化从 `config/llm.yaml` 删除。`chat_path` / `embed_path`
同样删除，请求路径由 SDK 固定，因此 `base_url` **必须含版本前缀**（方舟为 `/api/v3` 或 `/api/plan/v3`）。
全部接入点都失败才会抛出 `LLMError`。

### 5. 运行

```bash
vela agent diagnose --db workspace/demo/gold/analysis.duckdb --provider volcengine
# 或不传 --provider，直接让 VELA_LLM_PROVIDER 环境变量生效
```

### 真实环境验收（`pytest -m realllm`）

固化 ENV-02 的可复现验收（会产生**真实付费调用**）：

```bash
PYTHONPATH=src VELA_CONFIG_DIR=config \
  VELA_LLM_PROVIDER=volcengine \
  .venv/bin/python3 -m pytest -m realllm -q
```

- 缺 `VELA_ARK_API_KEY` / `VELA_ARK_MODEL` 时自动 `pytest.skip`（不是 fail）
- 断言范围只覆盖「链路跑完 + 报告非空 + 含至少一个 `[[EV:row_hash]]` 引用」
- **不断言**诊断结论正确（ROADMAP 成功判据 2 只要求链路通）
- 默认 `make test` / `pytest tests/` 因 `addopts` 排除 `realllm`，不会触发本用例

### 6. 向量检索接入（可选，替换本地哈希向量）

`agent/skills.py::embed_local` 目前用确定性哈希向量做技能宽召回的稠密检索路。
生产切换到方舟 embeddings：

```bash
VELA_ARK_EMBED_MODEL=<向量模型的接入点 ID>
```

`gateway/openai_compat.py::OpenAICompatProvider.embed(texts, model=None)` 已实现该端点
的调用；`SkillRegistry` 目前调用的是本地 `embed_local`，生产化时把这一处替换为
`gateway.embed()` 调用即可（接口签名一致，改动范围小——详见 `PRODUCTION_MIGRATION.md`）。

---

## 二、任意 OpenAI 兼容端点（vLLM / One-API / 自建网关）

同一套 `OpenAICompatProvider` 实现，只是换一组环境变量：

```bash
VELA_LLM_PROVIDER=openai_compat
VELA_OPENAI_API_KEY=<你的 key>
VELA_OPENAI_BASE_URL=http://localhost:8000/v1     # 例如自建 vLLM 服务
VELA_OPENAI_MODEL=<模型名或部署名>
```

`base_url` 同样必须含版本前缀（OpenAI 兼容端点通常为 `/v1`；方舟为 `/api/v3` 或 `/api/plan/v3`）。

---

## 三、出站脱敏（默认开启，不需要额外配置）

任何通过网关发出的 prompt，在计量与发送之前都会先过 `gateway/redact.py::Redactor`：

| 规则 | 匹配 | 替换 |
|---|---|---|
| `vin` | 17 位车架号 | 掩码（保留后 4 位 + 前缀哈希，`util/textutil.py::mask_vin`） |
| `gps` | 经纬度字段 | `<GEO>` |
| `phone` | 中国大陆手机号 | `<PHONE>` |
| `imei` | IMEI | `imei=<IMEI>` |
| `idcard` | 18 位身份证号 | `<IDCARD>` |
| `email` | 邮箱 | `<EMAIL>` |
| `ipv4` | IPv4 地址 | `<IPV4>` |

规则定义在 `config/llm.yaml` 的 `redaction.rules`，纯正则、可按需增删，无需改代码。

## 四、审计（默认开启，默认不落明文）

`config/llm.yaml` 的 `audit` 段：

```yaml
audit:
  enabled: true
  log_prompt: false        # 生产默认不落全量 prompt
  log_prompt_hash: true    # 只落 SHA-256 哈希，供事后比对而不泄漏内容
```

审计记录落于 `workspace/*/obs/llm_audit.jsonl`，含 `session_id`/`round_no`/
`logical_model`/`physical_model`/`provider`/`ok`/`prompt_tokens`/`completion_tokens`/
`latency_ms`/`redaction_hits`/`prompt_sha256`。若需要落全量明文用于调试，
临时设 `log_prompt: true`，**生产环境不建议长期开启**（会在审计日志里保留完整对话内容）。

## 五、三级 Token 预算硬切断

即使切到真实大模型，`gateway/budget.py::TokenLedger` 依然按 `config/budget.yaml` 的
`round_llm_tokens`/`session_llm_tokens` 做硬切断——超限直接抛 `BudgetExceeded`，
Agent 据此收敛为"证据不足以支撑结论"而不是静默截断或无限重试烧穿配额。
生产量级建议切到 `production` 档位：`export VELA_PROFILE=production`。
