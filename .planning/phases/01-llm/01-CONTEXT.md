# Phase 1: 真实 LLM 环境就绪 - Context

**Gathered:** 2026-07-31
**Status:** Ready for planning

<domain>
## Phase Boundary

打通火山引擎方舟真实环境的「可用 + 可自检」：`.env` 自动加载（ENV-01）、`VELA_LLM_PROVIDER=volcengine` 端到端跑通并产出带 `[[EV:row_hash]]` 引用的报告（ENV-02）、`vela doctor` 前置暴露环境与配置问题（ENV-03/04）。

**本阶段额外纳入（用户于本次讨论中决定，见 D-03/D-04）**：把 `gateway/openai_compat.py` 的手写 urllib HTTP 层替换为 openai 官方 SDK。它不是 ENV-01~04 的字面要求，但是 ENV-02/ENV-03 的直接实现手段——doctor 的鉴权与模型可用性探测需要可靠的异常分类，手写 HTTP 层无法提供。

**明确不做**：不触碰任何推理逻辑、指标口径、评测闸门、编排行为、技能库——那些分属 Phase 2~6。

</domain>

<decisions>
## Implementation Decisions

### 项目级约束变更（⚠️ 影响全部后续阶段）

- **D-01:** **「依赖最小化」纪律作废。** 新纪律：能用成熟三方开源库解决的，一律不手写实现。这是**项目级永久变更**，非本阶段特例，Phase 2~6 同样适用（如 Phase 2 的置信区间可直接用 numpy/scipy，无需再逐个报批）。
  - **必须同步改写三处**（属于本阶段交付物）：
    - `.planning/REQUIREMENTS.md:21` ENV-01 中的「stdlib 实现，不新增运行期依赖」
    - `.planning/PROJECT.md:88` Constraints 中的「运行期依赖仅 duckdb / pyarrow / PyYAML / pytz — 依赖最小化是既定纪律，新增依赖前先评估 stdlib 可行性」
    - `AGENTS.md` 代码约定中的同一条
    - 建议一并更新 `.planning/codebase/STACK.md` 的依赖清单（非硬性）
- **D-02:** **其余架构铁律全部保留，不得借本次变更松绑**：本地优先（不引入必须联网或依赖外部服务才能跑通主链路的改动）、单线程单进程、查询唯一收口（`LogQueryAPI.call()`）、配置驱动、图节点即方法、不使用 `logging` 模块、出站数据必经 `gateway/redact.py` 脱敏、禁止提交 `.env` 及任何凭证。三方库只要是纯本地可安装包（python-dotenv / openai SDK 都是）就与这些不冲突。
- **D-03:** 本阶段新增两个**必需依赖**（写入 `requirements.txt` 与 `pyproject.toml` `dependencies`，不进可选组）：`python-dotenv`、`openai`。理由：`.env` 加载失败即 ENV-01 失败，不应有静默降级路径；openai SDK 缺失时 volcengine provider 本就无法工作，不如安装时即报错。
- **D-04:** `gateway/openai_compat.py::OpenAICompatProvider` 用 openai 官方 SDK 重写（火山方舟官方推荐接入方式，完全 OpenAI 兼容）。重试 / 超时 / 错误分类交给 SDK；doctor 的四项自检结论直接由 SDK 异常类型判定，不再解析 HTTP 状态码。

### `.env` 加载器

- **D-05:** 使用 `python-dotenv`，**禁止手写解析器**。本次讨论早期曾定过「严格最小集手写解析」，已被 D-01 推翻作废。
- **D-06:** 挂载点在 `src/vela/config.py` **模块导入时**调用一次 `load_dotenv()`（幂等 + 已加载标记）。理由：符合「配置入口唯一收口在 config.py」，CLI / pytest / `vela serve` / 任意直接 `import vela.*` 的脚本全部自动覆盖，调用方零改动。
- **D-07:** **`.env` 定位锁定项目根**，不受 cwd 影响，与 `config.py:17` 的 `_DEFAULT_CONFIG_DIR`（`Path(__file__).resolve().parents[2]`）同源推导。⚠️ 需处理 `pip install` 到 site-packages 后 `parents[2]` 不再是项目根的情形（见 Open Questions）。
- **D-08:** **永远 `override=False`**，不提供任何覆盖开关（不加 `VELA_DOTENV_OVERRIDE`，不加 `vela --env-file`）。已存在的进程环境变量恒定优先——这正是 python-dotenv 的默认行为，无需额外代码，**需要一个专门单测钉住该优先级规则**（ROADMAP 成功判据 1 明确要求）。临时覆盖走 shell 前置赋值：`VELA_LLM_PROVIDER=volcengine vela …`。
- **D-09:** 加载过程**完全静默**——模块导入时不打印任何内容（否则会污染 `vela query` 等命令的 stdout）。「命中哪个 `.env`、加载了多少个变量、哪些被已存在的进程变量遮蔽」全部收到 `vela doctor` 输出里。
- **D-10:** 优先级链因此从四层变五层，**须同步改写文档**：`src/vela/config.py:4` 的 docstring、`.planning/codebase/STACK.md:67`。新链条：
  ```
  显式函数参数 > 进程环境变量 > .env > config/*.yaml > 代码内默认值
  ```

