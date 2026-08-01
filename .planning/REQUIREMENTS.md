# Requirements: VELA v1.1 真实 LLM 生产级可信化与双驱动架构升级

**Defined:** 2026-07-31
**Core Value:** 每一个诊断结论都必须能被追溯到具体的原始日志字节，并且系统必须诚实地知道自己什么时候不知道。

**输入来源：** `explore-docs/` 四份代码级专业分析文档（63 项改造条目）。每条需求括注其原始条目 ID（C-xx / M-xx / F-xx / D-x），便于回溯原文。

**验收纪律（ADR-4）：**
- **逻辑必然缺陷**（逻辑上不可能正确）→ 用确定性过程指标验收，不需统计前置
- **行为调优类改动**（依赖模型行为）→ 必须在方差基线上用置信区间判定
- **全文不含 pp 数值收益承诺**——9 个故障用例下单例对错造成 ±11.1pp 跳变，追逐分数涨跌等于追逐噪声

---

## v1.1 Requirements

### ENV —— 真实 LLM 实测环境就绪

> 本类别不在四份文档覆盖范围内，来自 2026-07-30 环境核查的新发现：`.env` 中密钥已配置，但项目无任何 `.env` 加载机制（无 `python-dotenv` 依赖，`src/` 下零处读取），配置当前不会被代码读到。不修则整个里程碑的「真实 LLM 实测」前提不成立。原文中的 stdlib 约束已被 Phase 1 的 D-01 推翻。

- [x] **ENV-01**: 工程师运行任意 CLI 子命令或测试时，`.env` 中的配置被自动加载并生效，无需手工 `export`（用 python-dotenv 实现，见 D-01/D-03/D-05；已存在的进程环境变量优先级更高）
- [x] **ENV-02**: 工程师把 `VELA_LLM_PROVIDER` 切到 `volcengine` 后，`vela agent diagnose` 走真实火山引擎方舟端点完成一次端到端诊断并产出带引用的报告
- [x] **ENV-03**: 工程师运行 `vela doctor` 能看到真实 LLM 连通性自检结果（端点可达 / 鉴权有效 / 模型可用 / 四个逻辑模型映射完整），而不必先跑一次失败的诊断才发现配置错
- [x] **ENV-04**: 工程师能从 `vela doctor` 输出直接看出 `.env` 的配置形态错误（行尾注释污染值、`base_url` 路径异常），且 `.env.example` 不再含会被朴素解析吃进值的行尾注释

### METR —— 度量可信（先修尺子，ADR-2）

> 阶段 0「仪表校准」。**不改任何推理逻辑。** 完成后当前 44.4% 会被一个带置信区间的新基线取代，且可能因引用闸门生效而进一步下降——这是尺子变准的必然结果（风险 NR-1，已提前对齐）。

- [x] **METR-01** (C-01/F-01): 一份完全没有 `[[EV:row_hash]]` 引用的报告被质量闸门强制判失败；`citation_coverage`（有引用的事实句 / 事实句总数）作为新指标进入评测报表
- [x] **METR-02** (C-02): `dangling_rate` 在 `total == 0` 时返回 `None` 而非 `0.0`，并新增 `has_citations` 布尔门；`total == 0` 分支有专门单测覆盖
- [x] **METR-03** (C-11/F-10): 工程师修改技能库 / `budget.yaml` / `llm.yaml` / 提示词内容后，`config_hash` 必定改变；变更同时记录 hash 版本映射表以承接指纹断代（NR-6）
- [x] **METR-04** (C-12/F-02): 工程师可运行 `vela eval run --repeat N`，报告输出各指标的均值±标准差与置信区间
- [x] **METR-05** (C-13/F-03): 7 项过程指标（`premature_stop_rate` / `llm_parse_failure_rate` / `llm_truncation_rate` / `verdict_supported_ratio` / `skill_switch_per_session` / `unexplained_error_rate` / `citation_coverage`）与每轮决策轨迹表进入评测报表，归因无需再人工刨 `events.jsonl`
- [x] **METR-06** (C-14/F-09): LLM 响应按 `(provider, physical_model, prompt_sha256, params)` 做磁盘缓存，`--no-cache` 可关；重复评测缓存命中率 > 90%
- [x] **METR-07** (C-28/F-12): 工程师可运行 `vela eval run --reuse-workspace` 跳过已存在证据库的重建，单轮迭代省去约 80 秒
- [x] **METR-08** (ADR-8/KB §3.4): 工程师可运行消融评测集（10 场景 × 逐个剔除正确技能构造未知故障用例），4 项泛化指标 `misdiagnosis_rate_under_ablation` / `novel_detection_recall` / `unexplained_error_rate` / `confidence_calibration_error` 进入 `_TARGETS`
- [x] **METR-09** (NR-5): 在 `--no-cache` 条件下产出真实火山引擎 LLM 的方差基线报告，取代当前无置信区间的 44.4%，作为本里程碑后续一切判断的地基

