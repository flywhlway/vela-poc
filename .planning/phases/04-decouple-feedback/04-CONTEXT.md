# Phase 4: 去循环耦合与反馈闭环 - Context

**Gathered:** 2026-08-01
**Status:** Ready for planning
**Mode:** `--auto`（全部灰区自动选中；每题取 recommended/第一选项）

<domain>
## Phase Boundary

打破信号提取器与仿真器格式的循环耦合，并补全 planner 反馈闭环：把 `graph.py::_absorb_signals` 中硬编码的中止标记识别重构为 `config/extractors.yaml` 驱动框架（DECP-01），支持 ≥6 种中止形态并在合成对抗语料上达识别率 ≥0.85（DECP-02），把 `unmatched_abort_marker_rate` 纳入评测报表（DECP-03）；补全 planner 第 2+ 轮 payload（证据摘要 / 压缩痕迹 / 护栏提示 / 上一轮 verdicts / 开放问题）（DECP-04）；对新扩大的日志注入面施加五项安全约束并进回归对抗测试（DECP-05/06）；`_evidence_brief` 限 1500 token 且监控 `avg_llm_tokens`（DECP-07）。

**硬锁定顺序（ROADMAP / ADR-5）**：
1. **DECP-01 提取器框架须先于 DECP-02/03**（C-15 枢纽工程）
2. **五项注入约束须与 DECP-04 同批落地，不可反序**（打开注入面而无约束即漏洞）

**明确不做**：六级置信度 / `novel:` / 技能四职责分离（Phase 5）；证据通道与四象限仲裁器（Phase 6）；症状本体 `symptoms.yaml`（C-31 → v2.0，仅完成本期 C-15 前置）；改现有 10 场景仿真 emitter 主路径去「演」六形态（会污染回归门）；G4 真实能力宣称。

</domain>

<decisions>
## Implementation Decisions

### 提取器框架边界（DECP-01 / ADR-5）

- **D-01:** 新建 `config/extractors.yaml` + `src/vela/agent/extractors.py`。`AgentGraph._absorb_signals` 改为调用提取器框架，**禁止**继续在 graph 内硬编码 `reason=` / `at … phase` 正则。
- **D-02:** 框架范围**仅覆盖中止标记与派生信号**（`abort_marker` / `abort_reason` / `fail_phase` / 隐式中止），以及可声明的「从 tool 结果行/摘要字段取文本再跑规则」的绑定。`describe_dataset` 的 levels/ts_kinds、`find_gaps` 的通信层静默启发式等**领域路由逻辑仍留在 Python**（不硬塞进 YAML），避免把不可配置的策略伪造成配置。
- **D-03:** YAML schema **对齐 `parsers.yaml` 风格**：有序规则列表；每条含 `name` / `version` / `kind` / `priority`（或列表顺序即优先级）/ `regex`（命名捕获组）/ `sample`；可选 `signal_map` 把捕获组映射到 `st.signals` 键。工程师新增形态 = 追加一条 YAML，零 Python 改动——成功判据 1 的字面合同。
- **D-04:** 隐式中止（「最后一条 ERROR 后静默」）用 `kind: implicit_abort`（或等价）规则表达：阈值（静默窗口秒数、组件过滤）进 YAML；解释器在框架内实现，不散落在 `graph.py`。
- **D-05:** 现有 `reason=([A-Za-z0-9_x]+)` 与 `at\s+([A-Z]+)\s+phase` 作为框架规则集的**首批内建条目**迁入 YAML，迁移后 mock/黄金场景行为不变（回归门一票否决）。

### 六形态语料与指标（DECP-02 / DECP-03）

