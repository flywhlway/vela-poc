# Phase 2: 度量可信与真实基线 - Research

**Researched:** 2026-07-31
**Domain:** 评测闸门 / 配置指纹 / 重复评测统计 / LLM 磁盘缓存 / 消融评测 / Token 成本归集 / 真实火山引擎基线
**Confidence:** HIGH

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
| METR-01 | 零引用报告质量闸门失败；`citation_coverage` 入报表 | 修 `CitationReport.ok`/`has_citations`；新增事实句切分 + coverage；eval/CLI 消费 `ok` |
| METR-02 | `dangling_rate` 在 `total==0` 返回 `None`；单测钉死 | 改 `citations.py` 属性与 `to_dict()`；更新 runner 聚合对 `None` 的处理 |
| METR-03 | config_hash 覆盖 skills/budget/llm/prompts；映射表承接断代 | 扩展 `config_hash()` payload；新建 `docs/CONFIG_HASH_HISTORY.md`；四类扰动单测 |
| METR-04 | `vela eval run --repeat N` → 均值±标准差与 95% t-CI | CLI 旗标 + `eval/stats.py`（scipy）+ 报表双层输出 |
| METR-05 | 7 项过程指标 + 决策轨迹表入报表 | eval 侧从 `DiagnosisResult.events` / state / report 聚合；不改 graph 控制流 |
| METR-06 | LLM 磁盘缓存键四元组；`--no-cache`；命中率 >90% | `LLMGateway.chat` 在脱敏后、provider 前查/写缓存 |
| METR-07 | `--reuse-workspace` 跳过已建成可用库 | `EvalRunner._one` 检查 `gold/analysis.duckdb` + `qa/qa_report.json.checks_passed` |
| METR-08 | 消融评测集 + 四泛化指标入 `_TARGETS` | 运行时 mask `expected_skills`；代理口径标注；`--ablation` 旗标 |
| METR-09 | `--no-cache` + volcengine N≥3 方差基线落盘 | 收尾人工/Makefile 目标；产物进 `baseline/`；取代 44.4% |
| PERF-01 | bench 覆盖真实 provider：token 成本 + P95 延迟 | 扩展 `scripts/bench.py`；与 METR-09 共用数据 |
| PERF-02 | TokenLedger 成本归集；超限 ALERT；单价入 config | 扩展 `budget.yaml` + `TokenLedger.snapshot()`；告警不替代硬切断 |
</phase_requirements>

## Summary

Phase 2 的本质是「先修尺子」：当前 `CitationReport` 在零引用时返回 `dangling_rate=0.0` 且 `ok=True`（F-01），`config_hash` 仅覆盖 pipeline/parsers/ota_phases（F-10），评测 runner 单次出数无置信区间（F-02），过程指标与消融集缺失，bench 只测 mock。本阶段按 ADR-2 **禁止改 `AgentGraph` 节点控制流与提示词诱导行为**，只改度量/指纹/评测/缓存/成本归集面，并在闸门口径稳定后用真实火山引擎跑 N≥3 无缓存基线。

代码面已具备可复用骨架：`CitationReport`/`verify_citations`、`EvalRunner`/`_TARGETS`/`cmd_eval`、`TokenLedger`、`LLMGateway.chat` 脱敏→预算→降级链、`SkillRegistry(skills=…)` 可注入、`qa_report.json.checks_passed`、`.cache/` 已在 `.gitignore`、`doctor --json` 指纹、`realllm` 默认排除。主要缺口是闸门语义、指纹覆盖、CLI 旗标、统计聚合、缓存钩子、过程/消融指标代理定义，以及基线产物目录。

**Primary recommendation:** 按「闸门+指纹 → 缓存/reuse/repeat/过程/消融/成本 → 收尾真实基线」顺序落地；scipy 作可选 `[eval]` 依赖算 t-CI；缓存挂在脱敏后的 `LLMGateway.chat`；消融用运行时 skill mask；基线写入 `.planning/phases/02-metrics-baseline/baseline/` 并宣告 44.4% 退役。

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 引用闸门语义 / citation_coverage | API / Backend（agent 确定性校验） | Eval 报表 | 程序化校验独立于模型；eval 消费 `ok`/`coverage` |
| config_hash 指纹 | API / Backend（config） | Evidence pack salt | hash 写入 runs / Merkle salt；断代文档在 docs |
| 重复评测 + t-CI | API / Backend（eval） | CLI | 纯本地统计，无浏览器层 |
| LLM 磁盘缓存 | API / Backend（gateway） | Filesystem `.cache/` | 出站路径唯一挂载点；须在脱敏后 |
| workspace 复用 | API / Backend（eval runner） | Database / Storage | 复用 Gold DuckDB + QA 标记 |
| 过程指标聚合 | API / Backend（eval） | Obs events | 不改 graph；从 events/state 聚合 |
| 消融评测 | API / Backend（eval） | Skills registry | 运行时 mask，不改 YAML |
| Token 成本归集 / 告警 | API / Backend（gateway budget） | Config YAML | 告警走 EventBus；硬切断语义不变 |
| 真实基线跑数 | API / Backend（CLI/Makefile） | External LLM | 付费、`--no-cache`、人工门 |
| doctor 指纹嵌入基线元数据 | CLI | — | 只读消费既有 JSON 契约 |