### ORCH —— 编排层逻辑止血

> 阶段 1。全部为**逻辑必然缺陷**，验收用确定性过程指标，不依赖样本量。这些缺陷 mock 供应商全部测不出——`mock.py` 按设计意图而非提示词字面实现。

- [ ] **ORCH-01** (C-04/D1): 首轮禁止 stop 的程序化守卫生效，被拒绝的 stop 计入 `plan.stop_rejected` 指标 → `premature_stop_rate ≤ 0.05`
- [ ] **ORCH-02** (C-05/D1): 提示词第 5 条重写，明确区分「停止调查」与「无法定论」，不再诱导模型在证据池结构上必然为空的首轮选择 `stop=true`
- [x] **ORCH-03** (C-09/D5/F-07): `_parse_json` 优先信任 `json_mode` 结构化结果、禁止跨段花括号提取、解析失败显式重试 2 次并计入指标与 ALERT 事件 → `llm_parse_failure_rate ≤ 0.02`
- [x] **ORCH-04** (C-10/D6): `planner`/`verifier` 的 `max_tokens` 上调至 2048，且 `finish_reason == "length"` 触发截断告警 → `llm_truncation_rate ≤ 0.02`
- [ ] **ORCH-05** (C-07/D3): verifier 判据归一化为枚举匹配（大小写与变体不再落空）且允许 `partial` 推进流程 → `verdict_supported_ratio ≥ 0.6`
- [ ] **ORCH-06** (C-08/D3): verifier 的 claim 重构为**根因假设**而非日志原文，消除「判断这行日志是否支撑它自己」的同义反复，支持多条证据支撑单个假设
- [ ] **ORCH-07** (C-06/D4): 技能剔除策略回归 `unproductive-only`，配合探针级 `(skill_id, args_hash)` 去重；round 1 选中但验证未通过的正确技能不再被物理剔除出 round 2 候选集
- [ ] **ORCH-08** (C-03/F-01): reporter 输出后程序化校验引用数 ≥ 证据链条目的 50%，不足则带修复提示重试一次，仍不足则降级为 `insufficient_citation` 状态（阈值先设宽再观察分布收紧，NR-4）
- [ ] **ORCH-09** (C-22/KB L0): 报告与 unanswerable 落地前强制执行一次全局 SQL 不变量检查；存在从未被任何探针取回的错误级日志行时，禁止输出 `no_fault_found`，强制降级为 `insufficient_coverage` 并附未解释错误行 → `unexplained_error_rate ≤ 0.05`
- [ ] **ORCH-10** (C-23/KB L1): 通用兜底技能 `SK-GENERIC-EVIDENCE-FIRST`（空关键词 + `fallback_only: true` + 无 `root_cause_label`）在候选集全零分**且存在 ERROR 级信号**时被注入（RESEARCH A1：健康包无 ERROR 不注入），系统不再空手停止

### DECP —— 去循环耦合与反馈闭环

> 阶段 2 前半。**C-15 是枢纽工程**（ADR-5）：一次投入同时服务 F-04 去循环耦合与 F-18 症状本体前置。

