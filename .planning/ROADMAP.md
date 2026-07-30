# Roadmap: VELA v1.1 —— 真实 LLM 生产级可信化与双驱动架构升级

## Overview

本里程碑把 VELA 从「仿真自我确认的 POC」（真实 LLM 首测 44.4%，且度量这个数字的尺子本身存在结构性盲区）推进到「度量可信、编排健壮、知识缺口可观测」的生产级诊断服务。旅程分六个阶段：先打通真实火山引擎方舟环境（Phase 1，全局最前置），再修正评测体系本身并在真实模型上建立带置信区间的新基线（Phase 2）——这是 ADR-2「先修度量再修系统」的直接体现，在失效的仪表上优化等于没有优化；随后止血编排层的逻辑必然缺陷（Phase 3，mock 供应商完全测不出的一类问题），打破信号提取器与仿真器的循环耦合并补全 planner 反馈闭环（Phase 4，同步加固注入安全）；再把「答/不答」二元判据升级为六级置信度并完成技能库治理（Phase 5）；最终落地技能通道之外的第二条独立证据通道与四象限仲裁器（Phase 6），让技能库覆盖不到的故障从静默误判变成可测量的知识缺口信号。全程贯穿两条不可违反的纪律：任何阶段都不得用仿真/消融分数冒充真实能力（G4 真实能力门本期全程未测，移至 v2.0）；任何验收都不承诺具体 pp 数值收益，逻辑必然缺陷用确定性过程指标验收，行为调优类改动必须在方差基线上用置信区间判定。

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

- [ ] **Phase 1: 真实 LLM 环境就绪** - 打通火山引擎方舟真实环境，`.env` 自动加载 + provider 切换 + `vela doctor` 连通性自检
- [ ] **Phase 2: 度量可信与真实基线** - 修正评测闸门与指标基础设施，在真实 LLM 上建立带置信区间的准确率、成本、延迟新基线
- [ ] **Phase 3: 编排层逻辑止血** - 消除首轮误停 / JSON 解析 / 截断 / verifier 判据 / 技能锁死等逻辑必然缺陷
- [ ] **Phase 4: 去循环耦合与反馈闭环** - 提取器框架化解耦仿真器依赖，补全 planner 反馈闭环并加固注入安全
- [ ] **Phase 5: 置信度分级与技能治理** - 六级置信度替换二元判据，技能库四职责分离与治理工具落地
- [ ] **Phase 6: 双驱动架构：证据通道与仲裁器** - 独立证据通道 + 四象限仲裁器，让知识缺口从静默误判变为可观测信号

## Phase Details

### Phase 1: 真实 LLM 环境就绪
**Goal**: 工程师无需手工 `export` 任何变量，仅凭 `.env` 即可让 CLI / 测试读到真实凭证；把 provider 切到 `volcengine` 后诊断链路端到端走通；`vela doctor` 能在跑诊断前就自检出环境与配置问题。这是全局最前置的阶段——不打通真实环境，后续任何「真实 LLM 下」的度量与行为调优都无法进行。
**Depends on**: Nothing (first phase)
**Requirements**: ENV-01, ENV-02, ENV-03, ENV-04
**Success Criteria** (what must be TRUE):
  1. 不手工 `export`，仅凭 `.env` 文件内容，任意 CLI 子命令或 `pytest` 均能读到火山引擎凭证与 `base_url`；已存在的进程环境变量优先级更高（有专门单测覆盖该优先级规则）
  2. `VELA_LLM_PROVIDER=volcengine` 时，`vela agent diagnose` 对至少一个仿真场景端到端跑完并产出含 `[[EV:row_hash]]` 引用的报告（不要求诊断结论正确，只要求链路不因环境问题中途报错）
  3. `vela doctor` 一次性输出端点可达性 / 鉴权有效性 / 模型可用性 / 四个逻辑模型映射完整性四项自检结果，无需先跑一次失败诊断才能定位配置错误
  4. `vela doctor` 能识别并报出 `.env` 中的行尾注释污染值与 `base_url` 路径异常；`.env.example` 不再含会被朴素解析器吃进值的行尾注释