## Project Constraints (from .cursor/rules/)

仓库内无 `.cursor/rules/` 文件。以下约束来自 `AGENTS.md` / Phase 1 永久决策，planner 须同等遵守：

- Gold 库只经 `LogQueryAPI.call()`；本阶段消融/过程指标若查库须走门面或复用已开的 AgentGraph API，禁止直连 DuckDB。
- 配置驱动：成本单价/上限、缓存根目录覆盖放 `config/*.yaml` 或 env，业务不硬编码。
- Provider 只经 `gateway/base.py::Provider`；缓存不得引入 provider 专属分支。
- 程序化校验优先于模型自述；引用闸门修复属确定性路径。
- 图节点即方法；**禁止**在 `agent/nodes/` 建文件；**禁止**改 `graph.py` 控制流（D-24）。
- 不用 `logging`；结构化事件走 `EventBus`；CLI 用 `print()`。
- 三方库优先（D-01）；本地优先，不引入必须联网才能跑通主链路的依赖。
- 出站脱敏必须保留；缓存键基于脱敏后 prompt。
- 完成判据：`make test-fast`；涉及评测/网关须 `make test`；付费用 `realllm` 排除。

## Current State & Gaps

### 引用闸门（F-01）— VERIFIED

```27:37:src/vela/agent/citations.py
    @property
    def dangling_rate(self) -> float:
        return round(len(self.dangling) / self.total, 4) if self.total else 0.0

    @property
    def ok(self) -> bool:
        return not self.dangling
```

- `total==0` → `dangling_rate=0.0`、`ok=True`：零引用报告「满分」。[VERIFIED: codebase]
- `to_dict()` 无 `has_citations`；`node_report` 写 `st.citation_check = rep.to_dict()` 但不因 `ok` 改 status（符合 D-04，Phase 2 不改重试）。[VERIFIED: codebase]
- `EvalRunner`：`cr.dangling_rate = float(...get("dangling_rate", 0.0))` —— `None` 会炸；`metrics()` 对 dangling 做简单均值，未消费 `ok`/`has_citations`/`citation_coverage`。[VERIFIED: codebase]
- `cmd_eval` 退出码用 `dangling_citation_rate <= 0.015`，不检查 `has_citations`。[VERIFIED: codebase]
- 现有单测覆盖悬空/合法引用，**无** `total==0` 分支钉死。[VERIFIED: tests/test_agent.py]

### config_hash（F-10）— VERIFIED

```186:204:src/vela/config.py
def config_hash() -> str:
    payload = canonical_json({
        "pipeline": load_yaml("pipeline.yaml"),
        "parsers": load_yaml("parsers.yaml"),
        "phases": load_yaml("ota_phases.yaml"),
        "canon_rules_version": canon_rules_version(),
        "algos": fingerprint_algos(),
    })
```

- 未纳入：`config/skills/*.yaml`（经 `load_skills()`）、`budget.yaml`、`llm.yaml`、`gateway/prompts.py`。[VERIFIED: codebase]
- `env_checks.yaml` 本就不在 payload（保持 D-06）。[VERIFIED: codebase]
- `docs/CONFIG_HASH_HISTORY.md` 不存在。[VERIFIED: filesystem]
- 单测仅断言确定性与 `sha256:` 格式，无扰动断言。[VERIFIED: tests/test_obs_and_config.py]

### 评测 runner / CLI — VERIFIED

- `EvalRunner._one` **总是** `build_evidence_db`；无 reuse、无 repeat、无 ablation、无 cache 旗标。[VERIFIED: codebase]
- `cmd_eval` / argparse 仅 `--dataset/--workspace/--out/--provider/--profile`。[VERIFIED: codebase]
- `_TARGETS` 6 项，无过程/消融/coverage 目标。[VERIFIED: eval/report.py]
- `CaseResult` 无过程字段；`RoundRecord` 无 stop/verdicts/finish_reason。[VERIFIED: codebase]

### 缓存 — VERIFIED

- 网关无磁盘缓存；`.gitignore` 已有 `.cache/`。[VERIFIED: codebase + .gitignore]
- `Auditor` 已算 `prompt_sha256`，但不写响应体、不记 `finish_reason`。[VERIFIED: gateway/audit.py]

### TokenLedger / bench — VERIFIED

- `TokenLedger`：tokens 累计 + `BudgetExceeded`；无成本估算/上限告警。[VERIFIED: gateway/budget.py]
- `budget.yaml`：无单价、无诊断成本上限段。[VERIFIED: config/budget.yaml]
- `scripts/bench.py`：建库吞吐 + 诊断延迟 P50/P95；默认 provider=None（走配置，常为 mock）；无 token 成本、无 volcengine 专用路径、无 `--no-cache`。[VERIFIED: scripts/bench.py]

### 过程指标数据源缺口 — VERIFIED

