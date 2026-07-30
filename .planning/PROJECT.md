# VELA —— 车联网 OTA 日志证据化与智能诊断平台

## What This Is

VELA 把海量、多格式、多编码的车端 OTA 升级日志，转化为**可查询、可压缩、可核验、可追溯**的列式取证库，
再由一个七节点推理图驱动大模型自动定位根因，产出**每个结论都带 `[[EV:row_hash]]` 引用**的中文诊断报告，
并打包成含 Merkle 根、可离线三级验证的证据包。

面向车企 / Tier1 的 OTA 运维与诊断工程师：他们今天要在数 GB 跨 ECU 日志里人工翻找升级失败原因。
本地优先、纯 Python、无 Docker、无外部服务依赖；模型供应商可插拔（mock / 火山引擎方舟 / 任意 OpenAI 兼容端点）。

## Core Value

**每一个诊断结论都必须能被追溯到具体的原始日志字节，并且系统必须诚实地知道自己什么时候不知道。**

一个自信地给出错误 ECU 排查建议的系统，浪费的是工程师一整天以及对整个系统的信任；
一个诚实地说「我不确定，这是我看到的证据」的系统，在真实生产环境中价值高得多。

## Requirements

### Validated

<!-- v1.0 POC 已交付并经 177 个测试与 10 场景黄金评测确认 -->

- ✓ 原始日志压缩包经 Stage-0~8 转化为 DuckDB + Parquet 列式取证库（53 列 schema） — v1.0
- ✓ 13 个正则驱动解析器由 `config/parsers.yaml` 配置，新增日志格式零代码改动 — v1.0
- ✓ 三级指纹（`row_hash` 引用锚点 / `raw_hash` 字节 / `norm_hash` 去重聚类）与多时钟源时间归一（附 `ts_confidence`） — v1.0
- ✓ 12 个只读查询工具全部经 `LogQueryAPI.call()` 唯一收口，含 SQL 沙箱与鸟瞰-下钻护栏 — v1.0
- ✓ 七节点推理图（plan → retrieve → compress → verify → report，+ human_gate / unanswerable / distill）可中断续跑 — v1.0
- ✓ 预算感知证据压缩（白名单封顶 / 稀有豁免 / 模板配额 → 滑窗摘要） — v1.0
- ✓ 程序化引用校验独立于模型自述，剔除悬空引用 — v1.0
- ✓ 证据包 Merkle 根 + L0/L1/L2 三级离线验证 — v1.0
- ✓ 模型网关抽象：mock / 火山引擎方舟 / OpenAI 兼容三供应商，切换只改环境变量 — v1.0
- ✓ 出站脱敏（VIN/GPS/手机号/IMEI/身份证/邮箱/IP 共 7 类）+ 三级 token 预算硬切断 + 全量调用审计 — v1.0
- ✓ 10 场景仿真数据集 + 黄金评测集 + 6 项核心指标报表 — v1.0
- ✓ CLI 统一入口（`sim`/`build`/`query`/`agent`/`eval`/`evidence`/`serve`/`doctor`）+ 本地 HTTP 服务 — v1.0

### Active

<!-- v1.1 当前范围。详见 REQUIREMENTS.md -->

- [ ] 真实火山引擎方舟 LLM 实测环境可一键就绪并自检
- [ ] 度量体系可信：零引用报告被拦截、方差基线建立、`config_hash` 覆盖全部行为输入
- [ ] 编排层逻辑缺陷止血：首轮 stop / JSON 解析 / 截断 / verifier 判据 / 技能锁死
- [ ] 信号提取器配置化去耦合，打破「提取器认识仿真器格式」的循环验证
- [ ] planner 反馈闭环补全，且注入路径受五项安全约束
- [ ] 置信度六级分级替换二元 answered/unanswerable
- [ ] 技能库治理：Schema v2、受控词表、lint、候选集瘦身、维度预过滤
- [ ] 双驱动架构：证据通道 + 仲裁器，把知识缺口变成可测量信号

### Out of Scope

<!-- 显式边界。含 v1.1 明确延后项，理由沿用四份分析文档的决策 6 与 §7 P3。 -->