### 测试作用域

- **D-11:** `tests/conftest.py:13` 的 `os.environ.setdefault("VELA_LLM_PROVIDER", "mock")` 改为**无条件赋值** `os.environ["VELA_LLM_PROVIDER"] = "mock"`。
  - **为什么必须改**：D-06 让 `.env` 在 pytest 收集阶段 `import vela.*` 时就灌进 `os.environ`；`setdefault` 此时不会覆盖，`.env` 写着 `volcengine` 就会让 177 个测试全部打真实付费 API，且 `determinism` 标记的用例会大面积失败。
  - `VELA_ARK_*` 等**凭证仍照常从 `.env` 加载**——ENV-01「测试也能读到凭证」依然成立，只是 provider 被锁死。需要真实 LLM 的用例自行 monkeypatch 回 `volcengine`。
  - 同理检查 `conftest.py:14-15` 的 `VELA_PROFILE` / `PYTHONHASHSEED` 是否也需要从 `setdefault` 改为无条件赋值。

### `vela doctor`

- **D-12:** **探测时机按 provider 自动判定**：`VELA_LLM_PROVIDER=mock` → 跳过全部网络探测；`volcengine` / `openai_compat` → 自动联网。
  - ⚠️ **已知后果**：`.env` 切到 volcengine 后，`run_all.sh` / `make demo` 的第一步会开始打网络。由 D-14 的退出码策略兜住，不会中断链路。
- **D-13:** 同时提供 `--offline` 与 `--online` **双向强制覆盖**开关。
- **D-14:** **退出码分层**：
  - 返 `1`：本地硬错误——配置文件缺失 / 必需依赖缺失 / `.env` 形态错误（D-16）
  - 返 `0`：连通性四项任一失败——输出中**显著标 ❌**，但不阻断。保证一次限流或临时断网不会让整条演示链路断在 `run_all.sh` 第一步（`set -euo pipefail`）。
- **D-15:** **四项自检的探测方式**：
  1. **端点可达 / 鉴权有效 / 模型可用**：合并为一次 `max_tokens=1` 的最小 chat 调用，按 openai SDK 抛出的异常类型（`AuthenticationError` / `NotFoundError` / `APIConnectionError` / `RateLimitError` 等）分别归因到三项结论。不用 `/models` 列表——方舟填的是推理接入点 ID（`ep-xxxx`），列表接口未必覆盖。
  2. **四个逻辑模型映射完整性**：先**本地**调 `models_for()` 把 `planner` / `verifier` / `reporter` / `distiller` 各自解析成物理模型链并展示（链为空 = 映射不完整，零成本即可判定）；再对**去重后**的物理模型集合各发一次最小 chat。典型配置下四者都回落到同一个 `VELA_ARK_MODEL`，**只花 1 次调用**。
- **D-16:** ENV-04 的形态检查规则放**新建的 `config/env_checks.yaml`**，描述每个变量的期望形态（正则 / 必填性 / 提示文案），业务代码不硬编码。**该文件不进 `config_hash`**——纯诊断用途，不影响推理结果与证据包指纹。
  - ⚠️ **ENV-04 的重心已转移**：python-dotenv 会自动剥离未加引号值的行尾注释，所以 `.env.example:23-27` 那批注释在加载层**已不再污染值**。剩余的真实检查项是：`base_url` 路径异常（用户 `.env` 中疑似的 `/api/plan/v3`，代码与文档口径是 `/api/v3`）、值内可疑残留注释（加引号的值不会被剥离）、接入点 ID 形态提示。
  - `.env.example` 仍需清理（把行尾注释移到变量上一行）——ENV-04 字面要求，且避免误导。
- **D-17:** **掩码规则**：API key 只显示前 4 后 4（长度不足则全掩）；`base_url` 与接入点 ID（`ep-xxxx`）**明文展示**——它们不是凭证、不能单独认证，而看不到它们就无法对照 `.env` 排查。
- **D-18:** 提供 `--json` 结构化输出，与人读输出**同一套检查结果**（实现上先收成 `list[dict]` 再双通道渲染）。掩码规则在两种形态下一致。Phase 2 要把环境指纹写进评测报表，届时直接消费 `--json`。

