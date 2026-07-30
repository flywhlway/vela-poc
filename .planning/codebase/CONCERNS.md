# Codebase Concerns

**Analysis Date:** 2026-07-30

> 本文件综合三个来源：(1) 项目自身 README「已知局限」章节的诚实声明；(2) `explore-docs/` 下三份已完成的代码级分析报告（真实 LLM 归因分析、技能知识库依赖分析、多专家联合评审）；(3) 本次对源码的直接核查（已逐条核实文件路径与代码片段仍然有效）。所有 P0/P1/P2 优先级与 ID（D1-D6 / F-01~F-19 / C-01~C-39）沿用 `explore-docs/` 原文档编号，便于交叉引用。

## Tech Debt

**技能配置是结构性总依赖，而非增强性依赖：**
- Issue: 根因标签、假设候选集、探针取证策略三者全部只能来自 `config/skills/builtin.yaml`。`decisive` 判据硬编码要求 `self.skills.label_of(skill_id) is not None`，技能库之外不存在任何产出结论的路径。
- Files: `src/vela/agent/graph.py:234-235`（decisive 判据）、`src/vela/agent/graph.py:552`（`_SUGGEST` 处置建议硬编码字典，独立于 YAML，新增技能必须同时改 Python 源码）
- Impact: 系统本质是一个 10 类闭集分类器；技能库覆盖不到的故障模式在架构上不可能被正确命名（详见下方「已知局限」FM-1/FM-2 消融实验）。
- Fix approach: 技能职责四分离（检索锚点/取证策略/分类标签/处置知识），处置建议从 `_SUGGEST` 迁入技能 YAML 的 `remediation` 字段；参见 `explore-docs/VELA-技能知识库深度分析报告.md` §1.3、§2.3。

**信号提取器与仿真器循环耦合（评测自我确认）：**
- Issue: `abort_reason` 信号提取用正则 `reason=([A-Za-z0-9_x]+)` 精确匹配仿真器自己生成的日志格式，而该信号在技能召回中权重最高。
- Files: `src/vela/agent/graph.py:423`（提取器）、`src/vela/sim/generate.py:155,183,200,230` 等多处（仿真器生成同款 `reason=` 格式）
- Impact: 当前评测分数是在"提取器认识数据格式"这一有利条件下取得的；真实日志的中止标记形态差异极大（错误码式/中文式/无 reason 式/无中止行式），真实场景准确率大概率显著低于仿真评测分数。
- Fix approach: 把 `graph.py::_absorb_signals` 中硬编码的 `if/elif` 提取逻辑重构为 `config/extractors.yaml` 驱动的可配置提取器框架（枢纽工程，同时服务症状本体前置需求），详见 `explore-docs/VELA-多专家联合评审与系统性优化改造方案.md` F-04、F-18、C-15。

**`config_hash` 不覆盖技能库、预算与提示词：**
- Issue: `config_hash()` 只对 `pipeline.yaml` + `parsers.yaml` + `ota_phases.yaml` + 规范化规则版本 + 哈希算法做指纹，不包含 `config/skills/*.yaml`、`budget.yaml`、`llm.yaml`，以及全部提示词（`prompts.py` 是 Python 代码，从不在配置指纹范围内）。
- Files: `src/vela/config.py:125-143`
- Impact: 该哈希被写入 `runs` 表并进入证据包 Merkle 根计算（`salt=cfg_hash`）。用完全不同的技能库或大改的提示词跑两次，`config_hash` 相同——"结论可复现"的承诺存在缺口，且会导致优化迭代产生大量无法区分版本的证据包。
- Fix approach: 补齐哈希覆盖范围，纳入技能库、预算、模型网关配置与提示词内容哈希（`explore-docs/...多专家联合评审...md` F-10 / C-11）。

