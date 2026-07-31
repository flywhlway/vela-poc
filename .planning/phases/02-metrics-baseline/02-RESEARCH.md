# Phase 2: metrics-baseline - Research

**Researched:** 2026-07-31
**Domain:** 评测度量可信度 / 真实 LLM 方差基线 / Token 成本可观测（不改 AgentGraph 推理）
**Confidence:** HIGH

## Summary

Phase 2 是 ADR-2「先修尺子再修系统」的落地：修正引用闸门与 `config_hash` 指纹、扩展评测 runner/报表（`--repeat` / 过程指标 / 消融 / 缓存 / workspace 复用）、扩展 `TokenLedger` 成本归集与 `scripts/bench.py`，最后在 `--no-cache` + volcengine 下产出取代 44.4% 的带 95% CI 基线。实现面几乎全部落在 `citations.py`、`config.py`、`eval/*`、`cli.py`、`gateway/*`、`budget.py`、`scripts/bench.py`——**禁止**改 `graph.py` 节点控制流或提示词语义。

代码现状与锁定决策对齐度高：`CitationReport.ok` 在零引用时仍为 True（F-01 未修）；`config_hash` 只覆盖 pipeline/parsers/ota_phases；`cmd_eval` 无 `--repeat`/`--reuse-workspace`/`--no-cache`/`--ablation`；`TokenLedger` 只有硬切断无成本字段；`Auditor` 不落 `finish_reason`（截断率需在网关侧补字段才能可测）。消融可借已有 `AgentGraph(skills=SkillRegistry(...))` 注入点做运行时 mask，无需改技能 YAML。Student t 95% CI 用 `scipy.stats.t.interval` + `stats.sem`（已用 Context7/官方 API 与本机实测验证）。

**Primary recommendation:** 按锁定顺序先交付 METR-01~08 + PERF-02（尺子与可观测基础设施），用 mock 全量回归钉住契约；METR-09/PERF-01 收尾在 `--no-cache` 真实 LLM 下写入 `.planning/phases/02-metrics-baseline/baseline/`，并废止 44.4% 对比口径。

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### 引用闸门语义（METR-01 / METR-02）

- **D-01:** `CitationReport.dangling_rate` 在 `total == 0` 时返回 `None`（不再返回 `0.0`）；新增 `has_citations: bool`（`total > 0`）。
- **D-02:** `CitationReport.ok` 在零引用时为 `False`（`has_citations` 为假即质量闸门失败）；有引用且无悬空才为 `True`。零引用报告必须被强制判失败——有专门单测钉住 `total==0` 分支。
- **D-03:** `citation_coverage` = 含至少一个 `[[EV:…]]` 的事实句数 / 事实句总数。事实句切分用**确定性启发式**（中英文句号/换行；空行与纯标题行不计），细则由 planner 钉死并单测；指标进入评测报表与 `_TARGETS`（G1 目标线 ≥ 0.9 仅作报表目标，本阶段不因未达标阻断回归门以外的交付——回归门仍是 177 测试 + 仿真已通过用例回归数 = 0）。
- **D-04:** 本阶段**只修度量侧闸门/指标**；reporter 侧「引用不足重试」（ORCH-08 / C-03）属 Phase 3，禁止在本阶段改 `node_report` 推理行为。评测/校验路径消费修正后的 `ok`/`has_citations` 即可让零引用报告在质量闸门上失败。

#### config_hash 覆盖与指纹断代（METR-03 / NR-6）

- **D-05:** `config_hash()` payload **扩展纳入**：`config/skills/*.yaml`（或现有 skills 加载路径下全部技能 YAML）、`budget.yaml`、`llm.yaml`、`gateway/prompts.py` 的内容哈希；**保留**既有 `pipeline.yaml` / `parsers.yaml` / `ota_phases.yaml` / `canon_rules_version` / `fingerprint_algos`。
- **D-06:** **继续排除**（与 Phase 1 D-16 一致）：`config/env_checks.yaml` 及纯诊断用途配置——改它们不得改变指纹。
- **D-07:** 本阶段首次扩展必然造成指纹断代。交付一份 **hash 版本映射表**（Markdown）：记录断代时刻的旧 hash → 新 hash、纳入文件清单、日期与简短原因；路径定为 `docs/CONFIG_HASH_HISTORY.md`（若不存在则新建）。之后每次有意改变 hash 口径须追加一行——承接 NR-6，越早一次性断代越好。
- **D-08:** 修改技能库 / `budget.yaml` / `llm.yaml` / 提示词任一项后，`config_hash` 必须变化——用断言单测覆盖（至少四类输入各一条）。

#### 重复评测与置信区间（METR-04）

- **D-09:** `vela eval run --repeat N`：N 次完整评测后输出各指标的**均值 ± 标准差**与**置信区间**。默认行为保持单次（无 `--repeat` 时与今日一致）；聚合仅在显式 `--repeat N`（N≥2）时启用。
- **D-10:** 小样本（基线 N≥3）置信区间采用 **Student t 双侧 95% CI**。实现优先用成熟库（Phase 1 D-01：scipy/numpy 可进可选或必需依赖，planner 按「纯本地可装、不破坏离线主链路」择一）；禁止手写脆弱统计若库已能覆盖。
- **D-11:** 报表同时给出逐次 run 明细与聚合行，避免只剩一个合并数字无法审计。

#### LLM 响应缓存与 workspace 复用（METR-06 / METR-07）