### ENV-02 实测验收

- **D-19:** 新增 `realllm` pytest 标记的用例，**默认被 `addopts` 排除**，只有显式 `VELA_LLM_PROVIDER=volcengine pytest -m realllm` 才跑。断言：诊断跑完不中途报错 + 报告非空 + 含至少一个 `[[EV:row_hash]]` 引用（不断言诊断结论正确——ROADMAP 成功判据 2 明确只要求链路通）。与现有 `slow` / `determinism` 标记体系一致，`make test` 绝不会误触发付费调用。

### Claude's Discretion

- `.env.example` 注释重排的具体版式
- `config/env_checks.yaml` 的字段命名与 schema 形状
- doctor 输出的具体排版、`--json` 的 key 命名
- openai SDK 客户端的构造位置与复用策略（每次 `complete()` 新建 vs Provider 实例持有）

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 需求与路线（本阶段的验收标准来源）
- `.planning/REQUIREMENTS.md` §ENV（第 17-24 行）— ENV-01~04 四条需求原文。⚠️ 第 21 行的「stdlib 实现，不新增运行期依赖」**已被 D-01 推翻**，需在本阶段改写
- `.planning/ROADMAP.md` §Phase 1（第 22-35 行）— 四条 Success Criteria 与回归门（177 测试全过 + 仿真基准回归数 = 0）
- `.planning/PROJECT.md` §Context（第 84 行）— 真实 LLM 环境的实际状态核查结论；§Constraints（第 86-96 行）— ⚠️ 第 88 行需按 D-01 改写

### 项目铁律（D-02 确认除依赖最小化外全部保留）
- `AGENTS.md` — 架构铁律 / 代码约定 / 安全边界 / 完成判据。⚠️「依赖最小化」一条需按 D-01 改写
- `CLAUDE.md` — 直接 import AGENTS.md 全文，无需单独改

### 实现对象（本阶段直接改动的文件）
- `src/vela/config.py` — `.env` 加载挂载点（D-06）；第 4 行 docstring 的优先级链需按 D-10 改写
- `src/vela/gateway/openai_compat.py` — 全文 124 行，用 openai SDK 重写（D-04）。`models_for()` 的逻辑模型→物理模型解析与降级链逻辑**保留不变**
- `src/vela/gateway/base.py` — **只读参考，不改**。脱敏（第 96-107 行）、预算预检、降级链（第 113-148 行）、审计全在 `LLMGateway.chat()` 里，`Provider.complete()` 只管发请求 —— 这是换 SDK 改动面可控的结构原因
- `src/vela/cli.py:172-198` — `cmd_doctor` 现状（零网络调用），四项连通性自检是全新能力
- `tests/conftest.py:13-15` — `setdefault` 改无条件赋值（D-11）
- `.env.example` — 行尾注释清理（D-16）
- `config/llm.yaml` — 第 8-12 行四个逻辑模型定义；第 25-39 行 volcengine provider 段（含 `fallback_chain`）

### 领域文档
- `docs/LLM_PRODUCTION.md` — 火山方舟接入的既有文档口径（含 base_url 的 `/api/v3` 正确形式，是 D-16 判定 `base_url` 异常的基准）
- `.planning/codebase/INTEGRATIONS.md` §APIs — 网关抽象与网络请求特性现状
- `.planning/codebase/STACK.md` §Configuration（第 60-67 行）— ⚠️ 第 67 行优先级链需按 D-10 改写

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `LLMGateway.chat()`（`gateway/base.py:87-148`）：脱敏 → 预算预检 → 降级链 → 计量 → 审计的完整流程已就位，换 SDK 完全不需要动它
- `OpenAICompatProvider.models_for()`（`openai_compat.py:31-59`）：逻辑模型专属环境变量 → 通用 `model_env` → `fallback_chain` 的解析顺序，是 D-15 第 2 项「本地判定映射完整性」的现成实现，直接复用
- `build_gateway()`（`base.py:155-174`）：按 `kind` 分发 provider，doctor 可直接用它构造出真实 provider 再探测，不必自己拼客户端
- `config_dir()`（`config.py:20-21`）：项目根定位的既有模式，D-07 与它同源推导