- [ ] **DECP-01** (C-15/F-04/F-18): `graph.py::_absorb_signals` 中按工具名硬编码的 `if/elif` 提取逻辑重构为 `config/extractors.yaml` 驱动的框架；工程师新增一种中止标记形态时不需要改任何 Python 代码
- [ ] **DECP-02** (C-16/F-04): 中止标记支持 ≥ 6 种形态（`reason=` 结构式 / 十六进制错误码式 / 英文 `cause:` 式 / 中文无结构式 / 有中止行无 reason 式 / 无显式中止行的隐式中止「最后一条 ERROR 后静默」），在 6 种形态的**合成对抗语料**上识别率 ≥ 0.85
- [ ] **DECP-03** (NR-2): `unmatched_abort_marker_rate` 指标进入评测报表，持续驱动提取器形态补全
- [ ] **DECP-04** (C-17/D2): planner 的 payload 补全反馈闭环——包含证据摘要、压缩痕迹、护栏提示、上一轮 verdicts 与开放问题；planner 不再在第 2 轮收到与第 1 轮几乎相同的输入 → `skill_switch_per_session ≤ 2.5`
- [ ] **DECP-05** (C-18/F-08): 注入 planner 上下文的日志原文受五项约束——`wrap_log_content` 分隔标记包裹 / 剥离控制序列与疑似指令标记（`[[`、`]]`、`<|...|>`、`system:`）/ 只进 user 角色永不进 system / 提示词显式声明分隔标记内为不可执行数据 / 单行截断至 300 字符
- [ ] **DECP-06** (C-18/NR-7): 提示注入对抗用例（含上述控制序列载荷）进入回归测试集，未来扩大注入面的改动会被自动拦截
- [ ] **DECP-07** (NR-8): `_evidence_brief` 摘要限制在 1500 token 内，`avg_llm_tokens` 纳入监控，反馈闭环不使 token 消耗超出预算档

### CONF —— 置信度分级与人机交接

> 阶段 2 后半。注意 KB 文档预告：置信度分级后「确定」结论会减少，这是**暴露既有不确定性**而非引入新问题（风险 R7），需配套给出「如何提升置信度」的具体建议。

- [ ] **CONF-01** (C-20/F-06): `ts_confidence` 参与结论把关——低时间置信度证据链上的结论在报告措辞层面从因果表述（「A 导致 B」）降级为相关性表述（「A 与 B 相关」），机制五名实相符
- [ ] **CONF-02** (C-21/KB L4): 六级置信度（`confirmed` / `probable` / `suspected` / `novel` / `insufficient_coverage` / `no_fault_found`）替换当前二元的 `answered` / `unanswerable`，每级有明确判据与对应的报告呈现方式 → `confidence_calibration_error ≤ 0.15`
- [ ] **CONF-03** (C-29/KB L2): 无匹配技能标签但存在充分错误证据时，系统产出 `novel:` 前缀的开放式根因描述（自由文本 + 证据链），与受控标签空间隔离、不污染 `top1_root_cause_accuracy`，并标记为知识蒸馏高价值输入 → `novel_detection_recall ≥ 0.80`
- [ ] **CONF-04** (C-24/F-14): `node_human_gate` 产出结构化交接物——已排除的假设及理由、已检索但未采信的证据、未解释错误行清单、建议的下一步查询；人工可直接接手而非空手接管
- [ ] **CONF-05** (C-39/决策6): `root_cause.contributing_chain` 字段作为数据结构预留写入，不投入推理逻辑、不改评测口径，为后续多根因能力留出扩展位

### SKIL —— 技能库治理

> 阶段 2 后半。目标是把技能当前承担的四种职责（检索锚点 / 取证策略 / 分类标签 / 处置知识）分离开。

- [ ] **SKIL-01** (C-27): 技能 Schema v2 + `_taxonomy.yaml` 受控词表落地，`vela skills lint` 覆盖 8 项检查（含关键词冲突检测），技能库改动在提交前可自检
- [ ] **SKIL-02** (C-25): 技能候选集瘦身——移除 probes 全文（探针在选定后由程序注入）、新增 `differential` 鉴别项、`trigger` 改写为可判定表述；候选集 token 占用下降 ≥ 50%
- [ ] **SKIL-03** (C-26): 维度预过滤（`phase_scope` / `ecu_scope` / `module_scope`）在检索阶段零 token 成本收窄候选池
- [ ] **SKIL-04** (C-32): 处置建议从 `graph.py::_SUGGEST` 硬编码 Python 字典迁入技能 YAML 的 `remediation` 字段；工程师新增技能不再需要同时改 Python 源码
- [ ] **SKIL-05** (KB §2.2): 技能库按域拆分为多个 YAML 文件（加载器已支持 `glob("*.yaml")`，零代码改动），多人可并行维护不同域而不冲突

### DUAL —— 双驱动架构（技能 + 证据）