- **D-12:** 磁盘缓存键 = `(provider, physical_model, prompt_sha256, params)`（与需求字面一致）；缓存根目录默认项目级 `.cache/vela/llm/`（gitignore）；提供 `--no-cache` 关闭。重复评测场景目标命中率 > 90%（可用同 prompt 二次跑验证）。
- **D-13:** 缓存挂在网关出站路径（`LLMGateway.chat` 或 Provider 之上），**不得**改变 mock/真实供应商的业务语义；mock 评测可走缓存亦可旁路——planner 保证 determinism 标记用例不被缓存引入非确定性。
- **D-14:** `--reuse-workspace`：若目标 workspace 已存在可用证据库（既有 `analysis.duckdb` / 建库完成标记，细则 planner 对齐 `EvalRunner`），则跳过重建；否则正常 `build`。不得在复用时 silently 使用损坏半成品库（缺库或 QA 未过则重建或显式失败）。

#### 过程指标与消融评测集（METR-05 / METR-08）

- **D-15:** 7 项过程指标（`premature_stop_rate` / `llm_parse_failure_rate` / `llm_truncation_rate` / `verdict_supported_ratio` / `skill_switch_per_session` / `unexplained_error_rate` / `citation_coverage`）+ 每轮决策轨迹表进入评测报表。数据从既有 `SessionState` / 事件 / 用例结果字段**聚合**，不改图节点逻辑；Phase 3 才会真正压低的指标本阶段允许显示为高值或占位——**可测即可**，不要求达标。
- **D-16:** 消融集 = 10 场景 × 按 golden 真值的正确技能在**运行时从候选集 mask 剔除**（不改 `builtin.yaml` 源文件、不持久化残缺技能库）。产出四指标：`misdiagnosis_rate_under_ablation` / `novel_detection_recall` / `unexplained_error_rate` / `confidence_calibration_error`，纳入 `_TARGETS` 但本阶段**不要求达标**（达标依赖 Phase 3~6）。CLI 入口形态由 planner 定（如 `vela eval run --ablation` 或子命令），须可一键跑通。
- **D-17:** 消融/过程指标中依赖 Phase 5 六级置信度或 `novel:` 的字段：本阶段用**当前二元结论可计算的代理定义**并在报表注释标明「代理口径，Phase 5 后替换」——禁止为算出 `novel_detection_recall` 而提前实现 CONF-03。

#### 真实方差基线与 NR-1（METR-09）

- **D-18:** 在 `--no-cache` + `VELA_LLM_PROVIDER=volcengine` 下，对仿真黄金集做 N≥3 次重复，产出准确率均值±标准差与 95% CI，以及端到端延迟/成本联立基线（与 PERF-01 可同次采集）。**明确标注**：基准=仿真回归门，**非能力宣称**；G4 本期未测。
- **D-19:** 基线产物落盘：` .planning/phases/02-metrics-baseline/baseline/` 下至少一份 Markdown 人读报告 + 一份 JSON 机读明细（含 `config_hash`、doctor 环境指纹字段、N、provider、是否 cache、逐次指标）。自本阶段验收完成起，**禁止再引用 44.4% 作为后续对比基线**；Phase 3~6 一律以本目录基线为准（NR-1：分数可能因引用闸门变准而下降——预期行为，不是回归）。
- **D-20:** 付费实测沿用 Phase 1：`realllm` 标记 + 默认 `addopts` 排除；CI/`make test` 不触发付费。基线跑数可作为人工门或显式 `pytest -m realllm` / Makefile 目标，planner 写清门禁与凭据要求。

#### 成本与延迟（PERF-01 / PERF-02）

- **D-21:** 扩展现有 `scripts/bench.py`，覆盖真实火山引擎 provider：单次诊断 token 成本与端到端 P95 延迟；可与 METR-09 共用实测数据，避免重复付费。
- **D-22:** `TokenLedger` 从「只做预算切断」扩展为「成本归集可观测」：累计 tokens、按配置单价估算成本、会话级汇总可被 eval/bench 读取。单价与「单次诊断成本上限」放进 `config/budget.yaml`（或并列成本段），超限发 `EventBus` ALERT——**默认告警不替代**既有 `BudgetExceeded` 硬切断语义（硬切断阈值仍由预算档决定）。
- **D-23:** PERF 基线数字写入与 D-19 同一 `baseline/` 目录（或其中明确章节），便于 G6 汇报。

#### 阶段纪律与回归门

- **D-24:** 任何计划/实现若需要改动 `graph.py` 节点控制流或提示词「诱导行为」——**拒绝并拆到 Phase 3+**。允许的触碰面：`citations.py` 闸门语义、`config_hash`、`eval/*`、`cli` eval 参数、gateway 缓存钩子、`budget.TokenLedger`、`scripts/bench.py`、配置与文档、测试。
- **D-25:** 回归门不变：现有测试全量通过（failed=0）；仿真基准已通过用例回归数 = 0（一票否决）。新指标入报表不得破坏既有 mock 黄金评测的退出码契约，除非测试与文档同步更新且回归数仍为 0。
- **D-26:** 承接 Phase 1：评测报表可消费 `vela doctor --json` 的环境指纹键（`config_hash` / `provider` / `dotenv` 等）写入基线元数据；不改 doctor 契约。

### Claude's Discretion

- 事实句切分正则的具体字符类与边界用例表
- 缓存文件格式（JSONL vs 单文件 blob）与淘汰策略
- `--ablation` CLI 子命令 vs 旗标的最终命名
- `docs/CONFIG_HASH_HISTORY.md` 表格列名微调
- scipy vs 纯公式实现 t 区间（只要正确且可测）
- bench 与 eval 是否共用 runner 内部 API

### Deferred Ideas (OUT OF SCOPE)

- Reporter 引用不足重试与 `insufficient_citation` 降级（ORCH-08）→ Phase 3
- 编排层过程指标真正压降（首轮 stop / JSON / 截断等）→ Phase 3
- 六级置信度与真 `novel:` 口径替换本阶段代理定义 → Phase 5
- 消融集上 FM-1 的 Q2 捕获率 → Phase 6（依赖仲裁器）
- G4 真实工单标注基准 → v2.0（REAL-01）
- 可选依赖降级分支清理、lockfile、ruff 等工程卫生 → 非本阶段

