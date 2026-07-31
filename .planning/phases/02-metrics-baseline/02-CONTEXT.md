# Phase 2: 度量可信与真实基线 - Context

**Gathered:** 2026-07-31
**Status:** Ready for planning
**Mode:** `--auto`（全部灰区自动选中；每题取 recommended/第一选项）

<domain>
## Phase Boundary

修正评测体系本身并在真实火山引擎 LLM 上建立带置信区间的准确率、成本、延迟基线（METR-01..09、PERF-01、PERF-02）。

**硬锁定（ADR-2）**：本阶段**不改任何推理逻辑**——不触碰 `AgentGraph` 节点行为、技能召回/剔除策略、verifier/reporter 提示词语义、提取器、置信度模型。只改「尺子」：引用闸门语义、指纹覆盖、评测 runner/报表、缓存与 workspace 复用、消融可测性、TokenLedger 成本归集与 bench。

**阶段内顺序（ROADMAP 已定）**：先落地 METR-01~08 与 PERF-02 的指标/闸门基础设施；METR-09 与 PERF-01 作为收尾，在口径确定后、`--no-cache` + 真实 LLM 下最后跑，确保基线反映修正后的闸门。

**明确不做**：ORCH/DECP/CONF/SKIL/DUAL 行为修复；G4 真实标注集；用仿真分数对外宣称真实准确率；任何 pp 收益承诺。

</domain>

<decisions>
## Implementation Decisions

### 引用闸门语义（METR-01 / METR-02）

- **D-01:** `CitationReport.dangling_rate` 在 `total == 0` 时返回 `None`（不再返回 `0.0`）；新增 `has_citations: bool`（`total > 0`）。
- **D-02:** `CitationReport.ok` 在零引用时为 `False`（`has_citations` 为假即质量闸门失败）；有引用且无悬空才为 `True`。零引用报告必须被强制判失败——有专门单测钉住 `total==0` 分支。
- **D-03:** `citation_coverage` = 含至少一个 `[[EV:…]]` 的事实句数 / 事实句总数。事实句切分用**确定性启发式**（中英文句号/换行；空行与纯标题行不计），细则由 planner 钉死并单测；指标进入评测报表与 `_TARGETS`（G1 目标线 ≥ 0.9 仅作报表目标，本阶段不因未达标阻断回归门以外的交付——回归门仍是 177 测试 + 仿真已通过用例回归数 = 0）。
- **D-04:** 本阶段**只修度量侧闸门/指标**；reporter 侧「引用不足重试」（ORCH-08 / C-03）属 Phase 3，禁止在本阶段改 `node_report` 推理行为。评测/校验路径消费修正后的 `ok`/`has_citations` 即可让零引用报告在质量闸门上失败。

### config_hash 覆盖与指纹断代（METR-03 / NR-6）

- **D-05:** `config_hash()` payload **扩展纳入**：`config/skills/*.yaml`（或现有 skills 加载路径下全部技能 YAML）、`budget.yaml`、`llm.yaml`、`gateway/prompts.py` 的内容哈希；**保留**既有 `pipeline.yaml` / `parsers.yaml` / `ota_phases.yaml` / `canon_rules_version` / `fingerprint_algos`。
- **D-06:** **继续排除**（与 Phase 1 D-16 一致）：`config/env_checks.yaml` 及纯诊断用途配置——改它们不得改变指纹。
- **D-07:** 本阶段首次扩展必然造成指纹断代。交付一份 **hash 版本映射表**（Markdown）：记录断代时刻的旧 hash → 新 hash、纳入文件清单、日期与简短原因；路径定为 `docs/CONFIG_HASH_HISTORY.md`（若不存在则新建）。之后每次有意改变 hash 口径须追加一行——承接 NR-6，越早一次性断代越好。
- **D-08:** 修改技能库 / `budget.yaml` / `llm.yaml` / 提示词任一项后，`config_hash` 必须变化——用断言单测覆盖（至少四类输入各一条）。

### 重复评测与置信区间（METR-04）

- **D-09:** `vela eval run --repeat N`：N 次完整评测后输出各指标的**均值 ± 标准差**与**置信区间**。默认行为保持单次（无 `--repeat` 时与今日一致）；聚合仅在显式 `--repeat N`（N≥2）时启用。
- **D-10:** 小样本（基线 N≥3）置信区间采用 **Student t 双侧 95% CI**。实现优先用成熟库（Phase 1 D-01：scipy/numpy 可进可选或必需依赖，planner 按「纯本地可装、不破坏离线主链路」择一）；禁止手写脆弱统计若库已能覆盖。
- **D-11:** 报表同时给出逐次 run 明细与聚合行，避免只剩一个合并数字无法审计。

### LLM 响应缓存与 workspace 复用（METR-06 / METR-07）