| 指标 | 现有信号 | Phase 2 聚合策略（不改 graph 控制流） |
|------|----------|----------------------------------------|
| premature_stop_rate | `events` 中 `plan.done` 含 `stop` + `round_no` | 会话在 `round_no<=1` 且 `stop=True` 的占比 |
| llm_parse_failure_rate | `_parse_json` 失败静默返回 `{}`，无计数器 | **代理**：`plan.done` 且 `skill is None` 且 `stop=False` 且 actions 空；报表标注代理 |
| llm_truncation_rate | `LLMResponse.finish_reason` 存在但未入 audit | **允许**在 gateway/audit 记录 `finish_reason`（非推理逻辑）；再聚合 `length` 占比 |
| verdict_supported_ratio | `verify.done` 事件含 `supported`/`claims` | `sum(supported)/sum(claims)` |
| skill_switch_per_session | `st.used_skills` / rounds | 相邻 round `selected_skill` 变化次数均值 |
| unexplained_error_rate | 无现成字段 | **代理**：结论后 ERROR 行未进入 evidence_pool 的占比（经 `LogQueryAPI`）；或消融专用定义 |
| citation_coverage | 无 | 对 `report_md` 跑新切分函数 |

[VERIFIED: graph events emit sites + state.py + RCA §4.5]

### 消融 — VERIFIED

- `SkillRegistry(skills=…)` / `AgentGraph(..., skills=)` 已支持注入。[VERIFIED: skills.py / graph.py `__init__`]
- golden `expected_skills` 可作 mask 清单。[VERIFIED: golden.py]
- 无消融 runner / 四指标。[VERIFIED: eval/]

## Discretion Recommendations（Claude's Discretion → 钉死建议）

| 灰区 | 建议 | 理由 |
|------|------|------|
| 事实句切分 | 分隔符类 `[。！？.!?\n]+`；丢弃空白行；丢弃 `^\s*#{1,6}\s` 标题行与 `^\s*[-*_]{3,}\s*$` 分隔线；句子内存在 `CITE_RX` 即计覆盖 | 确定性、中英混排；易单测 |
| 缓存格式 | 单文件 blob：`.cache/vela/llm/<key_sha256>.json`，内容 `{response_text, meta, created_at}`；无 LRU（POC 磁盘便宜）；`VELA_LLM_CACHE_DIR` 可覆盖根 | 实现简单；命中可测 |
| 消融 CLI | `vela eval run --ablation` **旗标**（非新子命令） | 复用 runner/报表路径 |
| hash 历史表列 | `date \| old_hash \| new_hash \| added_inputs \| reason` | 与 D-07 对齐 |
| t-CI | **scipy.stats.t.interval**（可选依赖 `eval`） | D-01 + Context7 官方 API；N=2 时 df=1 仍合法 |
| bench/eval 共用 | 抽出 `vela.eval.stats`（mean/std/ci）与成本读取 helper；bench 调用，不强制 bench 走完整 EvalRunner | 避免重复付费采集逻辑分叉 |

## Standard Stack

### Core（已在项目中）

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | ≥3.11（环境 3.12.13） | 运行时 | 项目约束 [VERIFIED: pyproject + `python3 --version`] |
| PyYAML | ≥6.0 | 配置/技能加载 | 已有 [VERIFIED: pyproject.toml] |
| pytest | ≥8.0 | 测试 | 已有 [VERIFIED: pyproject.toml] |
| openai | ≥1.40 | 火山引擎方舟 | Phase 1 已接入 [VERIFIED: pyproject.toml] |

### Supporting（本阶段新增）

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| scipy | 1.18.0（PyPI 当前） | `scipy.stats.t.interval` / `sem` | 仅 `--repeat N` 与基线聚合 [VERIFIED: `pip index versions scipy`] |
| numpy | 2.5.1（PyPI 当前；scipy 依赖） | scipy 传递依赖 | 随 scipy 安装 [VERIFIED: pip index] |

**Installation（推荐可选 extra，不污染离线主链路）：**

```bash
# pyproject.toml
# [project.optional-dependencies]
# eval = ["scipy>=1.11"]
# dev = ["pytest>=8.0", "scipy>=1.11"]
pip install -e ".[dev]"
```

无 `--repeat` 时主链路不 import scipy；`--repeat`/`make baseline` 若缺包则清晰报错提示安装 `[eval]`。

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| scipy t.interval | 手写 t 临界值表 | 违反 D-01；易错；CONTEXT 允许但非优选 |
| scipy | 仅 statistics.stdev + 查表 | 无官方 CI API；小样本脆弱 |
| 磁盘 blob 缓存 | SQLite / JSONL append-only | 过重；命中查找更复杂 |
| `--ablation` 旗标 | `vela eval ablation` 子命令 | 多分叉；报表路径重复 |

**Version verification:** scipy 1.18.0 / numpy 2.5.1 via `pip index versions` on 2026-07-31. [VERIFIED: PyPI via pip]