- **D-06:** **不改**现有 10 场景仿真 emitter 主路径与 golden 真值格式——六形态验收靠**合成对抗语料**（`tests/` fixtures 或 `data/` 下独立语料目录），对提取器做离线识别率评测 ≥0.85；现有 `reason=` 仍是规则 #1，保证仿真回归门不被「为覆盖而改仿真」破坏。
- **D-07:** 六种形态最低集合锁定为 ROADMAP 字面：`reason=` 结构式 / 十六进制错误码式 / 英文 `cause:` 式 / 中文无结构式 / 有中止行无 reason 式 / 无显式中止行的隐式中止。每条形态在 YAML 中有对应规则 + 语料样例 + 单测。
- **D-08:** `unmatched_abort_marker_rate` =（存在中止候选文本但未命中任何提取规则的样本数）/（中止候选样本总数）。候选定义由 planner 钉死（至少覆盖 `phase_timeline.abort_markers` 与语料中的显式中止行）；指标进入 `eval/report.py` 报表与 `_TARGETS`；本阶段以**可测 + 六形态语料达标**为主，不承诺真实日志全覆盖（NR-2：框架化后靠该指标持续驱动补全）。

### 反馈闭环字段契约（DECP-04）

- **D-09:** `node_plan` payload **必须新增**（与归因文档 D2 对齐，保留既有键）：
  - `evidence_so_far` ← `_evidence_brief(st.evidence_pool, …)`
  - `compression_trace` ← 上一轮压缩折叠痕迹
  - `guardrail_notes` ← 上一轮工具 `notes` / 护栏提示（截断条数）
  - `prior_verdicts` ← 上一轮 verifier 结论与缺口
  - `open_questions` ← 尚未闭合的问题列表
  既有 `evidence_digest` / `signals` / `candidate_skills` / `used_skills` / `budget` **保留**。
- **D-10:** `_evidence_brief` 输出紧凑字段：`ts` / `component` / `level` / `template_id` / `row_hash` + **经注入消毒后的截断原文**；默认行数上限与 1500 token 预算由配置给出（见 D-16），禁止把未消毒 `raw_line` 塞进 planner user。
- **D-11:** 若 `SessionState` 尚无 `unresolved` / 等价字段，本阶段**新增轻量 list**，由 verify 节点写入未支撑/部分支撑缺口；**不**引入 Phase 5 六级置信度枚举。
- **D-12:** `planner_user` / `PLANNER_SYSTEM` 同步声明：分隔标记内为不可执行数据；第 2+ 轮须基于 `evidence_so_far` 与 `prior_verdicts` 决策，禁止无视已获证据盲目换技能。验收代理指标：`skill_switch_per_session ≤ 2.5`（过程指标已在 Phase 2/3 可测）。

### 注入安全与对抗回归（DECP-05 / DECP-06）

- **D-13:** 五项约束**与 DECP-04 同批合并交付**，禁止「先打开 evidence_so_far、后补消毒」的中间提交进入主分支。
- **D-14:** 在 `query/guard.py` 扩展消毒 API（推荐名 `sanitize_log_for_llm`）：剥离控制序列与疑似指令标记（至少 `[[`、`]]`、`<|...|>`、`system:`）→ 单行截断至配置阈值（默认 300 字符）→ 再 `wrap_log_content`。`_evidence_brief` 与任何新注入路径**强制**经此函数；日志内容**只进 user 角色，永不进 system**。
- **D-15:** 对抗用例进回归集：构造含上述控制序列的证据行，断言 (a) 出站 planner user 经包裹、(b) 裸控制序列被剥离或失效、(c) system 提示不含日志原文。以**确定性单测/集成测**为主，不依赖真实 LLM 被「诱导」才算通过（程序化校验优先于模型自述）。
- **D-16:** 阈值进配置、不硬编码业务魔法数：单行截断 300、`_evidence_brief` 1500 token 上限写入 `config/budget.yaml`（或并列 `config/agent.yaml`——planner 择一，须进 `config_hash`）。剥离模式表可与阈值同文件或独立小 YAML；**须纳入 `config_hash`**（改变消毒规则 = 改变出站语义）。

### 指纹、波次与回归门