**`evidence_pool` 无界增长且检查点全量重写：**
- Issue: `SessionState.evidence_pool` 每轮追加去重后的完整证据行（含 `raw_line` 原文），`CheckpointStore.save()` 每轮把整个 `SessionState` 序列化落盘。production 档 `max_rounds: 30`。
- Files: `src/vela/agent/state.py:44`（`evidence_pool` 定义）、`src/vela/agent/checkpoint.py:18`（`save` 方法）
- Impact: 单轮可保留数十至数百行，检查点 JSON 可膨胀至数十 MB 且每轮全量重写；同时 `raw_line` 可能含 VIN/位置/用户标识，出站有脱敏（`gateway/redact.py`）但落盘无脱敏。
- Fix approach: 检查点存引用（`row_hash`）+ 按需回取，而非原文全量落盘；参见 F-11 / C-37。

**评测每次重建数据库，迭代成本高：**
- Issue: `EvalRunner._one()` 每个用例都重新 `build()` 一次（实测约 8 秒/用例）。提示词/编排层迭代只需要重跑诊断阶段，不需要重建证据库。
- Files: `src/vela/eval/runner.py`
- Impact: 每轮提示词调优白等约 80 秒（10 场景 × 8s）。
- Fix approach: 新增 `--reuse-workspace` 跳过已存在证据库的重建（F-12 / C-28）。

**候选技能集把完整探针（含参数）塞进模型上下文：**
- Issue: `compact()` 把每个技能的全部 `probes`（工具名+完整 args）序列化进候选集，供模型选择。12 个技能 × 2~3 条探针占用大量 token，且诱导模型"照抄探针"而非基于假设推理。
- Files: `src/vela/agent/skills.py::compact`（技能候选集裁剪函数）
- Impact: 候选集 token 开销高；技能规模扩大后（30+）问题会加剧。
- Fix approach: 候选集只给决策所需字段（id/title/trigger/summary/discriminators/probe_count），探针在选定后由程序注入（`explore-docs/VELA-技能知识库深度分析报告.md` §5.2、C-25）。

## Known Bugs

**D1 提示词第 5 条直接诱导真实 LLM 首轮 stop（逻辑必然缺陷）：**
- Symptoms: 真实 LLM 接入后，多个故障场景在第 1 轮即以 `unanswerable` 收场（`predicted_label = None`，判为 miss），而首轮 `evidence_pool` 结构上必然为空。
- Files: `src/vela/gateway/prompts.py`（`PLANNER_SYSTEM` 第 5 条"证据不足时输出 stop=true"）、`src/vela/agent/graph.py:322-331`（首轮 stop 无补救，直接终局）
- Trigger: 任意首轮请求真实 LLM 诊断；模型严格遵循提示词字面，在没有下钻证据时选择 `stop=true`。mock 供应商因为不读提示词正文而完全测不出此问题。
- Workaround: 无（需修改提示词第 5 条并加程序化守卫：首轮禁止 stop）。参见 `explore-docs/VELA-真实LLM准确率归因分析与优化方案.md` D1、`...多专家联合评审...md` C-04/C-05。

**D2 planner 全程看不到已获证据，反馈闭环断裂：**
- Symptoms: 第 2 轮及以后，planner 收到的 payload 与第 1 轮几乎完全相同（只多 `used_skills`），不包含上一轮检索到的证据行、`compression_trace`、护栏提示或 verifier 判定结果，导致模型在关键词层面盲目游走而非基于已有证据推理。
- Files: `src/vela/agent/graph.py:145-149`（`node_plan` 的 payload 构造）、`src/vela/agent/graph.py:185-189`（`search_logs`/`get_lines`/`get_context` 结果只进 `evidence_pool` 给 verifier，不进 `evidence_digest` 给 planner）
- Trigger: 任意需要多轮下钻的诊断会话。
- Workaround: 无（需在 payload 中补全 `evidence_so_far`/`compression_trace`/`guardrail_notes`/`prior_verdicts`，见 D2 修复方案 / C-17；注意补全时需配合注入安全约束，见下方安全条目）。

**D3 verifier 判据是脆弱字符串精确匹配，且 claim 构造是循环论证：**
- Symptoms: `decisive` 要求 verifier 返回精确字符串 `"supported"`（大小写/变体如 `"Supported"`、`"partially_supported"` 全部落空）；且 `claims` 构造中 `claim` 字段就是日志原文，`citations` 字段是同一行的 `row_hash`——模型被要求判断"这行日志是否支撑它自己"。
- Files: `src/vela/agent/graph.py:233-235`（decisive 判据）、`src/vela/agent/graph.py:216-218`（claim/citation 同源构造）
- Trigger: 真实 LLM 对单行证据给出负责任的 `"weak"` 判断时，系统永不收敛。
- Workaround: 无（需判据归一化枚举匹配+分级，claim 重构为根因假设而非日志行自身；D3 / C-07 / C-08）。