## Package Legitimacy Audit

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| scipy | PyPI | 15+ yrs | 极高（科学计算标配） | github.com/scipy/scipy | [OK] | Approved — 建议 optional `[eval]` |
| numpy | PyPI | 15+ yrs | 极高 | github.com/numpy/numpy | [OK] | Approved — scipy 传递依赖 |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

*slopcheck 0.6.1 `slopcheck install scipy numpy` → 2 OK。Context7 文档库 `/websites/scipy_doc_scipy` 确认 `stats.t.interval` 用法。* [VERIFIED: slopcheck + Context7]

## Architecture Patterns

### System Architecture Diagram

```text
                    ┌─────────────────────────────────────────┐
                    │  CLI: vela eval run                     │
                    │  [--repeat N] [--reuse-workspace]       │
                    │  [--no-cache] [--ablation] [--provider] │
                    └───────────────────┬─────────────────────┘
                                        │
                    ┌───────────────────▼─────────────────────┐
                    │  EvalRunner                             │
                    │  for case in golden:                    │
                    │    reuse? → gold/analysis.duckdb + QA   │
                    │    else build()                         │
                    │    skills = mask(expected) if ablation  │
                    │    AgentGraph.run()                     │
                    │    aggregate citations/process metrics  │
                    └───────────┬─────────────┬───────────────┘
                                │             │
              ┌─────────────────▼──┐   ┌──────▼──────────────┐
              │ CitationReport     │   │ DiagnosisResult     │
              │ ok/has_citations/  │   │ events + state +    │
              │ coverage           │   │ gateway_stats/cost  │
              └────────────────────┘   └──────┬──────────────┘
                                              │
                    ┌─────────────────────────▼──────────────┐
                    │ LLMGateway.chat                        │
                    │  redact → cache lookup → precheck →    │
                    │  provider.complete → charge ledger →   │
                    │  cache store                           │
                    └─────────────────────────▲──────────────┘
                                              │
                              .cache/vela/llm/<key>.json
                                              │
                    ┌─────────────────────────▼──────────────┐
                    │ report.py: _TARGETS + process +        │
                    │ ablation + (optional) repeat aggregate │
                    │ → eval_report.md / eval_result.json    │
                    └─────────────────────────┬──────────────┘
                                              │ METR-09/PERF 收尾
                    ┌─────────────────────────▼──────────────┐
                    │ baseline/{report.md, result.json}      │
                    │ + doctor --json fingerprint            │
                    └────────────────────────────────────────┘
```

### Recommended Project Structure

```
src/vela/
├── agent/citations.py          # dangling_rate/ok/has_citations + coverage
├── config.py                   # config_hash 扩展
├── gateway/
│   ├── base.py                 # chat 缓存钩子
│   ├── budget.py               # TokenLedger 成本归集
│   ├── cache.py                # NEW: 磁盘缓存读写
│   ├── audit.py                # 可选：finish_reason 入审计
│   └── prompts.py              # 纳入 hash（内容不变）
├── eval/
│   ├── runner.py               # reuse / ablation / 过程字段
│   ├── report.py               # _TARGETS + 轨迹表 + 聚合行
│   ├── stats.py                # NEW: mean/std/t-CI
│   ├── process.py              # NEW: 7 项过程指标聚合
│   └── golden.py               # 不变
├── cli.py                      # eval 旗标
config/budget.yaml              # cost 段
docs/CONFIG_HASH_HISTORY.md     # NEW
scripts/bench.py                # volcengine + 成本
.planning/phases/02-metrics-baseline/baseline/  # 基线产物
tests/test_agent.py / test_eval.py / test_obs_and_config.py / test_gateway.py
```

### Pattern 1: 度量侧闸门，不改推理

**What:** 只改 `CitationReport` 语义与 eval 消费；`node_report` 仍写报告，不重试、不改 status 机。
**When to use:** 全程 Phase 2。
**Example:**

```python
# 目标语义（D-01/D-02）
@property
def dangling_rate(self) -> float | None:
    if self.total == 0:
        return None
    return round(len(self.dangling) / self.total, 4)

@property
def has_citations(self) -> bool:
    return self.total > 0

@property
def ok(self) -> bool:
    return self.has_citations and not self.dangling
```

### Pattern 2: 缓存挂在脱敏之后

**What:** `chat()` 在 redaction 完成后、`precheck`/`complete` 前查缓存；命中仍 `ledger.charge`（避免缓存绕过预算——**推荐命中也计量**，与「可观测成本」一致；若 planner 选「命中不计量」须在威胁分析中说明）。
**When to use:** METR-06。
**Recommendation:** 命中**仍 charge**（用缓存响应中的 token 计数或估算），这样 `--no-cache` 基线与有缓存迭代的成本口径一致区分「API 成本」vs「计量成本」；报表可另计 `cache_hits`。若需「命中不计 API 成本」，在 snapshot 加 `cache_hit: bool` 字段。

**威胁要点：** 缓存明文响应可含日志摘要——目录须 gitignore；键含脱敏后 prompt_sha256，禁止缓存未脱敏内容。

### Pattern 3: 消融运行时 mask

**What:**

```python
skills = load_skills()
masked = [s for s in skills if s["id"] not in set(gc.expected_skills)]
registry = SkillRegistry(skills=masked)
g = AgentGraph(..., skills=registry)
```