None — discussion stayed within phase scope（无折叠 todo）
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| METR-01 | 零引用报告质量闸门失败；`citation_coverage` 入报表 | D-01~D-04；改 `CitationReport.ok`/`has_citations`；`eval` 计算 coverage；禁止改 `node_report` |
| METR-02 | `dangling_rate` 在 total==0 → `None`；`has_citations`；单测 | 同 citations.py；同步 `to_dict` 与 runner 对 None 的聚合 |
| METR-03 | skills/budget/llm/prompts 进 `config_hash`；映射表 | 扩展 `config_hash` payload；新建 `docs/CONFIG_HASH_HISTORY.md`；排除 `env_checks.yaml` |
| METR-04 | `--repeat N` → 均值±标准差 + 95% CI | `scipy.stats.t.interval`；默认单次不变；报表含逐次明细 |
| METR-05 | 7 项过程指标 + 决策轨迹表 | 从 SessionState/events/audit 聚合；网关补 `finish_reason` 落审计；代理公式见下文 |
| METR-06 | LLM 磁盘缓存 + `--no-cache`；命中率 >90% | 挂 `LLMGateway.chat` 脱敏后；键=(provider, physical_model, prompt_sha256, params) |
| METR-07 | `--reuse-workspace` 跳过重建 | 以 `gold/analysis.duckdb` + `manifest.json` + `qa/qa_report.json` 为可用判据 |
| METR-08 | 消融评测集 + 4 泛化指标入 `_TARGETS` | 运行时 `SkillRegistry` mask；代理 novel/calibration；不要求达标 |
| METR-09 | `--no-cache` 真实 LLM 方差基线 | 收尾行；落盘 `baseline/`；废止 44.4%；`realllm` 门禁 |
| PERF-01 | bench 覆盖 volcengine；成本+P95 | 扩展 `scripts/bench.py`；可与 METR-09 同次采集 |
| PERF-02 | TokenLedger 成本归集 + 超限 ALERT | `budget.yaml` 单价/上限；ALERT 不替代 `BudgetExceeded` |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 引用闸门语义 / citation_coverage | API / Backend（`agent/citations` + `eval`） | — | 确定性校验与报表聚合，不在浏览器 |
| config_hash 指纹与断代表 | API / Backend（`config.py`）+ Docs | Database（evidence pack salt） | 指纹写入 runs/证据包；映射表为人读文档 |
| `--repeat` / CI 聚合 | API / Backend（`eval` + CLI） | — | 本地 CLI 评测编排 |
| LLM 磁盘缓存 | API / Backend（`LLMGateway`） | CDN/Static（本地 `.cache/` 文件） | 出站路径缓存；非服务端边缘 |
| `--reuse-workspace` | API / Backend（`EvalRunner`） | Database / Storage（DuckDB workspace） | 跳过 build，读已有 Gold |
| 过程指标 / 决策轨迹 | API / Backend（`eval` 聚合） | Database（events.jsonl / sessions） | 不改图节点，事后聚合 |
| 消融 mask | API / Backend（`EvalRunner` + `SkillRegistry`） | — | 构造期注入 skills，不改 YAML |
| TokenLedger 成本归集 | API / Backend（`gateway/budget`） | Config（`budget.yaml`） | 会话级计量 + 配置单价 |
| 真实基线 / bench | API / Backend（CLI/scripts） | 外部 LLM（volcengine） | 付费实测；产物落 planning/baseline |
| 测试与回归门 | API / Backend（pytest） | — | mock 默认；realllm 排除 |

## Project Constraints (from .cursor/rules/ + AGENTS.md)

仓库无 `.cursor/rules/` 与项目级 `.cursor/skills/`。生效约束来自 `AGENTS.md`（与 Phase 1 D-01 对齐）：

- 查询唯一收口：`LogQueryAPI.call()`；禁止评测路径绕过门面直连 DuckDB（过程指标若扫 ERROR 行须经 API）。
- 配置驱动：阈值/单价/缓存目录进 `config/*.yaml` 或环境变量；`load_yaml` 有 `lru_cache`——改配置须重启或清 cache。
- 模型可插拔：缓存/bench 不得写 provider 专属分支；只认 `Provider` / `VELA_LLM_PROVIDER`。
- 程序化校验优先：引用闸门独立于模型自述。
- 图节点即方法：本阶段**不**在 `agent/nodes/` 建文件，也**不**改节点行为。
- 单线程同步；不引入并发框架；DuckDB `read_only=True`。
- 三方库优先（Phase 1 D-01）：统计用 scipy/numpy；禁止手写脆弱数值栈。
- 不用 `logging`；结构化事件走 `EventBus`；CLI 用 `print()`。
- 出站必经 `redact.py`；禁止提交 `.env`/密钥。
- 完成判据：`make test-fast`；涉及建库/查询/推理须 `make test`；行为变化同步 config 与文档。
- 测试风格（TESTING.md）：不用 `unittest.mock`；用真实 `MockProvider` + `tmp_path`；平面 `tests/test_*.py`。

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| 现有 VELA 栈 | duckdb / pyarrow / PyYAML / pytz / python-dotenv / openai | 主链路 | 已在 `pyproject.toml` `[VERIFIED: pip index + repo]` |
| scipy | **1.18.0**（PyPI 当前；约束建议 `scipy>=1.11`） | Student t 95% CI（`stats.t.interval` + `stats.sem`） | Phase 1 D-01 + D-10；官方 stats API `[VERIFIED: Context7 /websites/scipy_doc_scipy + 本机实测]` |
| numpy | **2.5.1**（scipy 依赖；约束建议随 scipy） | 均值/数组运算 | scipy 依赖；`np.mean` 与 t.interval 配套 `[VERIFIED: pip index versions]` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | ≥8.0（已有） | 单测 / realllm 门禁 | 全部 METR/PERF 回归 |
| 标准库 `hashlib` / `json` / `pathlib` | stdlib | LLM 缓存文件与 cache key | 不引入 diskcache（见 Discretion） |
| 标准库 `statistics` | stdlib | 可选辅助（mean/stdev） | 可与 scipy 并用；CI 仍以 scipy 为准 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| scipy `t.interval` | 手写 t 分位表 / `statistics` | 违反 D-01/D-10；仅当无法装 scipy 时作 fallback（不推荐作主路径） |
| 标准库 JSON 缓存文件 | `diskcache` 5.6.3 | diskcache 成熟但本阶段缓存语义极简；stdlib 零新依赖、易审计 `[ASSUMED: diskcache 非必需]` |
| 把 scipy 放进必需依赖 | 仅 `dev`/`all` 可选 | **推荐可选**：离线 mock 主链路不依赖 scipy；`--repeat`/基线聚合时需要 |