**回归门**:
  - 现有 177 个测试全部通过
  - 仿真基准已通过用例回归数 = 0（一票否决）
**Plans**: 8 plans（5 波次）
- [x] 01-01-PLAN.md — 回归基线采集 + 新增 pip 包合法性核验 + python-dotenv/openai 必需依赖与 realllm 标记默认排除
- [x] 01-02-PLAN.md — 依赖纪律（D-01）与五层配置优先级链（D-10）的四份权威文档口径改写
- [x] 01-03-PLAN.md — `.env` 模块导入期静默加载（override=False）+ conftest 测试作用域锁定 + 优先级/锚点/静默性护栏
- [x] 01-04-PLAN.md — openai 官方 SDK 重写 provider + probe() 探测原语 + llm.yaml 死键清理 + 受影响用例改写
- [ ] 01-05-PLAN.md — mask_secret 掩码 + config/env_checks.yaml 规则表 + EnvChecker 模块 + .env.example 注释清理
- [ ] 01-06-PLAN.md — `vela doctor` 四项连通性自检 + 双通道渲染 + 退出码分层 + --offline/--online/--json
- [ ] 01-07-PLAN.md — realllm 标记端到端验收用例 + 生产接入文档三处口径对齐
- [ ] 01-08-PLAN.md — 一票否决回归门（177 测试 + 仿真基准回归数 0 + 演示链路）+ 真实环境实测验收

### Phase 2: 度量可信与真实基线
**Goal**: 评测体系本身先被修正为可信——零引用报告不再被误判通过、配置改动必被指纹捕获、重复评测可给出置信区间、7 项过程指标与消融评测集接入报表——并在真实火山引擎环境下产出第一份带置信区间的准确率、成本、延迟基线，取代无统计意义的 44.4%。本阶段**不改任何推理逻辑**（ADR-2：先修度量再修系统）。
**Depends on**: Phase 1（METR-09 与 PERF-01 均需真实 LLM 环境已就绪；建议阶段内先落地 METR-01~08 与 PERF-02 的指标基础设施，METR-09/PERF-01 作为收尾在指标口径确定后最后运行，确保基线反映修正后的闸门）
**Requirements**: METR-01, METR-02, METR-03, METR-04, METR-05, METR-06, METR-07, METR-08, METR-09, PERF-01, PERF-02
**Success Criteria** (what must be TRUE):
  1. 一份完全没有 `[[EV:row_hash]]` 引用的报告被质量闸门强制判失败；`has_citations` 布尔门与 `citation_coverage` 指标存在，且 `dangling_rate` 的 `total==0` 分支有专门单测覆盖（不再返回 `0.0`）
  2. 修改技能库 / `budget.yaml` / `llm.yaml` / 提示词任一项内容后，`config_hash` 必定变化（有断言单测），hash 版本映射表同步记录
  3. `vela eval run --repeat N` 输出各指标均值±标准差与置信区间；`vela eval run --reuse-workspace` 可跳过已存在证据库的重建；LLM 响应缓存命中率 > 90%（`--no-cache` 可关闭）
  4. 消融评测集（10 场景 × 逐个剔除正确技能构造未知故障用例）可运行，产出 `misdiagnosis_rate_under_ablation` / `novel_detection_recall` / `unexplained_error_rate` / `confidence_calibration_error` 四项指标数值（本阶段只建立可测性并纳入 `_TARGETS`，不要求达标——达标依赖 Phase 3~6 的行为修复）
  5. 在 `--no-cache` 条件下，使用真实火山引擎 LLM 对仿真数据集产出准确率方差基线（均值±标准差，N≥3 次重复；基准=仿真回归门，非能力宣称）与端到端 P95 延迟、单次诊断 token 成本基线（`TokenLedger` 具备成本归集能力、超限告警配置生效），取代无统计意义的 44.4% 单点数字