> ADR-7：双驱动**首先是一套可观测性设施，其次才是推理能力增强**。单驱动下「知识缺口」完全不可观测——技能库没覆盖的故障会被静默误判为近邻标签（已实测的 FM-1），没有任何信号提示这里缺知识。

- [ ] **DUAL-01** (M-01): 四个领域无关的证据原语实现——P1 断点定位 / P2 错误簇拓扑 / P3 稀有性异常 / P4 因果时序；每个原语有独立单测与领域无关性检查（不得依赖 OTA 专属列名或语义）
- [ ] **DUAL-02** (M-02): 新增第八个图节点 `evidence_reason`，仅凭证据结构合成 `EvidenceHypothesis`（含断点阶段、责任组件、支撑 row_hash、因果声明许可、置信度、`novel:` 标签建议）；在零技能条件下仍能产出假设
- [ ] **DUAL-03** (M-03): 四象限仲裁器落地（Q1 `confirmed` / Q2 `suspected` 技能孤证 / Q3 `novel` 证据孤证 / Q4 `insufficient` 双缺）；一致性判定基于断点阶段 + 责任组件 + 证据交集的结构化比对，**不重蹈 D3 的字符串精确匹配陷阱**
- [ ] **DUAL-04** (M-04): P4 时序门控接入仲裁器——`ts_confidence` 不足时禁止发出因果声明，只允许相关性陈述
- [ ] **DUAL-05** (M-05): 分歧四指标（`q1_agreement_rate` / `overfit_rate` / `novel_rate` / `insufficient_rate`）进入评测报表，构成可观测的知识成熟度曲线
- [ ] **DUAL-06** (M-06): Q2 / Q3 分歧样本 100% 自动落盘为知识候选，为下个里程碑的知识闭环提供燃料
- [ ] **DUAL-07** (M-01~M-06): `zero_skill_accuracy`（零技能条件下的准确率）首次可测且 ≥ 0.40 —— 当前系统该指标值为 **0**（无技能则结构性失效）
- [ ] **DUAL-08** (M-03/FM-1): 消融评测集中的 FM-1 静默误诊被 Q2 象限捕获，捕获率 ≥ 0.8 —— 这类失效在单驱动架构下完全不可检测
- [ ] **DUAL-09** (XR-1/XR-2): 证据通道仅在三个时机运行（首轮与鸟瞰探针合并复用其结果 / 技能通道收敛前的最后一轮做仲裁 / 技能通道判定 unanswerable 时兜底），且 Q3 假设须满足最低证据门槛（≥ 2 个组件 + ≥ 3 条错误证据）以防 novel 泛滥为噪声

### PERF —— 成本与延迟基线

> G6 可运维层。当前完全无法回答生产场景的基本问题：单次诊断的 token 成本？P95 端到端延迟？这直接决定产品形态（同步接口 vs 异步任务）。

- [x] **PERF-01** (C-36/F-13): `scripts/bench.py` 覆盖真实火山引擎 provider，产出单次诊断的 token 成本与端到端 P95 延迟基线（当前只测建库吞吐与 mock 诊断延迟）
- [x] **PERF-02** (G6): 单次诊断 token 成本上限进入配置并在超限时告警，`TokenLedger` 从「只做预算切断」扩展为「成本归集可观测」

---

## v2 Requirements

延后到下一里程碑，已跟踪但不在当前路线图。

### 真实能力度量

- **REAL-01** (C-19): 30~50 例历史工单人工确认根因，train/holdout 严格切分，构建真实标注基准 —— **G4 能力门在本期标注为「未测」，这是唯一可对外宣称准确率的依据**
- **REAL-02** (G4): 真实标注集 Top-1 ≥ 80%
- **REAL-03** (C-35/F-15): 结论反馈回路（工程师确认根因 vs 系统判定），生产准确率唯一可靠来源

### 跨域泛化

- **XDOM-01** (M-13): 领域包契约定义 + `ota.yaml` 重构（`config/domains/<domain>.yaml`）
- **XDOM-02** (M-14): Schema 3 列泛化（`ota_phase`→`process_phase` 等）+ 兼容视图 + 工具改名保留别名
- **XDOM-03** (M-15): `_phase_matchers` 与 `gold.py` 前向填充改为领域包驱动，支持 `phase_model: none`
- **XDOM-04** (M-17): `vela domain lint` + `vela domain scaffold <id>` 新域脚手架
- **XDOM-05** (M-18): 第二个域 PoC（远程诊断）+ `transfer_decay` 迁移衰减测量