**Installation（推荐）：**

```bash
# 写入 pyproject optional-dependencies.dev/all 与 requirements-optional.txt
.venv/bin/pip install 'scipy>=1.11'
# 或 make install-dev 扩展后一次安装
```

**Version verification:** 2026-07-31 本机 `pip index versions` → scipy 1.18.0、numpy 2.5.1；`slopcheck install scipy numpy` → 二者均为 `[OK]`。`.venv` 内**尚未**安装——计划须含 install 步骤。

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| scipy | PyPI | 多年（SciPy 科学计算标准库） | 极高 | github.com/scipy/scipy | [OK] | Approved — 建议 `>=1.11` 进 optional `dev`/`all` |
| numpy | PyPI | 多年 | 极高 | github.com/numpy/numpy | [OK] | Approved — 随 scipy 传递；可不单独钉版本 |
| diskcache | PyPI | 多年 | 中高 | （未强制） | 未跑（不推荐） | **不采用** — Discretion 选 stdlib 缓存 |

**Packages removed due to slopcheck [SLOP] verdict:** none  
**Packages flagged as suspicious [SUS]:** none  

## Architecture Patterns

### System Architecture Diagram

```text
                    +-----------------------------------------+
                    |  CLI: vela eval run                     |
                    |  flags: --repeat --reuse-workspace      |
                    |         --no-cache --ablation --provider|
                    +-------------------+---------------------+
                                        |
                    +-------------------v---------------------+
                    |  EvalRunner                             |
                    |  1) reuse? -> skip build : build        |
                    |  2) ablation? -> SkillRegistry(mask)    |
                    |  3) AgentGraph.run() x cases            |
                    |  4) aggregate CaseResult + process metrics|
                    +---------+------------------+------------+
                              |                  |
              +---------------v---+    +---------v-----------+
              | Evidence workspace|    | LLMGateway.chat     |
              | gold/analysis.duckdb|  | redact -> cache? -> |
              | manifest + qa_report|  | budget -> Provider  |
              +-------------------+    +---------+-----------+
                                                 |
                                      +----------v----------+
                                      | .cache/vela/llm/    |
                                      | TokenLedger(+cost)  |
                                      | Auditor(+finish_reason)|
                                      +---------------------+
                              |
              +---------------v------------------------------+
              | report.render_markdown / eval_result.json    |
              | _TARGETS + process + ablation (+ CI if N>=2) |
              +---------------+------------------------------+
                              | METR-09 / PERF-01 (last)
              +---------------v------------------------------+
              | baseline/*.md + *.json                       |
              | + doctor --json fingerprint                  |
              +----------------------------------------------+
```

### Recommended Project Structure

```
src/vela/
├── agent/citations.py          # METR-01/02：ok / has_citations / dangling_rate=None
├── config.py                   # METR-03：扩展 config_hash payload
├── eval/
│   ├── runner.py               # reuse / ablation / CaseResult 扩展字段
│   ├── report.py               # _TARGETS + 过程/消融/聚合渲染
│   ├── stats.py                # NEW：t-interval 聚合（scipy）
│   ├── process_metrics.py      # NEW：7 项过程指标 + 轨迹表
│   └── ablation.py             # NEW：mask 技能 + 代理泛化指标
├── gateway/
│   ├── base.py                 # METR-06：chat 内缓存钩子；audit 传 finish_reason
│   ├── budget.py               # PERF-02：成本归集
│   └── cache.py                # NEW：磁盘缓存读写（stdlib）
├── cli.py                      # eval 新旗标；基线元数据钩子
scripts/bench.py                # PERF-01
docs/CONFIG_HASH_HISTORY.md     # NEW：NR-6 断代
.planning/phases/02-metrics-baseline/baseline/   # METR-09/PERF 产物
.cache/vela/llm/                # gitignored（根 .gitignore 已有 .cache/）
tests/
├── test_agent.py               # 零引用 ok=False；dangling_rate None
├── test_obs_and_config.py      # config_hash 四类输入变化；排除 env_checks
├── test_eval.py                # repeat / process / ablation / coverage
└── test_gateway.py             # cache hit；TokenLedger cost；finish_reason 审计
```

### Pattern 1: 引用闸门（度量侧 only）

**What:** `CitationReport` 语义修正后，`to_dict()` 暴露 `has_citations` / `ok` / `dangling_rate: float|None`；eval 把 `ok==False`（含零引用）计为质量闸门失败信号；**不**在 `node_report` 加重试。  
**When to use:** METR-01/02。  
**Example:**