**When to use:** `--ablation`；健康场景（无 expected_skills）跳过或计入对照。

### Pattern 4: Student t 95% CI

```python
# Source: https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.t.html
from scipy import stats
import numpy as np

def mean_std_ci(vals: list[float], confidence: float = 0.95) -> dict:
    a = np.asarray(vals, dtype=float)
    n = len(a)
    mean = float(a.mean())
    if n < 2:
        return {"mean": mean, "std": 0.0, "ci95": [mean, mean], "n": n}
    std = float(a.std(ddof=1))
    sem = stats.sem(a)
    lo, hi = stats.t.interval(confidence, df=n - 1, loc=mean, scale=sem)
    return {"mean": mean, "std": std, "ci95": [float(lo), float(hi)], "n": n}
```

[CITED: docs.scipy.org — scipy.stats.t.interval / sem]

### Anti-Patterns to Avoid

- **在 graph 里为过程指标加守卫/重试：** 属 Phase 3；本阶段只聚合。
- **为 novel_detection 实现 CONF-03：** 违反 D-17。
- **缓存未脱敏 prompt：** 安全违规。
- **reuse 半成品库：** 缺 `analysis.duckdb` 或 `checks_passed=false` 必须重建或显式失败。
- **把仿真基线写成能力宣称：** 违反 ADR-3 / D-18。
- **用手写 t 表替代 scipy：** 违反 D-01（除非 scipy 安装失败的降级文档化路径）。
- **修改 `env_checks.yaml` 却期望 hash 变：** 不得纳入（D-06）。

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Student t CI | 自建临界值表 / 正态近似 | `scipy.stats.t.interval` + `sem` | 小样本 N=3 时正态近似偏差大；D-01 |
| 引用提取 | 新解析器 | 既有 `CITE_RX` / `extract_citations` | 已覆盖 inline+trailer |
| 技能加载 | 重写 loader | `load_skills()` + `SkillRegistry(skills=)` | 已稳定排序与注入 |
| 配置指纹 | 自定义 hash 框架 | `canonical_json` + sha256 扩 payload | 模式已存在 |
| LLM 缓存 | Redis/服务 | 本地文件 blob | 本地优先 |
| 成本计量 | 平行账本类 | 扩展 `TokenLedger` | 单一计量源 |

**Key insight:** 本阶段复杂度在「口径与聚合」，不在新基础设施——复用现有门面可把 diff 压在评测与闸门层。

## Runtime State Inventory

> 指纹语义迁移（非改名，但影响已落盘证据包可比性）

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | 既有 workspace 证据包 `run.config_hash` / Merkle salt 用旧口径 | 文档记录断代；**不**批量重算历史包；新 run 自动用新 hash |
| Live service config | 无外部服务 | None — verified（本地优先） |
| OS-registered state | 无 | None — verified |
| Secrets/env vars | `VELA_LLM_PROVIDER` / Ark 凭证；可选 `VELA_LLM_CACHE_DIR` | 新增 cache env 写入 `.env.example` 注释；不改密钥名 |
| Build artifacts | `.cache/vela/`（新）；旧 duckdb 仍可用 | `.gitignore` 已覆盖 `.cache/`；reuse 依赖 QA 标记 |

## Common Pitfalls

### Pitfall 1: F-01 零引用悖论残留在聚合层
**What goes wrong:** 修了属性但 `float(None)`、均值把 `None` 当 0、退出码仍只看 rate。
**Why it happens:** runner/CLI/metrics.gauge 假定 rate 为 float。
**How to avoid:** `dangling_citation_rate` 改为「有引用用例的平均悬空率」；另报 `zero_citation_cases` / `citation_gate_pass_rate`；`gauge` 跳过 None。
**Warning signs:** 单测只改 citations.py、eval 绿但 CLI 崩。

### Pitfall 2: F-10 / NR-6 指纹断代未建账
**What goes wrong:** hash 变了但无映射表，历史证据包「看似同源」。
**How to avoid:** 与代码同 PR 交付 `docs/CONFIG_HASH_HISTORY.md` 首行；单测读 prompts/skills 扰动。
**Warning signs:** 只改 `config.py`、docs 空缺。

### Pitfall 3: NR-1 基线下降被当回归
**What goes wrong:** 引用闸门生效后 top1 低于 44.4%，被误回滚。
**How to avoid:** 基线报告醒目标注「仿真回归门、非能力」；回归门仍是 mock 已通过用例数=0 + 177 tests；禁止用 44.4% 对比。
**Warning signs:** PR 描述写「准确率回退」。

### Pitfall 4: 缓存破坏 determinism / 掩盖方差
**What goes wrong:** determinism 测试读到脏缓存；基线误开缓存。
**How to avoid:** 默认测试 `VELA_LLM_CACHE=0` 或 cache 仅显式开启；METR-09 强制 `--no-cache`；缓存键含 physical_model+params。
**Warning signs:** 同输入二次 mock 结果漂移或基线方差≈0。