**风险预告（NR-1，本阶段完成后必须对齐）**：当前 44.4% 会被本阶段建立的带置信区间的新基线取代，且可能因引用闸门（本阶段 METR-01/02）生效而进一步下降——这是尺子变准的必然结果，不是系统变差。**Phase 3~6 的一切准确率对比一律以本阶段建立的新基线为准，不得再引用 44.4%**；G4 真实能力门本期全程未测，任何阶段都不得用仿真或消融分数对外宣称真实准确率。

**回归门**:
  - 现有 177 个测试全部通过
  - 仿真基准已通过用例回归数 = 0（一票否决）
**Plans**: TBD

### Phase 3: 编排层逻辑止血
**Goal**: 消除编排层的逻辑必然缺陷——首轮误停、JSON 解析静默失败、输出截断、verifier 判据脆弱匹配与循环论证、技能被误剔除、未解释错误被忽视、候选集全零分空手停止。这些缺陷 mock 供应商因「按设计意图而非提示词字面实现」而完全测不出，是本里程碑首个触及真实 LLM 行为的阶段。
**Depends on**: Phase 2（须以本阶段前建立的新基线而非 44.4% 判断本阶段效果；`unexplained_error_rate` 等指标依赖 Phase 2 的过程指标基础设施与消融评测集才能验收）
**Requirements**: ORCH-01, ORCH-02, ORCH-03, ORCH-04, ORCH-05, ORCH-06, ORCH-07, ORCH-08, ORCH-09, ORCH-10
**Success Criteria** (what must be TRUE —— 全部为逻辑必然缺陷的确定性过程指标，按 ADR-4 无需统计前置):
  1. `premature_stop_rate ≤ 0.05`——首轮禁止 stop 的程序化守卫生效，被拒绝的 stop 计入 `plan.stop_rejected`；提示词第 5 条已重写，不再诱导模型在证据池结构上必然为空的首轮选择 `stop=true`
  2. `llm_parse_failure_rate ≤ 0.02` 且 `llm_truncation_rate ≤ 0.02`——`_parse_json` 优先信任 `json_mode` 结构化结果、禁止跨段花括号提取、解析失败显式重试 2 次并计入 ALERT 事件；`planner`/`verifier` 的 `max_tokens` 上调至 2048 且 `finish_reason == "length"` 触发截断告警
  3. `verdict_supported_ratio ≥ 0.6`——verifier 判据归一化为枚举匹配（大小写与变体不再落空）且允许 `partial` 推进流程；claim 重构为根因假设而非日志原文，消除「判断这行日志是否支撑它自己」的自证循环
  4. round 1 选中但验证未通过的正确技能不再在 round 2 候选集中被物理剔除（技能剔除策略回归 `unproductive-only`，配合探针级 `(skill_id, args_hash)` 去重，有专门单测覆盖）
  5. `unexplained_error_rate ≤ 0.05`——报告/unanswerable 落地前的全局 SQL 不变量检查阻止「存在从未被任何探针取回的错误级日志行」时输出 `no_fault_found`；候选集全零分时通用兜底技能 `SK-GENERIC-EVIDENCE-FIRST` 被注入，系统不再空手停止

**回归门**:
  - 现有 177 个测试全部通过
  - 仿真基准已通过用例回归数 = 0（一票否决）
**Plans**: TBD