```python
# Source: 本仓库 citations.py 现状 + D-01/D-02
@property
def has_citations(self) -> bool:
    return self.total > 0

@property
def dangling_rate(self) -> float | None:
    if self.total == 0:
        return None
    return round(len(self.dangling) / self.total, 4)

@property
def ok(self) -> bool:
    return self.has_citations and not self.dangling
```

### Pattern 2: 网关缓存（脱敏后、计量一致）

**What:** 在 `LLMGateway.chat` 完成 redact 之后、调用 `provider.complete` 之前查缓存；命中则构造 `LLMResponse` 并仍走 `ledger.charge`（成本口径与未命中一致），写 audit 时标记 `cache_hit=true`。`--no-cache` / env 关闭时旁路。  
**When to use:** METR-06；METR-09 强制 `--no-cache`。  
**Key:** `sha256(canonical_json({provider, physical_model, prompt_sha256, params}))`；文件 `.cache/vela/llm/{key}.json`。

### Pattern 3: 消融运行时 mask

**What:** `EvalRunner` 对故障用例取 `gc.expected_skills`，构造 `SkillRegistry(skills=[s for s in load_skills() if s["id"] not in masked])`，传入 `AgentGraph(..., skills=registry)`。健康用例不 mask。  
**When to use:** `--ablation`（推荐旗标名，Discretion）。  
**Why not edit YAML:** D-16 明确禁止持久化残缺技能库。

### Pattern 4: Student t 95% CI

**What / Example:**

```python
# Source: https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.t.html
# Verified: scipy 1.18.0 本机 — stats.t.interval(0.95, df=n-1, loc=mean, scale=sem)
from scipy import stats
import numpy as np

def mean_ci_95(values: list[float]) -> dict:
    xs = np.asarray(values, dtype=float)
    n = xs.size
    mean = float(np.mean(xs))
    std = float(np.std(xs, ddof=1)) if n >= 2 else 0.0
    if n < 2:
        return {"mean": mean, "std": std, "ci95": None, "n": n}
    sem = float(stats.sem(xs))
    lo, hi = stats.t.interval(0.95, df=n - 1, loc=mean, scale=sem)
    return {"mean": mean, "std": std, "ci95": [float(lo), float(hi)], "n": n}
```

### Anti-Patterns to Avoid

- **改 `node_report` 做引用重试：** Phase 3 ORCH-08；违反 D-04/D-24。
- **为 novel 指标实现 CONF-03：** 违反 D-17；用代理口径。
- **缓存未脱敏 prompt：** 安全违规；键与正文必须基于 redact 后文本。
- **缓存命中跳过 `ledger.charge`：** 成本基线失真；命中仍应按缓存内 token 计数 charge。
- **`--reuse-workspace` 仅看目录存在：** 半成品库（无 duckdb/manifest/qa）必须重建或失败（D-14）。
- **把新指标硬失败接入 `cmd_eval` 退出码而未同步测试：** 破坏 D-25 mock 契约——过程/消融指标入报表但**不**抬高退出码门槛（或同步改测试并保持仿真回归数=0）。
- **在聚合里对 `dangling_rate is None` 直接 `float()`/`sum()`：** 会 TypeError；见 Pitfalls。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Student t 置信区间 | 手抄 t 分位表 | `scipy.stats.t.interval` + `stats.sem` | 小样本边界、ddof、数值稳定 |
| `.env` / YAML 解析 | 自写解析器 | 已有 dotenv / PyYAML | Phase 1 已定 |
| LLM HTTP | 自写 urllib | 已有 openai SDK | Phase 1 |
| 磁盘 KV 缓存框架 | 自研复杂 LRU 服务 | stdlib JSON 文件 + sha256 文件名 | 单机 POC；命中率目标可用二次跑验证 |
| 技能检索 | 消融时改 retrieve 算法 | 既有 `SkillRegistry(skills=...)` 过滤 | 构造期 mask 即可 |

**Key insight:** 本阶段复杂度在「度量契约与聚合」，不在新算法——凡统计/IO 有成熟库或现成注入点就复用。

## Common Pitfalls

### Pitfall 1: `dangling_rate=None` 炸毁下游

**What goes wrong:** `EvalRunner` 现有 `float(...get("dangling_rate", 0.0))`；`Metrics.gauge` → `snapshot` 里 `round(v, 4)`；平均值 `sum(c.dangling_rate)`。  
**Why:** 今日属性永为 float。  
**How to avoid:** `CaseResult.dangling_rate: float | None`；聚合时跳过 None 或分母只计有引用用例；`Metrics.gauge` 忽略 None（改 `obs/metrics.py` 比改 graph 控制流更安全）。报表单独展示「零引用用例数」。  
**Warning signs:** mock e2e 在零引用路径 TypeError。

### Pitfall 2: 指纹断代未建映射表

**What goes wrong:** 证据包 `salt=config_hash` 旧包不可比；NR-6 失控。  
**How to avoid:** 扩展 hash 的同一 PR 写入 `docs/CONFIG_HASH_HISTORY.md`（旧=`sha256:32d709b3…` 已测于 2026-07-31）。  
**Warning signs:** 仅改代码无文档。

### Pitfall 3: 缓存绕过预算或写入明文敏感信息

**What goes wrong:** 缓存在 redact 前；或命中跳过 `precheck`/`charge`。  
**How to avoid:** 插入点固定在 redact 之后；命中仍 `precheck`+`charge`；缓存正文为已脱敏 messages。  
**Warning signs:** audit 出现 VIN/手机号；ledger 在命中时为 0。

### Pitfall 4: 过程指标「不可测」却硬编码假达标

**What goes wrong:** audit 默认 `log_prompt: false` 且不落 `finish_reason`，无法事后算 truncation/parse。  
**How to avoid:** 网关允许触碰面内扩展 `Auditor.record(..., finish_reason=)`（无需落全文 prompt）；parse 失败可用 events/`plan.done` 与空 skill+非预期 stop 的**代理**，报表标注「代理/待 Phase 3」；禁止为好看填 0 却不标注。  
**Warning signs:** 七项指标全是 0.0 且无注释。