**D4 技能"用过即剔除"锁死正确假设：**
- Symptoms: `excluded_skills()` 返回 `used_skills ∪ unproductive_skills` 的并集。round 1 选中正确技能但因 D3 被判 `"weak"`（非 decisive）后，该技能在 round 2 被物理剔除出候选集，即便它是唯一正确的假设。
- Files: `src/vela/agent/state.py::excluded_skills`
- Trigger: 任意"首次验证未通过但假设本身正确"的场景（真实 LLM 下常见，mock 下因首轮即收敛而从未触发）。
- Workaround: 无（需回归为仅剔除 `unproductive_skills`，配合探针级 `(skill_id, args_hash)` 去重；D4 / C-06）。

**D5 JSON 解析失败静默降级为 stop，且无日志记录：**
- Symptoms: `_parse_json` 解析失败时返回 `{}`，下游 `selected_skill=None` → `actions=[]` → 触发 stop；解析失败与模型主动 stop 在下游完全不可区分，且 `events.jsonl` 中不留任何"解析失败"的痕迹。
- Files: `src/vela/agent/graph.py:51-65`
- Trigger: 真实 LLM 输出带前言、Markdown 围栏或被截断的 JSON。
- Workaround: 无（需显式重试+计入指标+发 ALERT 事件；D5 / C-09）。

**F-07 `_parse_json` 花括号跨度提取可能取到语义错误但语法合法的片段：**
- Symptoms: 若模型输出中出现两段花括号（如"思考：{...}...然后 {"selected_skill": ...}"），`t.find("{")`/`t.rfind("}")` 会跨段截取，产出的字典语法合法但内容可能语义错误——比纯粹的解析失败更危险，因为它不会被解析失败率指标捕获。
- Files: `src/vela/agent/graph.py`（`_parse_json` 的花括号跨度提取逻辑）
- Trigger: 模型输出包含前言性质的伪 JSON 片段。
- Workaround: 无（需优先信任 `json_mode` 结构化结果，禁止跨段提取；C-09）。

**D6 `max_tokens` 过紧导致输出截断，触发 D5：**
- Symptoms: `verifier max_tokens: 768` 对最多 8 条 claims（每条约 90 token）几乎必然截断；`planner max_tokens: 1024` 对真实模型较长的 `thought` 字段也容易超限。`json_mode: true` 只保证格式是 JSON，不保证不被截断。
- Files: `config/llm.yaml`（`planner`/`verifier` 的 `max_tokens` 配置）
- Trigger: 任意真实 LLM 调用产出接近上限长度的输出。
- Workaround: 无（需上调至 2048 并加 `finish_reason == "length"` 截断告警；D6 / C-10）。

**已修复的历史 CLI bug（回归测试已覆盖，记录备查）：**
- Symptoms: `vela build` 的 QA 报告结构中检查项字段名为 `ok`/`detail`，曾被误当作 `passed` 读取导致误判。
- Files: `tests/test_cli_and_server.py::test_cli_build_command_produces_parseable_qa_json`（回归用例）
- Trigger: 已修复，README 常见问题排查章节专门记录此教训。
- Workaround: 不适用（已有回归测试防止复发）。

## Security Considerations

**F-01 零引用报告被判为"完美"——旗舰质量闸门存在结构性盲区：**
- Risk: `CitationReport.dangling_rate` 在 `total == 0`（报告完全没有任何 `[[EV:row_hash]]` 引用）时返回 `0.0`，`ok` 属性为 `True`——一份**完全没有引用的报告会通过系统最核心的质量闸门**。而 reporter 是自由文本输出（`json_mode: false`），引用格式仅在提示词里要求，无任何程序化保证。
- Files: `src/vela/agent/citations.py:27-32`（`dangling_rate`/`ok` 属性）、`src/vela/gateway/prompts.py`（引用格式仅提示词层面要求）
- Current mitigation: 无。当前 mock 供应商恒定输出规范引用，此盲区从未在测试中被触发。
- Recommendations: 新增 `citation_coverage` 指标（有引用的事实句数/事实句总数），零引用报告强制判失败；`dangling_rate` 在 `total==0` 时返回 `None` 而非 `0.0` 并新增 `has_citations` 布尔门（F-01 / C-01 / C-02）。