### Phase 4: 去循环耦合与反馈闭环
**Goal**: 打破信号提取器与仿真器格式的循环耦合——中止标记识别从硬编码正则改为配置驱动框架并支持 6 种形态；补全 planner 反馈闭环使其能看到已获证据、压缩痕迹与上一轮判定；对新扩大的注入面施加五项安全约束并纳入回归对抗测试。
**Depends on**: Phase 3（verifier 判据与技能剔除逻辑已止血，反馈闭环补全带来的效果变化才可被干净归因，而非被 Phase 3 遗留缺陷污染）
**Requirements**: DECP-01, DECP-02, DECP-03, DECP-04, DECP-05, DECP-06, DECP-07
**Success Criteria** (what must be TRUE):
  1. 工程师新增一种中止标记形态时，仅需修改 `config/extractors.yaml`，不需要改动任何 Python 代码——**DECP-01 提取器框架须先于 DECP-02/03 落地**（ADR-5：C-15 是枢纽工程，一次投入同时服务去循环耦合与症状本体前置）
  2. 中止标记支持 ≥ 6 种形态（`reason=` 结构式 / 十六进制错误码式 / 英文 `cause:` 式 / 中文无结构式 / 有中止行无 reason 式 / 无显式中止行的隐式中止），在 6 种形态合成对抗语料上识别率 ≥ 0.85；`unmatched_abort_marker_rate` 指标进入评测报表
  3. `skill_switch_per_session ≤ 2.5`——planner 第 2 轮 payload 包含证据摘要、压缩痕迹、护栏提示、上一轮 verdicts 与开放问题，不再与第 1 轮几乎相同
  4. 提示注入对抗用例（含 `[[`、`]]`、`<|...|>`、`system:` 等控制序列载荷）进入回归测试集并全部被正确拦截——**五项注入约束须与 DECP-04 反馈闭环同批落地，不可反序**（`wrap_log_content` 分隔标记包裹 / 剥离控制序列与疑似指令标记 / 只进 user 角色永不进 system / 提示词显式声明分隔标记内为不可执行数据 / 单行截断至 300 字符；DECP-04 打开注入面，无约束即构成漏洞）
  5. `_evidence_brief` 摘要限制在 1500 token 内，`avg_llm_tokens` 纳入监控，反馈闭环补全后 token 消耗未超出预算档

**回归门**:
  - 现有 177 个测试全部通过
  - 仿真基准已通过用例回归数 = 0（一票否决）
**Plans**: TBD

### Phase 5: 置信度分级与技能治理
**Goal**: 把「答/不答」二元判据升级为六级置信度（含开放式 `novel:` 根因与结构化人机交接物），同时把技能库混装的四种职责（检索锚点 / 取证策略 / 分类标签 / 处置知识）分离，为技能规模化与 Phase 6 双驱动的技能通道打好地基。注意：置信度分级后「确定」结论会减少，这是暴露既有不确定性而非引入新问题。
**Depends on**: Phase 4（反馈闭环与提取器框架已就位，置信度判据与技能治理才有稳定输入）；Phase 2（消融评测集用于验收本阶段的置信度校准与泛化指标）
**Requirements**: CONF-01, CONF-02, CONF-03, CONF-04, CONF-05, SKIL-01, SKIL-02, SKIL-03, SKIL-04, SKIL-05
**Success Criteria** (what must be TRUE):
  1. 六级置信度（`confirmed` / `probable` / `suspected` / `novel` / `insufficient_coverage` / `no_fault_found`）替换二元 `answered` / `unanswerable`，每级有明确判据与对应报告呈现方式，`confidence_calibration_error ≤ 0.15`；`ts_confidence` 不足的证据链结论从因果表述（「A 导致 B」）降级为相关性表述（「A 与 B 相关」）
  2. 无匹配技能标签但存在充分错误证据时，产出 `novel:` 前缀开放式根因（自由文本 + 证据链，与受控标签空间隔离、不污染 `top1_root_cause_accuracy`，标记为知识蒸馏高价值输入），`novel_detection_recall ≥ 0.80`——**本项须完整落地，它是 Phase 6 仲裁器 Q3 象限的硬前置**
  3. `node_human_gate` 产出结构化交接物（已排除假设及理由 / 已检索但未采信的证据 / 未解释错误行清单 / 建议的下一步查询），人工可直接接手而非空手接管
  4. `vela skills lint` 覆盖 8 项检查（含关键词冲突检测）；技能候选集 token 占用下降 ≥ 50%（探针全文移出候选集改为选定后程序注入，`trigger` 改写为可判定表述，新增 `differential` 鉴别项——**与 Schema v2 同批改动同一批技能 YAML**）；维度预过滤（`phase_scope` / `ecu_scope` / `module_scope`）在检索阶段以零 token 成本收窄候选池
  5. 处置建议全部来自技能 YAML 的 `remediation` 字段，`graph.py::_SUGGEST` 硬编码 Python 字典移除；技能库按域拆分为多个 YAML 文件，加载器 `glob("*.yaml")` 零代码改动支持多人并行维护