- **真实标注基准建设（C-19）** — 本期无历史工单 / 真实日志包可得；G4 真实能力门标注为「未测」，移至 v2.0
- **多租户改造（F-16）** — 当前租户校验绑定进程级环境变量 `VELA_TENANT`；重启条件：进入多团队共用阶段
- **落盘脱敏与保留期 / 加密（F-17）** — POC 期以文档标注风险替代；重启条件：接入真实车辆数据
- **列式库迁移（ClickHouse/StarRocks）** — 单机吞吐未成瓶颈；重启条件：单日日志 > 千万行
- **多根因推理与级联链** — 无验证数据且会破坏 `top1_hit` 评测口径；本期仅做 `root_cause.contributing_chain` 结构预留
- **因果图（L2 组合泛化）** — 依赖因果边积累，需 Jira 挖掘先行；重启条件：症状本体落地 + 因果边 ≥ 50 条
- **向量库 / 真实 embedding 召回** — 12 技能规模下混合召回已实测 100% 命中；重启条件：技能数 > 100
- **跨域基础设施（M-13~M-18）** — 领域包契约、Schema 泛化、第二个域 PoC；依赖本期双驱动证据原语先稳定
- **知识闭环运营化（M-07~M-12）** — 五源采集、探针自动合成、评审工作台；依赖本期 M-06 产出分歧信号
- **部署形态与并发模型改造** — 容器化、进程管理、多 db 挂载；与架构铁律「单线程单进程」冲突，需独立里程碑
- **症状本体 `symptoms.yaml`（C-31）** — 前置 C-15 本期完成，本体本身移至 v2.0

## Context

**代码规模**：约 7,100 行 Python（不含测试），61 个源文件，177 个单元/集成测试。架构映射见 `.planning/codebase/`。

**本里程碑的输入来源**：`explore-docs/` 下四份代码级专业分析文档，合计 63 项改造条目——
- 《技能知识库深度分析报告》（919 行）：闭集分类天花板、消融实验实测两个失效模式（FM-1 静默误诊 / FM-2 假阴性）、五层保障机制 L0~L4
- 《真实 LLM 准确率归因分析与优化方案》（605 行）：真实 LLM 首测 44.4%，定位 D1~D6 编排层缺陷
- 《多专家联合评审与系统性优化改造方案》（499 行）：**推翻前两份文档的共同隐含假设「评测体系是可信的」**，产出 F-01~F-19 与 C-01~C-39，六项 ADR
- 《双驱动架构升级与跨域泛化实施方案》（639 行）：技能+证据双驱动 M-01~M-06，跨域泛化 M-13~M-18，量化耦合边界（53 列中仅 3 列领域专属）

**必须如实面对的三条地基裂缝**（不是「还可以更好」，是当前认知的错误）：
1. **F-01 零引用悖论** — `CitationReport.dangling_rate` 在 `total==0` 时返回 `0.0`、`ok=True`：一份完全没有引用的报告会通过系统最核心的质量闸门。实测报告中 `dangling_citation_rate = 0.0` 很可能无意义。
2. **F-04 循环耦合** — `graph.py:423` 的 `reason=([A-Za-z0-9_x]+)` 提取器解析的正是 `sim/generate.py` 自己产生的格式，而 `abort_reason` 是技能召回中权重最高的信号。44.4% 是在「提取器认识数据格式」这一有利条件下取得的。
3. **F-10 config_hash 缺口** — 技能库、预算、`llm.yaml`、全部提示词均不进指纹，却参与证据包 Merkle 根计算（`salt=cfg_hash`）。优化过程本身会产生大量无法区分版本的证据包。

这三项共同解释了一个此前的困惑：mock 能拿 100%，是因为**仿真器、信号提取器、mock 打分器三者共享同一套格式约定**，形成自我确认的闭环。

**真实 LLM 环境的实际状态（2026-07-30 核查）**：`.env` 中密钥与 base_url 已填，但 `VELA_LLM_PROVIDER` 仍是 `mock`；且**项目无任何 `.env` 加载机制**（无 `python-dotenv` 依赖，`src/` 下零处读取），配置目前不会被代码读到。另有 `VELA_ARK_BASE_URL` 疑似笔误（`/api/plan/v3` vs 代码文档的 `/api/v3`）与行尾注释污染值的问题。

## Constraints