**F-16 多租户模型不成立：**
- Risk: `_check_tenant()` 把库中 `runs.tenant_id` 与**进程级环境变量** `VELA_TENANT` 比对。单租户单进程下有效，但生产多租户服务下一个进程需服务多个租户时，环境变量无法随请求变化，机制会退化为"要么全通过要么全拒绝"。
- Files: `src/vela/query/api.py:88-95`（`_check_tenant`）、`src/vela/config.py:120-122`（`tenant_id()` 读取 `VELA_TENANT`）
- Current mitigation: POC 期单租户单进程部署，尚未暴露问题。
- Recommendations: 生产多租户需将租户标识改为随请求传入（如 API 层参数/JWT claim），而非进程级环境变量（F-16，本期明确延后，见风险登记册）。

**SQL 沙箱依赖正则黑名单而非语法白名单/参数化：**
- Risk: `SqlGuard.check()` 用正则黑名单拦截危险关键字与函数（`insert/update/delete/drop/...`、`read_csv/shell/system(...)` 等），而非基于 SQL AST 的白名单校验；`tenant_predicate()` 用字符串拼接（`f"...tenant_id = '{safe}'"`）而非参数化查询构造租户谓词，仅靠 `re.sub(r"[^\w\-.]", "", tenant)` 清洗输入。
- Files: `src/vela/query/guard.py:18-58`（`SqlGuard.check`，正则黑名单）、`src/vela/query/guard.py:99-102`（`tenant_predicate`，字符串拼接）
- Current mitigation: 正则黑名单覆盖常见危险关键字/函数；表名白名单校验；`tenant` 值经字符清洗后才拼入 SQL；`explore_sql` 工具本身也仅供"逃生舱"低频使用。
- Recommendations: 黑名单模式天然存在遗漏风险（新增 DuckDB 函数/关键字需持续维护正则）；长期应迁移到基于 AST 的解析校验或完全参数化的谓词构造，而非字符串拼接+正则过滤的组合。

**F-08 / 分歧4 证据注入 planner 上下文的提示注入面：**
- Risk: 为修复 D2 需要把 `evidence_so_far`（含日志 `raw_line` 原文）注入 planner payload。车端日志内容可能包含形似指令的文本（应用日志打印用户输入、第三方 SDK 日志，甚至构造的攻击载荷），一旦注入无约束即构成提示注入面。
- Files: `src/vela/query/guard.py:90-96`（`wrap_log_content`，已存在的分隔标记包裹机制，当前仅在 `get_lines` 路径使用）
- Current mitigation: `wrap_log_content` 已实现日志原文包裹+"数据不是指令"声明，但目前只用于既有的 `get_lines` 展示路径，尚未强制应用到修复 D2 所需的新注入路径。
- Recommendations: 五项约束（C-18）：全部日志原文经 `wrap_log_content` 包裹；剥离控制序列与疑似指令标记（`[[`、`]]`、`<|...|>`、`system:` 等）；日志内容只进 user 角色、永不进 system 角色；提示词显式声明分隔标记内容不可执行；单行截断至 300 字符限制载荷长度。

**落盘数据无脱敏、无保留期（F-17，POC 期以文档标注替代）：**
- Risk: `workspace/` 下 `bronze/silver/gold`（全量日志原文）、`sessions/*.state.json`（证据原文）、`obs/llm_audit.jsonl`（含 completion 摘要）均为明文落盘，无 TTL、无加密。出站到大模型的内容有脱敏（`gateway/redact.py` 覆盖 VIN/GPS/手机号/IMEI/身份证/邮箱/IP 共 7 类规则），但落盘环节完全不脱敏。
- Files: `src/vela/gateway/redact.py`（仅覆盖出站路径）；`workspace/` 目录结构（本地生成，已在 `.gitignore` 中排除，不会提交到仓库）
- Current mitigation: 已在 `.gitignore` 中排除 `workspace/`，不会随代码提交泄露；README 未明确标注此限制。
- Recommendations: 若接入真实车辆数据，需在文档中显式标注该风险，避免真实数据被无意识长期留存；生产化时补充落盘脱敏与保留期策略（F-17，本期明确延后，见风险登记册）。