- **D-12:** 磁盘缓存键 = `(provider, physical_model, prompt_sha256, params)`（与需求字面一致）；缓存根目录默认项目级 `.cache/vela/llm/`（gitignore）；提供 `--no-cache` 关闭。重复评测场景目标命中率 > 90%（可用同 prompt 二次跑验证）。
- **D-13:** 缓存挂在网关出站路径（`LLMGateway.chat` 或 Provider 之上），**不得**改变 mock/真实供应商的业务语义；mock 评测可走缓存亦可旁路——planner 保证 determinism 标记用例不被缓存引入非确定性。
- **D-14:** `--reuse-workspace`：若目标 workspace 已存在可用证据库（既有 `analysis.duckdb` / 建库完成标记，细则 planner 对齐 `EvalRunner`），则跳过重建；否则正常 `build`。不得在复用时 silently 使用损坏半成品库（缺库或 QA 未过则重建或显式失败）。

### 过程指标与消融评测集（METR-05 / METR-08）

- **D-15:** 7 项过程指标（`premature_stop_rate` / `llm_parse_failure_rate` / `llm_truncation_rate` / `verdict_supported_ratio` / `skill_switch_per_session` / `unexplained_error_rate` / `citation_coverage`）+ 每轮决策轨迹表进入评测报表。数据从既有 `SessionState` / 事件 / 用例结果字段**聚合**，不改图节点逻辑；Phase 3 才会真正压低的指标本阶段允许显示为高值或占位——**可测即可**，不要求达标。
- **D-16:** 消融集 = 10 场景 × 按 golden 真值的正确技能在**运行时从候选集 mask 剔除**（不改 `builtin.yaml` 源文件、不持久化残缺技能库）。产出四指标：`misdiagnosis_rate_under_ablation` / `novel_detection_recall` / `unexplained_error_rate` / `confidence_calibration_error`，纳入 `_TARGETS` 但本阶段**不要求达标**（达标依赖 Phase 3~6）。CLI 入口形态由 planner 定（如 `vela eval run --ablation` 或子命令），须可一键跑通。
- **D-17:** 消融/过程指标中依赖 Phase 5 六级置信度或 `novel:` 的字段：本阶段用**当前二元结论可计算的代理定义**并在报表注释标明「代理口径，Phase 5 后替换」——禁止为算出 `novel_detection_recall` 而提前实现 CONF-03。

### 真实方差基线与 NR-1（METR-09）

- **D-18:** 在 `--no-cache` + `VELA_LLM_PROVIDER=volcengine` 下，对仿真黄金集做 N≥3 次重复，产出准确率均值±标准差与 95% CI，以及端到端延迟/成本联立基线（与 PERF-01 可同次采集）。**明确标注**：基准=仿真回归门，**非能力宣称**；G4 本期未测。
- **D-19:** 基线产物落盘：` .planning/phases/02-metrics-baseline/baseline/` 下至少一份 Markdown 人读报告 + 一份 JSON 机读明细（含 `config_hash`、doctor 环境指纹字段、N、provider、是否 cache、逐次指标）。自本阶段验收完成起，**禁止再引用 44.4% 作为后续对比基线**；Phase 3~6 一律以本目录基线为准（NR-1：分数可能因引用闸门变准而下降——预期行为，不是回归）。
- **D-20:** 付费实测沿用 Phase 1：`realllm` 标记 + 默认 `addopts` 排除；CI/`make test` 不触发付费。基线跑数可作为人工门或显式 `pytest -m realllm` / Makefile 目标，planner 写清门禁与凭据要求。

### 成本与延迟（PERF-01 / PERF-02）

- **D-21:** 扩展现有 `scripts/bench.py`，覆盖真实火山引擎 provider：单次诊断 token 成本与端到端 P95 延迟；可与 METR-09 共用实测数据，避免重复付费。
- **D-22:** `TokenLedger` 从「只做预算切断」扩展为「成本归集可观测」：累计 tokens、按配置单价估算成本、会话级汇总可被 eval/bench 读取。单价与「单次诊断成本上限」放进 `config/budget.yaml`（或并列成本段），超限发 `EventBus` ALERT——**默认告警不替代**既有 `BudgetExceeded` 硬切断语义（硬切断阈值仍由预算档决定）。
- **D-23:** PERF 基线数字写入与 D-19 同一 `baseline/` 目录（或其中明确章节），便于 G6 汇报。

### 阶段纪律与回归门

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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 需求与路线（验收合同）
- `.planning/ROADMAP.md` §Phase 2 — Goal、Success Criteria 1–5、风险预告 NR-1、回归门、阶段内顺序建议
- `.planning/REQUIREMENTS.md` §METR（METR-01..09）、§PERF（PERF-01、PERF-02）、§度量目标汇总 G1/G6；验收纪律 ADR-4
- `.planning/PROJECT.md` §Key Decisions ADR-2/ADR-3/ADR-8、§Constraints、§Context 三条地基裂缝（F-01/F-04/F-10）
- `.planning/STATE.md` — Phase 1 已完成决策（尤其 doctor `--json` 指纹、realllm 排除、D-01 三方库优先）

### 先验阶段
- `.planning/phases/01-llm/01-CONTEXT.md` — D-01 三方库纪律、D-16 env_checks 不进 hash、D-18/D-19 doctor JSON 与 realllm
- `.planning/phases/01-llm/01-VERIFICATION.md` — Phase 1 已验证能力与回归门凭据口径