- **Tech stack**: Python ≥ 3.11，`src/` 布局，运行期依赖 duckdb / pyarrow / PyYAML / pytz / python-dotenv / openai — 2026-07-31 Phase 1 讨论的 D-01 项目级永久变更：能用成熟三方开源库解决的一律不手写实现，新增依赖只需满足纯本地可安装、不引入必须联网才能跑通主链路的服务
- **本地优先**: 无 Docker、无外部服务依赖，主链路必须能离线跑通 — POC 到生产的连续性保证
- **单线程 / 单进程**: `AgentGraph.run()` 同步阻塞，DuckDB 以 `read_only=True` 单进程持有 — 本期不引入并发框架
- **查询唯一收口**: Gold 库只经 `LogQueryAPI.call()` 访问 — 证据可追溯性的结构保证
- **配置驱动**: 阈值/预算/解析规则一律在 `config/*.yaml`，业务代码不硬编码 — 注意 `config.py::load_yaml` 有 `lru_cache`，改配置须重启
- **图节点即方法**: 七节点全部是 `AgentGraph.node_*` 方法；`agent/nodes/` 是空目录，新增节点不要在其中建文件
- **日志纪律**: 不使用 `logging` 模块；结构化事件走 `obs/events.py::EventBus`，CLI 输出用 `print()`
- **Security**: 出站数据必须经 `gateway/redact.py` 脱敏；禁止提交 `.env` 及任何 API key / 接入点 ID
- **成本**: 真实 LLM 评测每轮约 100+ 次 API 调用 — 响应缓存（C-14）是迭代可行性的前置，但方差基线必须在 `--no-cache` 下测量

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| ADR-1 修正 RCA 结论：80% 目标必须以真实基准度量 | F-04 循环耦合使仿真分数不可迁移到真实日志 | — Pending（v1.1 无真实数据，G4 标注未测） |
| ADR-2 先修度量再修系统 | F-01 使旗舰闸门失效、F-02 使基线无意义；在失效的仪表上优化等于没有优化 | — Pending |
| ADR-3 双基准分离：仿真=回归门，真实=能力门 | 仿真数据有回归价值、无能力度量价值；汇报必须标注基准来源 | — Pending |
| ADR-4 按「逻辑缺陷 / 行为调优」分类验收 | 逻辑必然缺陷（首轮 stop 时 evidence_pool 结构上必为空）不需统计前置 | — Pending |
| ADR-5 C-15 提取器框架为枢纽工程，优先于症状本体 | 一次投入同时服务 F-04 去循环耦合与 F-18 症状本体前置 | — Pending |
| ADR-6 多根因/因果图/向量库/跨域本期不做 | 缺验证数据或未达触发条件 | — Pending |
| ADR-7 双驱动首先是可观测性设施，其次才是推理增强 | 单驱动下知识缺口不可观测；Q2 象限直接捕获已实测的 FM-1 静默误诊 | — Pending |
| ADR-8 v1.1 无真实数据 → 消融评测集升为唯一泛化度量手段 | C-19 移出本期后，消融集是 C-22/C-23/M-03 验收的共同前置 | — Pending |
| 删除所有 pp 数值收益承诺，改为过程指标验收 | 9 个故障用例下单例对错造成 ±11.1pp 跳变，一次噪声波动会引发无谓返工 | — Pending |

## Current Milestone: v1.1 真实 LLM 生产级可信化与双驱动架构升级

**Goal:** 在真实火山引擎方舟实测环境下，把 VELA 从「仿真自我确认的 POC」升级为度量可信、编排健壮、知识缺口可观测的生产级诊断服务。

**Target features:**
- 真实火山引擎方舟 LLM 实测环境一键就绪并自检（`.env` 加载 + provider 切换 + 连通性校验）
- 度量可信：引用覆盖率闸门、方差基线、`config_hash` 补齐、过程指标入报表、响应缓存、消融评测集
- 编排健壮：首轮 stop 守卫、JSON 解析加固、截断告警、verifier 判据归一化、技能剔除策略回归、未解释错误哨兵、兜底技能
- 去循环耦合与反馈闭环：可配置信号提取器框架（枢纽工程）、多形态中止标记、planner 反馈闭环、注入五项安全约束
- 置信度分级与技能治理：`ts_confidence` 参与把关、六级置信度、结构化人工交接物、候选集瘦身、维度预过滤、Schema v2 + lint
- 双驱动架构：四个证据原语、证据推理节点、四象限仲裁器、P4 时序门控、分歧三指标、分歧样本采集

**Key context:**
- **预告并提前对齐**：仪表校准完成后，当前 44.4% 会被一个带置信区间的新基线取代，且可能因引用闸门生效而进一步下降——这是尺子变准的必然结果，不是系统变差（风险 NR-1）
- G4 真实能力门本期**未测**，禁止用仿真分数对外宣称真实准确率
- C-16 验收口径由「真实日志识别率 ≥0.85」改写为「6 种形态合成对抗语料识别率 ≥0.85」
- 生产化边界 = 工程质量达生产级，不含多租户、落盘脱敏、部署形态与并发模型改造

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-07-31 after v1.1 milestone start*