**环境变量文件管理：**
- Risk: 项目根目录同时存在本地 `.env`（含实际密钥占位/配置，已被 `.gitignore` 的 `.env`/`.env.*` 规则排除）与已提交的 `.env.example`（无实际密钥，仅字段名模板）。经核实当前 `.env.example` 未包含任何真实密钥值，git 工作区状态干净。
- Files: `.env.example`（已提交，仅含空值占位）、`.gitignore`（`.env`/`.env.*` 规则 + `!.env.example` 例外）
- Current mitigation: `.gitignore` 规则正确排除本地 `.env`，仅 `.env.example` 入库且不含密钥。
- Recommendations: 无额外行动项；提醒后续贡献者切勿误将本地 `.env` 加入版本控制或复制粘贴密钥到示例文件。

## Performance Bottlenecks

**评测迭代成本高（重复建库）：**
- Problem: 每个评测用例都重新执行完整建库流程（约 8 秒/用例 × 10 场景 ≈ 80 秒/轮）。
- Files: `src/vela/eval/runner.py::EvalRunner._one`
- Cause: 未区分"证据库未变化，只需重跑诊断"与"证据库需要重建"两种场景，`--reuse-workspace` 尚未实现。
- Improvement path: 增加工作区复用开关，跳过已存在证据库的重建步骤（F-12 / C-28）。

**缺少 LLM 响应缓存，提示词迭代成本高昂且不可复现：**
- Problem: 每次评测全量重打真实 API：10 用例 × 平均 4 轮 × 4 个逻辑模型 ≈ 100+ 次调用/轮迭代，既昂贵又因非确定性而无法隔离"是提示词改好了"还是"这次运气好"。
- Files: `src/vela/gateway/audit.py`（已计算 `prompt_sha256`，是缓存的现成基础设施）
- Cause: 未按 `(provider, physical_model, prompt_sha256, params)` 做磁盘缓存。
- Improvement path: 新增响应缓存层，`--no-cache` 可关（方差基线测量必须在关闭缓存下进行，避免掩盖真实非确定性）；F-09 / C-14。

**完全没有成本与延迟模型：**
- Problem: 无法回答生产场景的基本问题：单次诊断的 token 成本？P95 端到端延迟？日均千次诊断的月度成本？
- Files: `src/vela/gateway/budget.py::TokenLedger`（只做预算切断，不做成本归集与预测）、`scripts/bench.py`（只测建库吞吐与 mock 诊断延迟，无真实 LLM 延迟基线）
- Cause: 真实 LLM 下 4 轮 × 4 逻辑模型的串行调用，P95 可能是分钟级，直接决定产品形态（同步接口 vs 异步任务），但当前完全未测量。
- Improvement path: 建立成本与延迟基线，扩展 `bench.py` 覆盖真实 LLM provider（F-13 / C-36）。

**中文分词是轻量规则实现（README 自述局限）：**
- Problem: FTS 检索在中文长句上的召回率弱于工业级方案。
- Files: `src/vela/evidence/fingerprint.py::tokenize_for_search`（中文 bigram + 英文词切分）
- Cause: 非成熟分词器，为 POC 阶段的务实取舍。
- Improvement path: 生产化时评估接入专业中文分词库或依赖真实 embedding 语义检索。

## Fragile Areas