### Pitfall 5: reuse 半成品库
**What goes wrong:** 只有部分 parquet、无 QA，诊断诡异失败。
**How to avoid:** 复用条件：`gold/analysis.duckdb` 存在 **且** `qa/qa_report.json` 中 `checks_passed is True`；否则 rebuild。
**Warning signs:** `--reuse-workspace` 后大量 BUILD 无、诊断空库。

### Pitfall 6: 退出码契约被新指标破坏
**What goes wrong:** mock 黄金评测 exit 4，CI 红。
**How to avoid:** D-25——新指标入报表但不加入 `cmd_eval` 硬退出条件，除非同步改测试且回归数仍为 0；过程/消融目标「展示但不门禁」。
**Warning signs:** `make eval` 在 mock 下非 0。

### Pitfall 7: 过程指标引诱改 graph
**What goes wrong:** 为让 `llm_parse_failure_rate`「真实」而改 `_parse_json`。
**How to avoid:** 代理口径 + 报表脚注；计数器发射留给 Phase 3。
**Warning signs:** diff 触及 `graph.py` 控制流。

## Code Examples

### 扩展 config_hash

```python
# 目标 payload 键（D-05/D-06）
payload = canonical_json({
    "pipeline": load_yaml("pipeline.yaml"),
    "parsers": load_yaml("parsers.yaml"),
    "phases": load_yaml("ota_phases.yaml"),
    "budget": load_yaml("budget.yaml"),
    "llm": load_yaml("llm.yaml"),
    "skills": load_skills(),  # 或按文件原始文本哈希，须与 load_skills 同源
    "prompts_sha256": hashlib.sha256(
        Path(__file__).resolve().parent.joinpath("gateway/prompts.py")
        .read_bytes()
    ).hexdigest(),
    "canon_rules_version": canon_rules_version(),
    "algos": fingerprint_algos(),
})
# 明确不读 env_checks.yaml
```

### reuse-workspace 判定

```python
def _workspace_reusable(ws: Path) -> bool:
    db = ws / "gold" / "analysis.duckdb"
    qa = ws / "qa" / "qa_report.json"
    if not db.exists() or not qa.exists():
        return False
    data = read_json(qa)
    return bool(data.get("checks_passed"))
```

### 消融代理指标（D-17）

```python
# 报表必须标注：代理口径，Phase 5 后替换
# misdiagnosis: ablation 下 status==answered 且 predicted 不在 {None, undetermined, no_fault_found}
# novel_detection_recall: ablation 下「正确拒绝」=
#   status in {unanswerable, human_gate} OR _no_fault(predicted_label)
# confidence_calibration_error: 二元 ECE 代理
#   conf = 1.0 if status==answered else 0.0
#   | mean(correct) - mean(conf) |  （correct 定义与 top1/拒绝一致性对齐）
```

### TokenLedger 成本扩展

```yaml
# config/budget.yaml 新增段（示例）
cost:
  # 单位：USD / 1K tokens（占位，按方舟实际单价改）
  input_per_1k: 0.0
  output_per_1k: 0.0
  diagnose_cost_alert: 1.0   # 单次诊断估算成本告警阈值；不替代 token 硬切断
```

## File-Level Change Map

| File | Change | Reqs |
|------|--------|------|
| `src/vela/agent/citations.py` | `dangling_rate`/`ok`/`has_citations`；`citation_coverage()` / 事实句切分；`to_dict` | METR-01/02 |
| `src/vela/config.py` | `config_hash` 扩 payload | METR-03 |
| `docs/CONFIG_HASH_HISTORY.md` | 新建断代表 | METR-03 |
| `src/vela/gateway/cache.py` | **NEW** 磁盘缓存 | METR-06 |
| `src/vela/gateway/base.py` | chat 挂缓存；可选 cache stats | METR-06 |
| `src/vela/gateway/audit.py` | 记录 `finish_reason`（过程指标） | METR-05 |
| `src/vela/gateway/budget.py` | 成本累计、snapshot 字段、超限 ALERT 钩子 | PERF-02 |
| `config/budget.yaml` | `cost:` 段 | PERF-02 |
| `src/vela/eval/stats.py` | **NEW** t-CI | METR-04 |
| `src/vela/eval/process.py` | **NEW** 7 项聚合 + 轨迹 | METR-05 |
| `src/vela/eval/runner.py` | reuse / ablation / 过程字段 / None-safe dangling | METR-04/05/07/08 |
| `src/vela/eval/report.py` | `_TARGETS` 扩展；过程/消融/聚合行；代理脚注 | METR-01/05/08 |
| `src/vela/cli.py` | `--repeat/--reuse-workspace/--no-cache/--ablation`；exit 契约审慎 | METR-04/06/07/08 |
| `scripts/bench.py` | volcengine、成本、P95、no-cache | PERF-01 |
| `pyproject.toml` | optional `eval`/`dev` + scipy | METR-04 |
| `.env.example` | cache/cost 相关注释 | METR-06 |
| `Makefile` | `baseline` / `eval-repeat` 目标（付费显式） | METR-09 |
| `tests/test_agent.py` | total==0、coverage 边界 | METR-01/02 |
| `tests/test_obs_and_config.py` | 四类 hash 扰动；env_checks 不变 | METR-03 |
| `tests/test_eval.py` | repeat 聚合、reuse、ablation、过程字段 | METR-04/05/07/08 |
| `tests/test_gateway.py` | 缓存命中、`--no-cache`、成本 snapshot | METR-06 / PERF-02 |
| `.planning/phases/02-metrics-baseline/baseline/*` | 收尾产物（人工跑） | METR-09 / PERF-01 |
| **禁止** `src/vela/agent/graph.py` 控制流 / prompts 语义 | — | D-24 |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 单次评测点估计 | `--repeat N` + t-CI | Phase 2 | 行为调优可检验 |
| dangling_rate 零引用=0.0 | None + has_citations 门 | Phase 2 | 旗舰闸门恢复意义 |
| config_hash 窄覆盖 | skills/budget/llm/prompts | Phase 2 | 证据包可区分优化版本 |
| 无 LLM 缓存 | 本地四元组磁盘缓存 | Phase 2 | 迭代成本可承受 |
| 44.4% 口头基线 | `baseline/` 带 CI 报告 | Phase 2 收尾 | NR-1：旧数字退役 |