**回归门**:
  - 现有 177 个测试全部通过
  - 仿真基准已通过用例回归数 = 0（一票否决）
**Plans**: TBD

### Phase 6: 双驱动架构：证据通道与仲裁器
**Goal**: 落地技能通道之外的第二条独立证据通道与四象限仲裁器，把「技能库没覆盖的故障」从静默误判为近邻标签（已实测的 FM-1）变成可观测、可测量的知识缺口信号——双驱动首先是一套可观测性设施，其次才是推理能力增强（ADR-7）。
**Depends on**: Phase 2（消融评测集是 DUAL-07/08 验收的共同前置）；Phase 3 + Phase 4（编排层未止血、提取器未解耦，双通道共用同一条编排链路则走不通）；Phase 5（CONF-03 的 `novel:` 开放式根因是本阶段 Q3 象限判定的硬前置——Q3 判定为 `novel`，没有开放式根因分支则 Q3 无法产出结论）
**Requirements**: DUAL-01, DUAL-02, DUAL-03, DUAL-04, DUAL-05, DUAL-06, DUAL-07, DUAL-08, DUAL-09
**Success Criteria** (what must be TRUE):
  1. 四个领域无关证据原语（P1 断点定位 / P2 错误簇拓扑 / P3 稀有性异常 / P4 因果时序）均有独立单测与领域无关性检查（不依赖 OTA 专属列名或语义）；第八个图节点 `evidence_reason` 在零技能条件下仍能仅凭证据结构产出 `EvidenceHypothesis`
  2. `zero_skill_accuracy ≥ 0.40`（技能候选集人为清空条件下的准确率——当前该指标值为 0，无技能则结构性失效）
  3. 四象限仲裁器（Q1 `confirmed` / Q2 `suspected` 技能孤证 / Q3 `novel` 证据孤证 / Q4 `insufficient` 双缺）落地，一致性判定基于断点阶段 + 责任组件 + 证据交集的结构化比对（不重蹈 D3 的字符串精确匹配陷阱）；`ts_confidence` 不足时仲裁器仅允许相关性陈述、禁止发出因果声明（P4 时序门控接入）
  4. 消融评测集中的 FM-1 静默误诊被 Q2 象限捕获，捕获率 ≥ 0.8（这类失效在单驱动架构下完全不可检测）；分歧四指标（`q1_agreement_rate` / `overfit_rate` / `novel_rate` / `insufficient_rate`）进入评测报表，构成可观测的知识成熟度曲线
  5. Q2 / Q3 分歧样本 100% 自动落盘为知识候选；证据通道仅在三个约定时机运行（首轮与鸟瞰探针合并复用其结果 / 技能通道收敛前的最后一轮做仲裁 / 技能通道判定 unanswerable 时兜底），且 Q3 假设满足最低证据门槛（≥ 2 个组件 + ≥ 3 条错误证据）以防 `novel` 泛滥为噪声

**回归门**:
  - 现有 177 个测试全部通过
  - 仿真基准已通过用例回归数 = 0（一票否决）
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. 真实 LLM 环境就绪 | 4/8 | In Progress|  |
| 2. 度量可信与真实基线 | 0/TBD | Not started | - |
| 3. 编排层逻辑止血 | 0/TBD | Not started | - |
| 4. 去循环耦合与反馈闭环 | 0/TBD | Not started | - |
| 5. 置信度分级与技能治理 | 0/TBD | Not started | - |
| 6. 双驱动架构：证据通道与仲裁器 | 0/TBD | Not started | - |