### Established Patterns
- 配置驱动：`config/*.yaml` 承载全部阈值与规则 → D-16 的 `env_checks.yaml` 遵循此模式
- `load_yaml` 有 `lru_cache`（`config.py:28`）：改配置须重启进程才生效，doctor 相关配置同理
- 依赖降级模式（`try: import xxhash / except ImportError: 回退 blake2b`）：**本阶段新依赖不采用此模式**（D-03 定为必需依赖）
- pytest 标记体系：`slow` / `determinism` 已在 `pyproject.toml` 的 `[tool.pytest.ini_options]` 注册 → D-19 的 `realllm` 标记依样注册

### Integration Points
- `config.py` 模块顶部 → `.env` 加载的唯一注入点（D-06）
- `gateway/openai_compat.py` 的 `_post` / `complete` / `embed` 三个方法 → openai SDK 替换的边界，`Provider` 接口签名不变
- `cli.py::build_parser()` 的 `doctor` 子命令（第 268-269 行）→ 挂 `--offline` / `--online` / `--json` 三个参数
- `run_all.sh` 第 1 步与 `Makefile:42` 的 `doctor` 目标 → D-14 退出码策略的消费方，需验证不回归

</code_context>

<specifics>
## Specific Ideas

- 用户原话：**「项目必须打破不新增依赖库的约束限制，能使用专业三方开源库组件的功能尽可能避免重复造轮子手写开发，比如加载 `.env` 文件环境配置，禁止手写实现直接引入新的依赖解决处理。」** —— 这是 D-01 的直接来源，措辞是「禁止手写实现」，planner 遇到任何「要不要自己实现 X」的选择时应默认选成熟三方库。
- 用户在 `.env` override 那题选了「不留逃生舱、行为唯一」，但在 doctor 探测那题选了「`--offline` 与 `--online` 都给」——不是矛盾：前者是**优先级规则**（多一种规则就多一类排查疑案），后者是**执行开关**（不改变任何优先级语义）。planner 设计新开关时按此区分。
- 用户已知并接受 D-12 的后果（切到 volcengine 后 `make demo` 不再离线），由 D-14 的退出码策略兜底。

</specifics>

<deferred>
## Deferred Ideas

- **清理现有可选依赖的降级分支**（`xxhash`→`blake2b`、`blake3`→`blake2b`、`fastapi`→`http.server`）：D-01 的项目级变更逻辑上支持把它们也升为必需依赖并删掉 try-import 双路径（消除双路径带来的行为不一致与测试盲区），但改动面涉及 `util/hashing.py`（会影响指纹算法，进而影响 `config_hash` 与证据包）与 `server/app.py`，超出 Phase 1 边界。用户本次明确选择不展开。
- **补一份 lockfile**（当前依赖只有 `>=` 下限约束，无 `requirements.lock` / `uv.lock`）：新增依赖后可复现性问题会更突出，但属独立议题。
- **其他已知手写轮子的替换清单**（`evidencepack` 的 Merkle 实现、`Makefile` 里自制的 `ast.parse` lint 替换为 ruff 等）：符合 D-01 的方向，但各自都超出本阶段边界，建议在对应阶段或独立里程碑处理。
- **合并 `requirements.txt` / `requirements-optional.txt` 到 `pyproject.toml` 单一它源**（当前两处重复维护、易不同步）：本阶段只在现有结构里加依赖，不重构。

</deferred>

<open_questions>
## Open Questions（留给 planner 定，不需回问用户）

- **D-07 的 `pip install` 兼容**：`Path(__file__).resolve().parents[2]` 在可编辑安装（`pip install -e`）下指向项目根，但在常规安装到 site-packages 后不成立。可选解法：`find_dotenv()` 向上回溯兜底、检测 `.git` / `pyproject.toml` 锚点、或在非项目根场景下静默跳过。planner 择一并加测试。
- **`config/llm.yaml` 中 `retry_backoff_s` 的处置**：openai SDK 的退避策略内置且不可配（只暴露 `max_retries` 与 `timeout`）。该配置项换 SDK 后失效——是删除、还是保留并在 YAML 注释里标注失效，planner 定。`timeout_s` / `max_retries` 可直接映射到 SDK 参数。
- **openai SDK 异常类型 → 现有 `LLMError` 的映射粒度**：`LLMGateway.chat()` 的降级链（`base.py:119-131`）对任何异常都会 fallback 到下一个接入点。鉴权失败重试其他接入点通常无意义，是否要区分「不可重试类」（`AuthenticationError` / `PermissionDeniedError`）直接中断，planner 评估——注意这属于行为变更，需确认不破坏现有 `tests/test_gateway.py`。

</open_questions>

---

*Phase: 1-真实 LLM 环境就绪*
*Context gathered: 2026-07-31*