### 知识闭环运营化

- **KNOW-01** (M-07): 五源统一采集管道 + 统一候选 Schema
- **KNOW-02** (M-08/C-33/F-19): 症状指纹去重（Jaccard > 0.7），候选池不被近似重复淹没
- **KNOW-03** (M-09): 探针自动合成 + 留出集召回率自动验收（≥ 0.8）
- **KNOW-04** (M-10/C-34): 人工评审工作台 `vela knowledge review` + 五道闸门 + 影子评测
- **KNOW-05** (M-11): 边际收益度量（留一法）+ 技能退役建议
- **KNOW-06** (M-12): 结论反馈入口产品化

### 其他

- **MISC-01** (C-30): 鉴别诊断 `differential` 消费逻辑（本期只加字段不消费）
- **MISC-02** (C-31/F-18): 症状本体 `symptoms.yaml`（前置 C-15 本期完成）
- **MISC-03** (C-37/F-11): `evidence_pool` 上界 + 检查点瘦身（原文改存 `row_hash` 引用 + 按需回取）
- **MISC-04** (SQL 沙箱): 从正则黑名单迁移到基于 AST 的白名单校验与参数化谓词构造

---

## Out of Scope

显式排除，记录理由以防范围蔓延与日后重复讨论。

| Feature | Reason |
|---------|--------|
| 多租户改造（F-16） | 租户标识改为随请求传入需 API 层改造；重启条件：进入多团队共用阶段 |
| 落盘脱敏与保留期 / 加密（F-17） | POC 期以文档标注风险替代；重启条件：接入真实车辆数据 |
| 列式库迁移（ClickHouse / StarRocks） | 单机 DuckDB 吞吐未成瓶颈；重启条件：单日日志 > 千万行 |
| 多根因推理与级联链 | 无验证数据（现有 9 用例全为单根因），且会破坏 `top1_hit` 评测口径；本期仅做 `contributing_chain` 结构预留 |
| 因果图（L2 组合泛化，C-29 之外部分） | 依赖因果边积累，需 Jira 挖掘先行；重启条件：症状本体落地 + 因果边 ≥ 50 条 |
| 向量库 / 真实 embedding 召回 | 12 技能规模下混合召回已实测 100% 命中；重启条件：技能数 > 100 |
| 部署形态与并发模型改造 | 容器化、进程管理、多 db 挂载与架构铁律「单线程单进程」冲突，需独立里程碑 |
| 类案 RAG（历史工单检索增强） | 依赖 Jira 数据准入，与 REAL-01 同批 |
| 工业级中文分词替换 | FTS 中文召回是已知弱项，但非本期瓶颈；真实 embedding 落地后一并评估 |
| 用户级鉴权 | 当前无认证体系；属服务化硬化范畴，与多租户同批 |

---

## Traceability

各阶段覆盖哪些需求。由 roadmapper 在创建路线图时填充。