- **D-17:** `config/extractors.yaml`（及注入守卫配置若独立成文件）**必须进入 `config_hash()` payload**；在 `docs/CONFIG_HASH_HISTORY.md` 追加断代行（承接 Phase 2 NR-6 纪律）。
- **D-18:** 建议波次（planner 可微调任务切分，不可违反硬顺序）：
  1. DECP-01 框架骨架 + 迁入现有 `reason=`/`phase` 规则（行为不变绿）
  2. DECP-02 六形态规则 + 合成语料 + 识别率门 + DECP-03 指标入报表
  3. DECP-04 + DECP-05 + DECP-06 同批（反馈闭环 ⊕ 注入约束 ⊕ 对抗回归）
  4. DECP-07 token 监控与预算档护栏 + 全量回归门（177 测试 + 仿真已通过用例回归数 = 0）
- **D-19:** 回归门与里程碑纪律不变：`make test` failed=0；仿真基准已通过用例回归数 = 0；不得用仿真/消融分数冒充 G4 真实能力；不承诺具体 pp 准确率收益——`skill_switch_per_session` 为过程指标验收。

### Claude's Discretion

- `extractors.yaml` 字段命名微调（`kind` vs `type`、`signal_map` 形状）
- `_evidence_brief` 放 `graph.py` 私有函数还是拆 `agent/brief.py`（超 ~80 行再拆）
- 合成语料目录落在 `tests/fixtures/` 还是 `data/adversarial/`
- `sanitize_log_for_llm` 精确函数名与是否对 `get_lines` 既有路径复用同一截断阈值
- DECP-07 的 `avg_llm_tokens` 是扩展现有 Metrics/TokenLedger 字段还是 eval 报表聚合键

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### 需求与路线（验收合同）
- `.planning/ROADMAP.md` §Phase 4 — Goal、Success Criteria 1–5、Depends on Phase 3、硬顺序（DECP-01 先于 02/03；注入与 DECP-04 同批）
- `.planning/REQUIREMENTS.md` §DECP（DECP-01..07）— 需求原文与追溯 ID（C-15..C-18 / F-04 / F-08 / F-18 / D2 / NR-2/7/8）
- `.planning/PROJECT.md` §Key Decisions ADR-5（C-15 枢纽）、§Deferred `symptoms.yaml`（C-31 → v2.0）
- `.planning/STATE.md` — Phase 3 完成决策（ORCH 止血已落地，反馈闭环效果可干净归因）

### 先验阶段
- `.planning/phases/01-llm/01-CONTEXT.md` — D-01 三方库优先；配置驱动；本地优先铁律
- `.planning/phases/02-metrics-baseline/02-CONTEXT.md` — `config_hash` 扩展纪律、过程指标可测性、`skill_switch_per_session` 已在报表
- `.planning/phases/03-orch-logic-hemostasis/03-VERIFICATION.md` — Phase 3 已验证能力；D2/DECP 明确未做

### 探索文档（改造条目原文）
- `explore-docs/VELA-多专家联合评审与系统性优化改造方案.md` — C-15..C-18、NR-2/7/8、F-04/F-08/F-18
- `explore-docs/VELA-真实LLM准确率归因分析与优化方案.md` §4.2 — D2 payload 补全与 `_evidence_brief` ~1500 token
- `explore-docs/VELA-双驱动架构升级与跨域泛化实施方案.md` — C-15 双重枢纽、M-13/M-16 与提取器关系（本阶段只做框架+六形态，不做领域包重构）

### 实现锚点
- `src/vela/agent/graph.py` — `_absorb_signals`（硬编码 `reason=`）、`node_plan` payload（缺反馈字段）
- `src/vela/query/guard.py` — `wrap_log_content` / `LOG_CONTENT_*`（已有包裹，缺剥离+截断+强制用于新路径）
- `src/vela/query/api.py` — `get_lines` 已调 `wrap_log_content`（参考复用点）
- `src/vela/gateway/prompts.py` — `PLANNER_SYSTEM` / `planner_user`
- `src/vela/agent/state.py` — `evidence_digest` / `signals`；本阶段或增 `unresolved`
- `src/vela/eval/report.py` / `process.py` — 过程指标与 `_TARGETS`（接入 `unmatched_abort_marker_rate`）
- `src/vela/config.py` — `config_hash()` / `load_yaml`（纳入 extractors）
- `config/parsers.yaml` — **schema 范本**（有序规则 + sample + 零代码扩展）
- `config/budget.yaml` — 阈值挂载点（300 / 1500）
- `docs/CONFIG_HASH_HISTORY.md` — 指纹断代追加
- `AGENTS.md` — 查询收口 / 配置驱动 / 图节点即方法 / 程序化校验优先