**度量体系存在双重循环验证（评测分数不可信为"真实能力"）：**
- Files: `src/vela/agent/citations.py`（F-01 零引用悖论）、`src/vela/agent/graph.py:423` + `src/vela/sim/generate.py`（F-04 信号提取器与仿真器格式耦合）
- Why fragile: 仿真器、信号提取器、mock 打分器三者共享同一套格式约定，形成自我确认的闭环；当前 44.4%（真实 LLM 首次实测）本身也缺乏统计置信区间（9 个故障用例，单例对错造成 ±11.1pp 跳变，且无重复评测机制）。
- Safe modification: 任何基于评测分数的优化收益估算都应先建立方差基线（`vela eval run --repeat N`，尚未实现，见 C-12）；区分"逻辑必然缺陷"（可无统计前置直接修复，如 D1/D4）与"行为调优类改动"（必须在方差基线上用置信区间判定）。
- Test coverage: 现有 177 个测试全部基于 mock provider，`mock.py` 按设计意图而非提示词字面实现（不读提示词正文），凡"提示词字面"与"mock 行为"不一致之处，测试全部覆盖不到。

**技能候选集全零分之外无任何"知道自己不知道"的机制（消融实验已实测两个失效模式）：**
- Files: `src/vela/agent/graph.py::_root_cause`（根因判定的 `has_error` 判据只检查 `st.evidence_pool`，不检查数据库全集）
- Why fragile: 消融实验剔除正确技能后，系统输出 `no_fault_found`——但数据库中确实存在明文写着 `campaign aborted ... reason=UDS_NRC_0x72` 的 ERROR 行（FM-2 假阴性）；剔除另一组技能后，系统选中语义近邻技能给出权威口吻的错误处置建议，且悬空引用率仍为 0.0（FM-1 静默误诊）。两种失效**都不会触发任何现有告警**。
- Safe modification: 新增全局未解释错误哨兵——报告落地前做一次 `SELECT count(*) FROM log_lines WHERE level_num>=40` 类不变量检查，若存在从未被任何探针取回的错误行则禁止输出 `no_fault_found`（L0 哨兵，纯 SQL 不变量，成本极低，见"技能知识库深度分析报告" §3.3）。
- Test coverage: 现有 10 场景黄金评测集全部是"已知模式的参数变体"（README 自述"L1 参数泛化已具备"），完全不覆盖"未知故障模式"场景；消融评测集（逐个剔除正确技能构造未知故障用例）尚未建立。

**`_root_cause` 单标签假设与真实级联故障不符：**
- Files: `src/vela/agent/graph.py::_root_cause`（返回单个 `label`，`decisive` 一旦成立即 `break`）
- Why fragile: 真实 OTA 失败常见级联形态（如"存储不足→下载分片失败→重试风暴→超时中止"，4 个症状对应 1 个真实根因）会被系统命中为直接症状对应的错误标签（如误判为下载超时而非存储不足）。
- Safe modification: 本期仅做数据结构预留（`root_cause.contributing_chain` 字段），不改评测口径、不投入推理逻辑（已达成共识延后，见下方决策记录）。
- Test coverage: 当前 9 个故障用例全部是单根因场景，无法验证多根因路径。

**`ts_confidence` 从未真正参与结论把关（机制名不副实）：**
- Files: `src/vela/evidence/timeline.py`（`ts_confidence` 完整计算与落库）、`src/vela/agent/graph.py::_root_cause`（`decisive` 判据完全不引用 `ts_confidence`）
- Why fragile: 全部证据 `ts_confidence=0.35`（纯 monotonic 无锚点）的会话与全部 `0.95` 的会话，收敛判据完全相同；时序不可判时得出的因果结论（"A 导致 B"）本应降级为相关性表述，当前以同等口吻输出因果判断。
- Safe modification: 低置信度证据链的因果结论需在报告措辞层面降级（C-20），需先完成置信度分级机制（C-21）。
- Test coverage: 未见专门验证低 `ts_confidence` 场景下报告措辞降级的测试用例。

**知识蒸馏候选池只写不读，且无去重：**
- Files: `src/vela/agent/graph.py::node_distill`（每个 `answered` 会话追加候选到 `candidates.jsonl`）
- Why fragile: 全项目对 `candidates.jsonl` 仅一处写入、零处读取——闭环缺失最后一环；同一故障模式跑 100 次会产出 100 条近似重复候选，无任何去重机制（Jira 挖掘管线设计了症状 Jaccard>0.7 去重，但会话蒸馏未套用同款约束）。
- Safe modification: 补充 `vela knowledge promote/review` 子命令消费候选池，并对会话蒸馏施加与 Jira 挖掘同等的去重约束（F-19 / C-33）。
- Test coverage: 无针对候选池消费路径的测试（因为该路径当前不存在）。