| Requirement | Phase | Status |
|-------------|-------|--------|
| ENV-01 | Phase 1 | Complete |
| ENV-02 | Phase 1 | Complete |
| ENV-03 | Phase 1 | Complete |
| ENV-04 | Phase 1 | Complete |
| METR-01 | Phase 2 | Complete |
| METR-02 | Phase 2 | Complete |
| METR-03 | Phase 2 | Complete |
| METR-04 | Phase 2 | Complete |
| METR-05 | Phase 2 | Complete |
| METR-06 | Phase 2 | Complete |
| METR-07 | Phase 2 | Complete |
| METR-08 | Phase 2 | Complete |
| METR-09 | Phase 2 | Complete |
| PERF-01 | Phase 2 | Complete |
| PERF-02 | Phase 2 | Complete |
| ORCH-01 | Phase 3 | Pending |
| ORCH-02 | Phase 3 | Pending |
| ORCH-03 | Phase 3 | Complete |
| ORCH-04 | Phase 3 | Complete |
| ORCH-05 | Phase 3 | Pending |
| ORCH-06 | Phase 3 | Pending |
| ORCH-07 | Phase 3 | Pending |
| ORCH-08 | Phase 3 | Pending |
| ORCH-09 | Phase 3 | Pending |
| ORCH-10 | Phase 3 | Pending |
| DECP-01 | Phase 4 | Pending |
| DECP-02 | Phase 4 | Pending |
| DECP-03 | Phase 4 | Pending |
| DECP-04 | Phase 4 | Pending |
| DECP-05 | Phase 4 | Pending |
| DECP-06 | Phase 4 | Pending |
| DECP-07 | Phase 4 | Pending |
| CONF-01 | Phase 5 | Pending |
| CONF-02 | Phase 5 | Pending |
| CONF-03 | Phase 5 | Pending |
| CONF-04 | Phase 5 | Pending |
| CONF-05 | Phase 5 | Pending |
| SKIL-01 | Phase 5 | Pending |
| SKIL-02 | Phase 5 | Pending |
| SKIL-03 | Phase 5 | Pending |
| SKIL-04 | Phase 5 | Pending |
| SKIL-05 | Phase 5 | Pending |
| DUAL-01 | Phase 6 | Pending |
| DUAL-02 | Phase 6 | Pending |
| DUAL-03 | Phase 6 | Pending |
| DUAL-04 | Phase 6 | Pending |
| DUAL-05 | Phase 6 | Pending |
| DUAL-06 | Phase 6 | Pending |
| DUAL-07 | Phase 6 | Pending |
| DUAL-08 | Phase 6 | Pending |
| DUAL-09 | Phase 6 | Pending |

**Coverage:**
- v1.1 requirements: 51 total（订正：原 Coverage 计数曾误记为 50，roadmapper 逐条核实全部 REQ-ID 后确认实际为 51 条，已在此更正）
- Mapped to phases: 51
- Unmapped: 0 ✓

---

## 度量目标汇总（G1~G6）

汇报任何准确率数字时**必须标注基准来源**（ADR-3）。仿真基准 = 回归门，不作为能力宣称依据。

| 层 | 目标 | 当前 | 本期目标值 | 基准 |
|---|---|---|---|---|
| **G1 度量可信** | `citation_coverage` | 无此指标 | ≥ 0.9 | — |
| | 方差基线 | 无 | 3 次重复，均值±标准差 | 仿真（`--no-cache`） |
| **G2 编排健壮** | `premature_stop_rate` | 未知（疑似高） | ≤ 0.05 | 仿真 |
| | `llm_parse_failure_rate` | 无观测 | ≤ 0.02 | 仿真 |
| | `llm_truncation_rate` | 无观测 | ≤ 0.02 | 仿真 |
| | `verdict_supported_ratio` | 未知 | ≥ 0.60 | 仿真 |
| | `skill_switch_per_session` | 未知 | ≤ 2.5 | 仿真 |
| **G3 回归防护** | 仿真基准 Top-1 | 44.4% | ≥ 85%（回归门） | 仿真 |
| | 已通过用例回归数 | — | = 0（一票否决） | 仿真 |
| **G4 真实能力** | 真实标注集 Top-1 | 未测 | **本期未测**（移至 v2.0） | 真实 |
| **G5 诚实性** | `unexplained_error_rate` | 无此指标 | ≤ 0.05 | 仿真 + 消融 |
| | `confidence_calibration_error` | 无 | ≤ 0.15 | 仿真 + 消融 |
| | `misdiagnosis_rate_under_ablation` | 无 | ≤ 0.20 | 消融 |
| | `novel_detection_recall` | 无 | ≥ 0.80 | 消融 |
| **G6 可运维** | 单次诊断 token 成本 | 未测 | 建立基线并设上限 | 真实 LLM |
| | 端到端 P95 延迟 | 未测（仅 mock） | 建立基线 | 真实 LLM |
| **G7 双驱动** | `zero_skill_accuracy` | **0** | ≥ 0.40 | 仿真 + 消融 |
| | FM-1 Q2 象限捕获率 | 不可检测 | ≥ 0.8 | 消融 |
| | `overfit_rate` (Q2) | 无 | ≤ 0.10 | 仿真 |
| | `unmatched_abort_marker_rate` | 无 | ≤ 0.15 | 合成对抗语料 |

---

*Requirements defined: 2026-07-31*
*Last updated: 2026-07-31 after ROADMAP.md created — Traceability 补全，50→51 计数订正*