### 探索文档（改造条目原文）
- `explore-docs/VELA-多专家联合评审与系统性优化改造方案.md` — F-01/F-02/F-10、C-01/C-02/C-11~C-14/C-28、ADR-2、NR-1/NR-6
- `explore-docs/VELA-真实LLM准确率归因分析与优化方案.md` — 44.4% 来源与过程指标清单
- `explore-docs/VELA-技能知识库深度分析报告.md` §3.4 — 消融/泛化度量与 ADR-8
- `explore-docs/VELA-双驱动架构升级与跨域泛化实施方案.md` — 阶段 0 硬前置声明

### 实现锚点（本阶段主要改动面）
- `src/vela/agent/citations.py` — `CitationReport.dangling_rate` / `ok`（F-01 修复点）
- `src/vela/config.py` — `config_hash()`（当前仅 pipeline/parsers/ota_phases）
- `src/vela/eval/runner.py` / `report.py` / `golden.py` — 评测执行与 `_TARGETS`
- `src/vela/cli.py` — `cmd_eval`（尚无 `--repeat` / `--reuse-workspace` / `--no-cache`）
- `src/vela/gateway/base.py` / `budget.py` — 缓存挂载点与 `TokenLedger`
- `src/vela/gateway/prompts.py` — 须纳入 config_hash 的内容
- `config/budget.yaml` / `config/llm.yaml` / `config/skills/` — 指纹与成本上限配置
- `scripts/bench.py` — PERF-01 扩展点
- `AGENTS.md` — 架构铁律（查询收口/配置驱动/不改 logging 等）；完成判据

### 代码地图
- `.planning/codebase/TESTING.md` — pytest 平面组织、mock 不用 patch、realllm/slow/determinism
- `.planning/codebase/STRUCTURE.md` — `eval/` / `gateway/` / `config` 布局
- `.planning/codebase/ARCHITECTURE.md` — 七层管道与评测位置

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `CitationReport`（`agent/citations.py`）：改 `dangling_rate`/`ok` 并加 `has_citations` 即 METR-01/02 核心；`to_dict()` 需同步
- `config_hash()`（`config.py`）：显式 payload 字典——按 D-05 增键即可；`canonical_json` + sha256 模式复用
- `EvalRunner` / `EvalResult` / `render_markdown` / `_TARGETS`：METR-04/05/08/09 的主扩展面；`cmd_eval` 已写 `eval_report.md` + `eval_result.json`
- `TokenLedger`（`gateway/budget.py`）：已有预算切断；PERF-02 在此扩展归集字段
- `scripts/bench.py`：已有建库吞吐与 mock 延迟骨架，扩 volcengine
- `vela doctor --json`（Phase 1）：基线元数据直接嵌入，无需新探测协议
- `realllm` pytest 标记 + addopts 排除：付费基线测试模板

### Established Patterns
- 配置驱动：阈值进 `config/*.yaml`，业务不硬编码（成本上限、缓存目录亦可 env 覆盖）
- 测试不用 `unittest.mock`：真实 `MockProvider` + `tmp_path`；新统计/闸门单测同此风格
- CLI：`cmd_*` 内延迟 import；退出码契约改动须同步测试
- D-01：置信区间/统计优先 scipy 或等价成熟库，不手写数值栈
- `load_yaml` 有 `lru_cache`：改配置须重启进程；测试用注入或独立进程

### Integration Points
- 质量闸门消费点：诊断后 `citation_check`、eval 报表 `dangling_citation_rate`、CLI 人读输出
- 证据包 `salt=cfg_hash`：hash 扩展后旧包不可比——靠 D-07 映射表承接
- Gateway `chat()`：缓存应包在脱敏/预算流程的合适层，避免缓存未脱敏内容或绕过预算（planner 选定确切插入点并做威胁分析）
- `.gitignore`：须忽略 `.cache/vela/`

</code_context>

<specifics>
## Specific Ideas

- ROADMAP 原文强调：METR-09/PERF-01 **收尾运行**，避免基线建立在未修正闸门上。
- NR-1 已与项目方对齐：新基线可能低于 44.4%，属尺子变准；不得解释为 Phase 2「改坏了系统」。
- Phase 1 用户级纪律 D-01 继续有效：统计与缓存若有成熟库则直接用。
- `--auto` 单次 pass：不就代理指标的数学细节再开讨论轮次；planner/researcher 在锁定决策下选定可单测公式即可。

</specifics>

<deferred>
## Deferred Ideas

- Reporter 引用不足重试与 `insufficient_citation` 降级（ORCH-08）→ Phase 3
- 编排层过程指标真正压降（首轮 stop / JSON / 截断等）→ Phase 3
- 六级置信度与真 `novel:` 口径替换本阶段代理定义 → Phase 5
- 消融集上 FM-1 的 Q2 捕获率 → Phase 6（依赖仲裁器）
- G4 真实工单标注基准 → v2.0（REAL-01）
- 可选依赖降级分支清理、lockfile、ruff 等工程卫生 → 非本阶段

None — discussion stayed within phase scope（无折叠 todo）

</deferred>

---

*Phase: 2-度量可信与真实基线*
*Context gathered: 2026-07-31*