**Deprecated/outdated:**
- 以 44.4% 作为 Phase 3+ 对比基线：本阶段完成后禁止。[CITED: ROADMAP NR-1 / CONTEXT D-19]
- 将 `dangling_citation_rate=0.0` 解读为「引用质量完美」而无视 `has_citations`。[CITED: explore-docs F-01]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 缓存命中仍应对 TokenLedger charge（用缓存内 token 数） | Pattern 2 | 成本口径与「API 账单」不一致；可改为分字段 |
| A2 | `llm_parse_failure_rate` 用 plan.done 空技能代理足够「可测」 | Gaps | Phase 3 前指标偏噪；已要求脚注 |
| A3 | 方舟单价占位 0.0，基线以 token 为主、金额为辅直到填实 | PERF-02 | 金额基线无意义；token/P95 仍可用 |
| A4 | 健康场景在 `--ablation` 下跳过 mask（无 expected_skills） | METR-08 | 分母定义需报表写清 |

**若需用户确认：** A1（缓存是否计量）影响 PERF 数字解读；其余为可脚注代理。

## Open Questions

1. **缓存命中是否计入 session token / 成本？**
   - What we know: D-12/D-13 要求不改业务语义、可关缓存；未钉死计量。
   - Recommendation: 命中仍 charge + 增加 `cache_hits` 计数；基线 `--no-cache` 不受影响。

2. **`cmd_eval` 退出码是否纳入 `has_citations`？**
   - What we know: D-25 要求不破坏 mock 契约。
   - Recommendation: mock reporter 通常有引用 → 可加 `citation_gate_pass_rate==1` 到 exit；若 mock 偶发零引用则仅报表告警、exit 仍用原四条件。实现前用现有 mock 黄金跑一次确认。

3. **scipy 放必需还是可选？**
   - Recommendation: optional `[eval]`/`dev`；CI `make test` 若测 CI 函数则 dev 安装须含 scipy（`make install-dev` 已装 dev）。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | 全阶段 | ✓ | 3.12.13 | — |
| scipy | METR-04 CI | ✓（研究机已装 1.18.0） | 1.18.0 | 可选依赖；缺则 `--repeat` 报错 |
| numpy | scipy | ✓ | 2.4.6+ / PyPI 2.5.1 | 随 scipy |
| 火山引擎凭据 | METR-09/PERF-01 | 视 `.env` | — | 人工门；无凭据则跳过收尾、基础设施仍可验收 |
| DuckDB workspace | reuse/eval | ✓ 本地样例存在 | — | 无则 build |

**Missing dependencies with no fallback:**
- 无（真实基线缺凭据时降级为「基础设施验收通过、基线产物人工补跑」）

**Missing dependencies with fallback:**
- scipy → 声明为 `[eval]` 可选；单测在未安装时 skip CI 专用用例（或 install-dev 纳入）

Step 2.6: 外部依赖已审计（本地 Python 栈 + 可选付费 LLM）。

## Validation Architecture