## Scaling Limits

**单机单进程 DuckDB（README 自述局限）：**
- Current capacity: 10 场景仿真数据集约 23 万条记录，单文件 DuckDB + Parquet 列存足够支撑 POC 演示与评测。
- Limit: 生产量级（数亿行/天）需要迁移列式库；DuckDB 单文件数据库未做分布式设计。
- Scaling path: 项目已在 `docs/PRODUCTION_MIGRATION.md` 中规划迁移到 ClickHouse/StarRocks（Schema 与 SQL 基本兼容）；触发条件为"单日日志 > 千万行"（多专家评审共识，本期明确不做）。

**技能库规模化后混合召回会退化：**
- Current capacity: 12 个内置技能，稠密哈希向量 ∪ 词面命中的混合召回，实测 100% 正确命中。
- Limit: 技能数增长到 30+ 时会出现评审冲突（多人改同一文件）、检索退化（关键词空间重叠）；`skills.py::retrieve` 的关键词匹配是最脆弱环节，换个日志措辞即失效。
- Scaling path: 先按域拆分为多文件（加载器已支持 `glob("*.yaml")`，零代码改动）；再加维度预过滤（按 `phase_scope`/`ecu_scope`/`module_scope` 收窄候选池，零 token 成本）；技能到千级规模再考虑向量库（FAISS/Milvus），当前触发条件设为"技能数 > 100"（多专家评审共识，本期明确不做）。

**向量召回当前是本地哈希向量，非真实 embedding：**
- Current capacity: `agent/skills.py::embed_local` 本地哈希向量在 12 技能规模下够用。
- Limit: 技能规模扩大后语义区分度不足。
- Scaling path: 接口已在 `gateway/openai_compat.py::embed` 备好，可直接切换到火山引擎方舟 `/embeddings`（README「向生产平台过渡」章节）。

## Dependencies at Risk

**当前依赖均为主流稳定包，无明确弃用风险：**
- `duckdb>=1.0` / `pyarrow>=14` / `PyYAML>=6.0` / `pytz>=2024.1`（`pyproject.toml` 必需依赖）、可选依赖 `xxhash`/`blake3`（加速）、`fastapi`/`uvicorn`（服务，若不可用会退化到标准库 `http.server`，见 `src/vela/server/app.py` 头部说明）、`pytest>=8.0`（开发依赖）。
- Risk: 无重大风险；`fastapi`/`uvicorn` 为可选依赖，其缺失已有标准库兜底路径，耦合度低。
- Impact: 不适用。
- Migration plan: 无需立即行动；常规版本升级维护即可。

## Missing Critical Features

**多次重复评测与方差基线：**
- Problem: `vela eval run` 单次跑完即出报告，无 `--repeat N` 机制，无法输出均值±标准差或置信区间。
- Blocks: 任何"改一项→测一次→看涨跌"的迭代优化都可能是在追逐噪声（真实 LLM 44.4% 首测样本量仅 9 个故障用例，±11.1pp 单例跳变）；F-02 / C-12。

**双基准分离（回归门 vs 能力门）：**
- Problem: 当前只有仿真评测集一套基准，同时承担"回归防护"与"能力宣称"两种用途，但 F-04（信号提取器与仿真器循环耦合）表明仿真分数不能代表真实能力。
- Blocks: 无法产出可对外宣称的真实准确率数字；多专家评审共识要求从历史 Jira 工单构建 30~50 例人工标注的真实基准（C-19），作为唯一的准确率宣称依据，当前尚未启动。

**过程指标聚合报表：**
- Problem: 当前评测只记录终局结果（`CaseResult`），中间决策全部散落在 `events.jsonl` 与 session JSON 里，未被聚合进任何报表；归因分析需要人工写脚本刨日志（本次三份 `explore-docs` 分析报告均采用此方式）。
- Blocks: 无法快速定位"准确率低"具体卡在哪个环节（首轮 stop / JSON 解析失败 / 截断 / verifier 判据过严 / 技能游走）；F-03 提出的 7 项过程指标（`premature_stop_rate`、`llm_parse_failure_rate`、`llm_truncation_rate`、`verdict_supported_ratio`、`skill_switch_per_session` 等）尚未接入报表。