### Pitfall 5: 消融改了 `builtin.yaml` 或污染全局 SkillRegistry

**What goes wrong:** 源文件被改或单例被清空。  
**How to avoid:** 每用例新 `SkillRegistry(list)`；测后确认 `config/skills/builtin.yaml` 无 diff。  
**Warning signs:** 消融后普通 eval skill_hit 崩溃。

### Pitfall 6: METR-09 在尺子未修时抢跑

**What goes wrong:** 基线仍建立在旧闸门上。  
**How to avoid:** ROADMAP/D-18 顺序——基础设施合并并通过 mock 回归后，最后人工/显式 `realllm` 跑基线。  
**Warning signs:** baseline JSON 的 `citation_gate_version` 缺失或仍宣称对比 44.4%。

### Pitfall 7: `cmd_eval` 退出码被新指标抬高

**What goes wrong:** 今日退出码看 top1/FP/dangling/illegal_skill；若把 `citation_coverage≥0.9` 或消融指标纳入硬失败，mock 黄金可能红。  
**How to avoid:** D-03/D-16——目标线进报表；硬退出码仅在同步测试且仿真回归数仍为 0 时扩展。推荐：零引用 `ok` 反映在 per-case 字段与报表，是否纳入 exit 由 planner 显式决策并改 `test_eval`/`test_cli`。

## Code Examples

### 事实句切分（Discretion 推荐钉法）

```python
# 推荐启发式（planner 应原样钉进单测表）
# - 按换行分段，再按 [?？!！.。] 切句
# - 丢弃：空行、仅 markdown 标题（^#{1,6}\s）、仅空白
# - 事实句：去空白后长度 ≥ 8 的句子（避免「是。」类噪声）[ASSUMED: 长度阈值可调]
# citation_coverage = count(句子含 CITE_RX) / count(事实句)；分母 0 → None 或 0.0（建议 None 与 dangling 对齐）
```

### workspace 复用判据

```python
# 与 evidence/pipeline.py 产物对齐 [VERIFIED: codebase]
def workspace_reusable(ws: Path) -> bool:
    db = ws / "gold" / "analysis.duckdb"
    manifest = ws / "manifest.json"
    qa = ws / "qa" / "qa_report.json"
    if not (db.is_file() and manifest.is_file() and qa.is_file()):
        return False
    # 可选：读 qa_report.checks 全 ok；失败则 False → 重建
    return True
```

### 代理消融指标（D-17）

```python
# 报表必须标注「代理口径，Phase 5 后替换」
# misdiagnosis_rate_under_ablation:
#   故障用例中 predicted_label 非空且 ≠ expected 且 status==answered 的比例
# novel_detection_recall（代理）:
#   消融故障用例中 status ∈ {unanswerable, human_gate}
#   或 predicted_label ∈ {None,"","undetermined","no_fault_found"} 的比例
#   （真 novel: 前缀待 Phase 5）
# unexplained_error_rate（代理）:
#   经 LogQueryAPI 统计 ERROR/FATAL 行中未出现在 seen_row_hashes 的比例（会话级均值）
# confidence_calibration_error（代理）:
#   | 1{status==answered} - 1{top1_hit} | 在故障用例上的均值
#   （真六级校准待 Phase 5）
```

### TokenLedger 成本归集草图