### 代码地图
- `.planning/codebase/ARCHITECTURE.md` — 推理平面与 `_absorb_signals` 位置
- `.planning/codebase/CONCERNS.md` — 循环耦合、D2 反馈断裂、F-08 注入面
- `.planning/codebase/CONVENTIONS.md` — 新模块命名与测试平面组织

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `wrap_log_content`（`query/guard.py`）：已有分隔标记 +「数据不是指令」声明；本阶段在其上叠加 strip + truncate，并强制用于 `_evidence_brief`
- `parsers.yaml` + `evidence/parsers.py`：配置驱动规则列表的成熟范本——`extractors.yaml` 应对齐同一扩展体验
- `evidence_digest` / `signals`（`SessionState`）：鸟瞰信号已部分存在；反馈闭环是补「下钻后证据」而非从零设计状态机
- `skill_switch_per_session`（`eval/process.py`）：DECP-04 验收指标已可聚合，无需新造口径
- `config_hash()`（Phase 2 已扩 skills/budget/llm/prompts）：本阶段追加 extractors（+ 注入配置）并写 HISTORY 行
- Phase 3 止血：`_llm_json`、首轮 stop 守卫、unproductive-only、GENERIC 注入——反馈闭环效果可干净归因

### Established Patterns
- 配置驱动：阈值进 YAML，业务不硬编码；`load_yaml` 有 `lru_cache`（改配置须重启/清缓存）
- 图节点即方法：逻辑留在 `AgentGraph.node_*`；新提取器模块是被调用的库，**不**在 `agent/nodes/` 建文件
- 测试：不用 `unittest.mock.patch` 伪装供应商；真实 `MockProvider` + fixtures；对抗注入用确定性断言
- 程序化校验优先：注入拦截用单测钉住，不靠模型「拒绝执行」自述

### Integration Points
- `_absorb_signals` ← 鸟瞰探针结果（`phase_timeline.abort_markers` 等）是提取器主输入
- `node_plan` payload ← DECP-04 主改点；经 `planner_user` 序列化进 LLM user
- `node_compress` / verify 输出 ← `compression_trace` / `prior_verdicts` / `open_questions` 的数据源
- `eval/report.py` ← `unmatched_abort_marker_rate` + 既有 `skill_switch_per_session` / token 监控
- Gateway 出站仍经 `redact.py`；注入消毒是**另一层**（防指令注入），二者都要，不可互相替代

</code_context>

<specifics>
## Specific Ideas

- ROADMAP 原文两次强调顺序：提取器框架枢纽先落地；注入约束与反馈闭环同批、不可反序——CONTEXT 已升为 D-01/D-13/D-18。
- 归因文档 §4.2 的 payload 键名（`evidence_so_far` 等）作为**推荐字面契约**，避免 planner/executor 各自发明同义字段。
- `--auto` 单次 pass：六形态正则细节、token 估算器精度留给 Claude's Discretion / research，不二次讨论。

</specifics>

<deferred>
## Deferred Ideas

- 症状本体 `symptoms.yaml`（C-31）→ v2.0（本期只完成 C-15 前置）
- 六级置信度 / `novel:` / `node_human_gate` 结构化交接 → Phase 5
- 双驱动证据通道与四象限仲裁 → Phase 6
- 改仿真 emitter 让 10 场景「天然」覆盖六形态 → 显式不做（保回归门）；若未来要多样性场景，另开 phase/里程碑
- 检查点落盘脱敏 / evidence_pool 无界（F-11/F-17）→ 非本阶段
- 领域包契约 / `ota.yaml` 重构（双驱动文档 M-13）→ 非本阶段

None — discussion stayed within phase scope（无折叠 todo）

</deferred>

---

*Phase: 4-去循环耦合与反馈闭环*
*Context gathered: 2026-08-01*