> `workflow.nyquist_validation` 未在 `.planning/config.json` 显式关闭 → 启用。

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest ≥8.0 |
| Config file | `pyproject.toml` → `[tool.pytest.ini_options]` |
| Quick run command | `make test-fast` |
| Full suite command | `make test` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| METR-01 | 零引用 `ok is False`；coverage 计算 | unit | `pytest tests/test_agent.py -k citation -q` | ✅ 扩展 |
| METR-02 | `total==0` → `dangling_rate is None` | unit | `pytest tests/test_agent.py -k 'zero_citation or total' -q` | ❌ Wave 0 |
| METR-03 | 四类扰动 hash 变；env_checks 不变 | unit | `pytest tests/test_obs_and_config.py -k config_hash -q` | ✅ 扩展 |
| METR-04 | repeat 聚合含 ci95 | unit | `pytest tests/test_eval.py -k repeat -q` | ❌ Wave 0 |
| METR-05 | metrics 含 7 过程键 + 轨迹 | unit | `pytest tests/test_eval.py -k process -q` | ❌ Wave 0 |
| METR-06 | 同键二次 chat 命中；no-cache 不写 | unit | `pytest tests/test_gateway.py -k cache -q` | ❌ Wave 0 |
| METR-07 | reuse 跳过 build；坏 QA 重建 | unit | `pytest tests/test_eval.py -k reuse -q` | ❌ Wave 0 |
| METR-08 | ablation mask + 四指标键存在 | unit | `pytest tests/test_eval.py -k ablation -q` | ❌ Wave 0 |
| METR-09 | 方差基线产物格式 | manual / realllm | `pytest -m realllm` 或 `make baseline` | ❌ 人工门 |
| PERF-01 | bench JSON 含 cost + p95 | unit/smoke mock | `pytest tests/test_cli_and_server.py -k bench` 或脚本 mock | ❌ Wave 0 |
| PERF-02 | ledger snapshot 含 estimated_cost；超限 emit | unit | `pytest tests/test_gateway.py -k cost -q` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `make test-fast` + 相关单文件 pytest
- **Per wave merge:** `make test`
- **Phase gate:** `make test` 绿 + mock 黄金回归数 0；METR-09/PERF-01 人工基线落盘

### Wave 0 Gaps

- [ ] `tests/test_agent.py` — `test_zero_citation_report_fails_quality_gate`；`test_citation_coverage_*` 边界表
- [ ] `tests/test_obs_and_config.py` — skills/budget/llm/prompts 扰动；env_checks 负例
- [ ] `tests/test_eval.py` — repeat/reuse/ablation/process 报表键
- [ ] `tests/test_gateway.py` — cache 命中率、cost alert、finish_reason 审计
- [ ] `make install-dev` 确保 scipy 在 dev extra（若 CI 跑 stats 单测）
- [ ] 基线目录占位 README（可选）：说明须 `--no-cache` + volcengine

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no（本地 CLI） | — |
| V3 Session Management | no | — |
| V4 Access Control | partial | 租户谓词既有；本阶段不改 |
| V5 Input Validation | yes | 缓存键/params 规范化；eval CLI 参数校验 N≥2 |
| V6 Cryptography | yes（hash） | sha256 via stdlib；不手写哈希算法 |
| V7 Error Handling | yes | 缓存损坏 → miss 重建；QA 失败不 silent reuse |
| V8 Data Protection | yes | 缓存仅存脱敏后流量；`.cache/` gitignore；禁止提交 `.env` |

### Known Threat Patterns for this phase

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 缓存未脱敏日志片段 | Information Disclosure | 缓存点必须在 `Redactor.redact` 之后 |
| 缓存投毒（篡改 blob） | Tampering | 键绑定 prompt_sha256；损坏 JSON → miss；不信任缓存改业务分支 |
| 预算绕过（缓存跳过 charge） | Elevation of Privilege（配额） | 命中仍 charge 或显式分字段审计 |
| 指纹遗漏导致证据包不可审计 | Repudiation | D-05 扩覆盖 + HISTORY 表 |
| 付费基线误入 CI | — | `realllm` addopts 排除；Makefile 显式目标 |

## Sources

### Primary (HIGH confidence)

- 代码库：`citations.py` / `config.py` / `eval/*` / `gateway/*` / `cli.py` / `scripts/bench.py` / `budget.yaml` — 2026-07-31 实读
- Context7 `/websites/scipy_doc_scipy` — `stats.t.interval` / `sem` / Student t CI
- `.planning/phases/02-metrics-baseline/02-CONTEXT.md` — 锁定决策 D-01..D-26
- `.planning/ROADMAP.md` Phase 2 / `.planning/REQUIREMENTS.md` METR/PERF
- `explore-docs/VELA-多专家联合评审与系统性优化改造方案.md` — F-01/F-02/F-10/NR-1/NR-6/C-01..C-14
- `AGENTS.md` / `.planning/codebase/TESTING.md` — 测试与架构铁律
- slopcheck + `pip index versions` — scipy/numpy

### Secondary (MEDIUM confidence)

- `explore-docs/VELA-真实LLM准确率归因分析与优化方案.md` §4.5 — 过程指标清单
- `explore-docs/VELA-技能知识库深度分析报告.md` §3.4 — 消融四指标

### Tertiary (LOW confidence)

- 方舟具体 token 单价（须运维填入 `budget.yaml`，研究时未验证账单）— [ASSUMED] A3

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 复用现有栈 + scipy 经 PyPI/slopcheck/Context7
- Architecture: HIGH — 触碰面由 CONTEXT D-24 钉死，代码锚点已核对
- Pitfalls: HIGH — F-01/F-10/NR-1 来自探索文档并与代码行为吻合
- 代理指标数学细节: MEDIUM — 可测但 Phase 5 前非最终口径（已脚注）

**Research date:** 2026-07-31
**Valid until:** 2026-08-30（栈稳定；方舟单价/API 变更时重验 PERF 配置）