**结论反馈回路（线上准确率不可观测）：**
- Problem: 系统能蒸馏知识候选，但无法知道自己给出的诊断结论最终对不对。
- Blocks: 生产环境唯一可靠的准确率来源应是"工程师最终确认的根因 vs 系统判定"的比对，当前完全没有这条回路；技能库分析报告 §6.5 提出的影子期"与人工最终结论一致率"也因此没有数据来源（F-15 / C-35）。

## Test Coverage Gaps

**真实 LLM 行为路径完全未被测试覆盖：**
- What's not tested: mock provider 按"设计意图"而非"提示词字面"实现（例如从不真正读取提示词正文中的 stop 条件，只按关键词打分），导致所有"提示词字面要求"与"mock 实际行为"不一致的缺陷（D1-D6，见上方 Known Bugs）对 177 个现有测试全部不可见。
- Files: `src/vela/gateway/mock.py`（mock provider 实现）、`tests/test_agent.py`（207 行，推理平面测试，全部基于 mock）
- Risk: mock 测试通过 ≠ 真实 LLM 行为正确；已实测真实 LLM 首次接入准确率从 mock 的 100% 跌至 44.4%。
- Priority: High（已有明确的修复优先级排序，见 `explore-docs/VELA-真实LLM准确率归因分析与优化方案.md` §5 与 `...多专家联合评审...md` §7）。

**消融场景（技能库不完整时的降级行为）无测试覆盖：**
- What's not tested: 剔除正确技能或整族相关技能后系统的降级行为（静默误诊 FM-1、假阴性 FM-2）。
- Files: 无对应测试文件；消融实验是本次 `explore-docs/VELA-技能知识库深度分析报告.md` 手工构造并实测的，未固化为自动化回归用例。
- Risk: 技能库任何调整（新增/修改/删除技能）都可能引入同类静默失效，而不会被现有测试捕获。
- Priority: High（多专家评审共识：消融评测集应作为"唯一能持续度量泛化能力"的手段）。

**零引用/低引用报告场景无测试覆盖：**
- What's not tested: reporter 输出完全没有 `[[EV:row_hash]]` 引用时，`CitationReport.ok` 是否正确判定为失败（当前实现下反而判定为 `True`）。
- Files: `src/vela/agent/citations.py`（缺少 `total==0` 分支的专门单测）
- Risk: 这是当前系统"最核心的质量闸门"存在的结构性盲区，真实 LLM 最可能的失效方式之一（不遵循引用格式）在指标上表现为满分而非零分。
- Priority: High（F-01，属于"逻辑必然缺陷"类别，可无统计前置直接修复并补测试）。

**提示注入场景无测试覆盖：**
- What's not tested: 日志原文中包含形似指令的文本（如 `system:`、`<|...|>`、`[[...]]` 等控制序列）被注入 planner 上下文后的处理是否安全。
- Files: `src/vela/query/guard.py::wrap_log_content`（防护机制已存在，但仅用于既有展示路径，未见针对性的对抗测试用例）
- Risk: 修复 D2（planner 反馈闭环）需要把更多日志原文注入 planner payload，这会扩大注入面；若无对抗测试保护，未来改动可能无意间引入注入漏洞。
- Priority: Medium（当前尚未实施注入路径扩展，风险是前瞻性的；C-18 落地时应同步补充对抗测试用例入回归集）。

**成本与延迟基线完全缺失：**
- What's not tested: 真实 LLM provider 下端到端延迟（P95）与 token 成本没有任何基准测量或断言。
- Files: `scripts/bench.py`（当前只测建库吞吐与 mock 诊断延迟）
- Risk: 无法评估生产化后的响应时间与成本是否可接受，也无法在改动引入性能回归时察觉。
- Priority: Medium（F-13，属于生产化前置工作，非当前 POC 阶段的阻断项）。

---

*Concerns audit: 2026-07-30*