```python
# config/budget.yaml 新增并列段（示例键名 Discretion）
# cost:
#   currency: CNY
#   price_per_1k_prompt_tokens: 0.0    # 按方舟定价填
#   price_per_1k_completion_tokens: 0.0
#   diagnose_cost_alert: 1.0           # 单次诊断成本告警上限
# charge() 后累加 estimated_cost；超限 bus.emit(..., Severity.ALERT)
# 不 raise BudgetExceeded
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 零引用 `ok=True`、`dangling_rate=0.0` | `ok=False`、`dangling_rate=None`、`has_citations` | Phase 2 / METR-01-02 | 尺子变准；分数可能下降（NR-1） |
| 单点 44.4% 无 CI | N≥3 + Student t 95% CI 基线目录 | Phase 2 / METR-09 | 后续阶段唯一对比锚 |
| config_hash 三 YAML | +skills+budget+llm+prompts | Phase 2 / METR-03 | 指纹断代，需 HISTORY |
| TokenLedger 仅切断 | +成本归集 + ALERT | Phase 2 / PERF-02 | G6 可回答单价问题 |
| scipy `interval(alpha=...)` 旧参名 | `interval(confidence=...)` | SciPy 1.10+ | 新代码用 `confidence=` `[CITED: scipy docs / community]` |

**Deprecated/outdated:**

- 将 44.4% 作为 Phase 3+ 对比基线（D-19 / NR-1）。
- 手写 t 区间或「依赖最小化故不用 scipy」（已被 Phase 1 D-01 废止）。

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 事实句最小长度阈值 8 字符合适 | Code Examples | coverage 数值偏移；须单测表可调 |
| A2 | 标准库 JSON 文件缓存足以达 >90% 命中率 | Standard Stack | 若不足可再引入 diskcache |
| A3 | 代理 novel/calibration 公式可被验收方接受为「可测」 | Ablation proxies | 需在报表显著标注 |
| A4 | `obs/metrics.py` 容忍 None 不算违反 D-24 | Pitfalls | 若严格禁止，则仅改 eval 聚合并避免 gauge(None) |
| A5 | 方舟单价由用户填入 budget.yaml，研究不锁具体数字 | PERF-02 | 基线成本绝对值依赖配置 |

**若表空则无需确认——本表非空：A1–A3 建议 planner 在任务中写死并单测，无需再开 discuss。**

## Open Questions

1. **`cmd_eval` 是否因 `has_citations==False` 直接非零退出？**
   - What we know: METR-01 要求质量闸门失败；今日 exit 看聚合 dangling_rate 等。
   - What's unclear: per-case 失败 vs 全局阈值。
   - Recommendation: 报表+`cases[].citation_ok` 必达；全局 exit 增加「零引用用例数==0」或保持仅报表——**优先**把 `citation_ok` 纳入与 dangling 同级的聚合失败条件，并同步测试（仍保仿真回归数=0）。

2. **scipy 放 optional 还是 required？**
   - Recommendation: **optional `dev`/`all`**；`--repeat` 缺依赖时 CLI 清晰报错。不破坏离线 diagnose。

3. **过程指标 `llm_parse_failure_rate` 在无 completion 落盘时如何取值？**
   - Recommendation: 网关不强制 `log_prompt=true`；parse 代理 = planner 输出无法形成合法动作且 events 可见的比例，或 Phase 2 报表显示 `null` + 注释「待 ORCH-03 埋点」。可测性优先于假精度。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | 全阶段 | ✓ | 3.12.13（.venv） | — |
| 项目 .venv + 主依赖 | mock 评测 | ✓ | 见 pyproject | `make install-dev` |
| scipy / numpy | METR-04 CI | ✗（.venv 内未装；系统 site-packages 有 1.18.0/2.4.6） | 装入 .venv | 明确报错；禁止静默手写 |
| volcengine 凭证 / `.env` | METR-09 / PERF-01 | ✓（Phase 1 已通） | — | 无凭证则跳过付费门，标 blocked |
| `data/dataset` 黄金集 | eval/baseline | 视本地 | — | `make sim` |
| 磁盘 `.cache/` | METR-06 | ✓（gitignore 已有 `.cache/`） | — | — |
| graphify | 研究增强 | ✗ disabled | — | 未用图；纯代码研究 |

**Missing dependencies with no fallback:** 无（scipy 可装；真实 LLM 仅收尾行需要）。  

**Missing dependencies with fallback:** scipy 未进 .venv → 计划 Wave 含安装；无 volcengine → METR-09 人工门挂起但 mock METR-01~08 可完成。

## Validation Architecture

> `workflow.nyquist_validation` 未在 `.planning/config.json` 设为 false → **启用**。

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest ≥8.0 |
| Config file | `pyproject.toml` → `[tool.pytest.ini_options]`（`addopts = "-q --strict-markers -m 'not realllm'"`） |
| Quick run command | `make test-fast` |
| Full suite command | `make test` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| METR-01 | 零引用 → `ok is False`；coverage 入 metrics | unit | `pytest tests/test_agent.py -k citation -q` + `tests/test_eval.py -k coverage` | ⚠️ 需扩展（现有 citation 测未钉零引用失败） |
| METR-02 | `total==0` → `dangling_rate is None`；`has_citations` | unit | `pytest tests/test_agent.py -k 'dangling or has_citations or zero' -q` | ❌ Wave 0 |
| METR-03 | 四类输入改变 hash；env_checks 不改变 | unit | `pytest tests/test_obs_and_config.py -k config_hash -q` | ⚠️ 仅有确定性测，缺四类变异 |
| METR-04 | `--repeat 3` 产出 mean/std/ci95 | unit/integration | `pytest tests/test_eval.py -k repeat -q` | ❌ Wave 0 |
| METR-05 | 7 指标键存在于 report/metrics | unit | `pytest tests/test_eval.py -k process_metric -q` | ❌ Wave 0 |
| METR-06 | 同 key 二次 chat 命中；`--no-cache` 不写 | unit | `pytest tests/test_gateway.py -k cache -q` | ❌ Wave 0 |
| METR-07 | 有完整 ws 时不调用 rebuild（可通过计时/标记） | integration | `pytest tests/test_eval.py -k reuse -q` | ❌ Wave 0 |
| METR-08 | `--ablation` 产出四指标键；不改 skills 文件 | integration | `pytest tests/test_eval.py -k ablation -q` | ❌ Wave 0 |
| METR-09 | 基线文件 schema；realllm 排除 | unit + manual/realllm | `pytest -m realllm`（显式）+ 检查 `baseline/` | ❌ Wave 0（付费人工门） |
| PERF-01 | bench JSON 含 cost + p95 | unit/script | `pytest` 抽测 bench 聚合函数或 dry-run mock | ❌ Wave 0 |
| PERF-02 | ledger snapshot 含 cost；超限 ALERT | unit | `pytest tests/test_gateway.py -k ledger_cost -q` | ❌ Wave 0 |
| D-25 | 全量回归 | suite | `make test` | ✅ |

### Sampling Rate

- **Per task commit:** `make test-fast` + 相关单文件 pytest  
- **Per wave merge:** `make test`  
- **Phase gate:** `make test` 绿 +（人工）METR-09 baseline 落盘 + 仿真回归数=0  

### Wave 0 Gaps

- [ ] `tests/test_agent.py` — 零引用 `ok is False`、`dangling_rate is None`、`has_citations`（METR-01/02）
- [ ] `tests/test_obs_and_config.py` — skills/budget/llm/prompts 变异改 hash；env_checks 不变（METR-03）
- [ ] `tests/test_eval.py` — repeat 聚合、process metrics 键、coverage、reuse-workspace、ablation 代理指标（METR-04/05/07/08）
- [ ] `tests/test_gateway.py` — 磁盘缓存命中/旁路、finish_reason 审计字段、TokenLedger 成本与 ALERT（METR-06/PERF-02）
- [ ] `docs/CONFIG_HASH_HISTORY.md` — 非测试但与 NR-6 验收绑定
- [ ] `.venv` 安装 `scipy`（dev 依赖）— Wave 0 或 Plan 01 首任务
- [ ] （可选）`tests/test_eval_stats.py` — 若不想膨胀 test_eval，可新建平面文件；TESTING.md 倾向并入 `test_eval.py`

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | no（本地 CLI） | — |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | yes | 缓存键/params 经 `canonical_json`；路径限制在 `.cache/vela/llm/`；workspace 路径不穿越 |
| V6 Cryptography | yes（哈希非加密） | `hashlib.sha256` 做 cache key / config_hash；不手写哈希算法 |
| V7 Error Handling | yes | 缓存损坏 → 视为未命中并重建；reuse 失败显式重建/报错 |
| V8 Data Protection | yes | 仅缓存 **redact 后** 内容；禁止把 `.env` 写入 baseline；baseline 可含 config_hash/provider，不含 API key |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 缓存投毒/污染导致错误诊断 | Tampering | 键含 prompt_sha256+params+model；`--no-cache` 基线；损坏 JSON 丢弃 |
| 敏感日志进缓存 | Information Disclosure | 挂载点在 `Redactor.redact` 之后 |
| 成本告警被当成切断绕过 | Elevation/Denial | ALERT ≠ `BudgetExceeded`；硬切断阈值独立 |
| 评测路径 SQL 注入扫 ERROR | Tampering | 只经 `LogQueryAPI` |
| 基线报告被当作对外准确率 | Spoofing（流程） | 文件头强制「仿真回归门，非 G4 能力宣称」 |

## Recommended Implementation Order (for planner)

1. **Wave A — 闸门与指纹：** METR-01/02/03 + HISTORY.md + 兼容 None 的 eval/metrics  
2. **Wave B — 评测基础设施：** METR-04 stats、METR-05 过程指标、METR-06 缓存、METR-07 reuse、METR-08 ablation、PERF-02 ledger  
3. **Wave C — 真实基线（收尾）：** METR-09 + PERF-01 → 写 `baseline/`；Makefile/`realllm` 门；文档废止 44.4% 对比  

## Sources

### Primary (HIGH confidence)

- Context7 `/websites/scipy_doc_scipy`、`/scipy/scipy` — `t.interval` / `ttest_1samp.confidence_interval` / sem 用法  
- 本仓库源码：`citations.py`、`config.py::config_hash`、`eval/{runner,report,golden}.py`、`cli.py::cmd_eval`、`gateway/{base,budget,audit}.py`、`scripts/bench.py`、`evidence/pipeline.py`（reuse 判据）、`agent/{graph,skills,state}.py`（注入点与事件）  
- `.planning/phases/02-metrics-baseline/02-CONTEXT.md` D-01..D-26  
- `.planning/REQUIREMENTS.md` METR/PERF；`.planning/ROADMAP.md` Phase 2  
- `pip index versions` + `slopcheck install scipy numpy` → [OK]  
- 本机实测：`stats.t.interval(0.95, ...)` 返回合理区间；当前 `config_hash=sha256:32d709b34dfebf66…`  

### Secondary (MEDIUM confidence)

- explore-docs 过程指标与消融定义（RCA §4.5、KB §3.4）— 与 REQUIREMENTS 七项略有出入时以 REQUIREMENTS/CONTEXT 为准  
- 社区 SciPy CI 教程（参数名 `confidence` vs 旧 `alpha`）— 以本机 1.18 API 为准  

### Tertiary (LOW confidence)

- 事实句长度阈值、代理指标精确阈值 — `[ASSUMED]`，见 Assumptions Log  

## Metadata

**Confidence breakdown:**

- Standard stack: **HIGH** — PyPI + slopcheck + Context7 + 本机调用  
- Architecture: **HIGH** — 锚点文件已读；消融/缓存/reuse 注入点已核实  
- Pitfalls: **HIGH** — None 传播、audit 缺 finish_reason、退出码契约均来自代码实证  
- 代理指标公式: **MEDIUM** — 锁定「要代理」但具体式由 Discretion/研究推荐  

**Research date:** 2026-07-31  
**Valid until:** 2026-08-30（栈稳定；scipy 小版本浮动可忽略）

---

## RESEARCH COMPLETE

**Phase:** 02 - metrics-baseline  
**Confidence:** HIGH  

### Key Findings

1. 零引用今日 `ok=True`/`dangling_rate=0.0`——METR-01/02 必改；`None` 会炸 `EvalRunner.float()` 与 `Metrics.snapshot.round`，须同步兼容。  
2. `config_hash` 仅三 YAML；扩展 skills/budget/llm/prompts 并新建 `docs/CONFIG_HASH_HISTORY.md`（旧 hash 已测：`sha256:32d709b3…`）。  
3. 消融无需改 graph/YAML：用 `AgentGraph(skills=SkillRegistry(filtered))`；novel/calibration 用二元代理并标注。  
4. 缓存挂 `LLMGateway.chat` 脱敏后；stdlib JSON 文件即可；`Auditor` 需补 `finish_reason` 才能测 truncation。  
5. `--reuse-workspace` 判据：`gold/analysis.duckdb` + `manifest.json` + `qa/qa_report.json`。  
6. CI：`scipy.stats.t.interval(0.95, df=n-1, loc=mean, scale=sem)`；scipy 进 optional dev，`.venv` 需安装。  
7. 顺序铁律：METR-01~08+PERF-02 → 最后 METR-09/PERF-01 写 `baseline/`，废止 44.4%。  
8. D-24：禁止改推理；允许 citations/config_hash/eval/cli/gateway cache/TokenLedger/bench。  
9. 回归门：`make test` + 仿真回归数 0；新指标慎入 exit code。  
10. 无 `.cursor/rules`；遵循 AGENTS.md + TESTING.md（无 unittest.mock）。
