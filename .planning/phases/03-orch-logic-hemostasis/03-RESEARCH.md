# Phase 3: 编排层逻辑止血 - Research

**Researched:** 2026-08-01
**Domain:** Agent 编排控制流 / LLM 输出契约 / 程序化守卫（逻辑必然缺陷）
**Confidence:** HIGH

## Summary

Phase 3 修复编排层十项**逻辑必然缺陷**（ORCH-01..10）。这些缺陷在 mock 供应商下因「按设计意图而非提示词字面实现」而完全测不出；Phase 2 真实 LLM 基线已提供过程指标锚点：`llm_parse_failure_rate≈0.63`、`llm_truncation_rate≈0.25`、`verdict_supported_ratio≈0.37`、`unexplained_error_rate≈0.63`（`premature_stop_rate` 本批实测为 0，但提示词第 5 条与首轮守卫仍属结构性必修）。[VERIFIED: `.planning/phases/02-metrics-baseline/baseline/eval_report.md`]

实现重心全部在现有代码路径：`AgentGraph` 节点方法、`SessionState.excluded_skills`、`_parse_json`/`_llm`、`prompts.py`、`config/llm.yaml`、`skills.py` + `builtin.yaml`，以及 Phase 2 已落地的过程指标聚合（需从代理口径升级为真实事件口径）。**不引入新第三方包**；未解释错误扫描必须经 `LogQueryAPI.call()`（禁止探索文档中的 `api._q` 直连）。[VERIFIED: `AGENTS.md` 架构铁律]

**Primary recommendation:** 按「程序化守卫优先于提示词」落地：先改控制流与解析/截断/剔除/引用/覆盖不变量（可单测），再改提示词与 claim 语义；验收以确定性过程指标对照 Phase 2 新基线，禁止再引用 44.4%。

<user_constraints>
## User Constraints（无 CONTEXT.md — 自 REQUIREMENTS / ROADMAP / explore-docs 锁定）

### Locked Decisions
- ADR-4：ORCH 全部为逻辑必然缺陷 → 用确定性过程指标验收，**无需统计前置**；全文不承诺具体 pp 收益。
- ADR-2 后果：效果对比一律相对 Phase 2 方差基线（`.planning/phases/02-metrics-baseline/baseline/`），**不得再引用 44.4%**。
- 需求集合固定为 ORCH-01..ORCH-10（C-04/C-05/C-09/C-10/C-07/C-08/C-06/C-03/C-22/C-23）；D2 planner 反馈闭环属 Phase 4（DECP-04），本阶段不做。
- 成功标准五条（ROADMAP Phase 3）与回归门（177 测试全绿 + 仿真已通过用例回归数 = 0）硬约束。
- 架构铁律：Gold 只经 `LogQueryAPI.call()`；配置驱动；Provider 抽象；程序化校验优先于模型自述；图节点即 `AgentGraph` 方法；无 `logging` 模块，用 EventBus；本地优先。
- Phase 1 D-01：能用成熟库则不手写；本阶段**无新依赖需求**。
- NR-4：ORCH-08 引用阈值先宽（证据链条目的 50%）观察分布再收紧。
- mock vs real：mock 不读提示词正文——单测必须直接驱动守卫/解析/剔除逻辑，不能指望 mock 复现 D1。

### Claude's Discretion（推荐默认）
- `_llm` 升级为返回完整 `LLMResponse` 的内部路径，并新增 `_llm_json(logical, system, user, retries=2)` 统一解析重试；业务节点不再各自手写重试环。
- 探针去重键：`(skill_id, args_hash)`，`args_hash = blake2b(canonical_json(args), digest_size=8).hexdigest()`；状态字段落在 `SessionState`（如 `executed_probes: list[str]`）。
- 未解释错误扫描：经 `api.call("search_logs", query="", mode="substring", min_level="ERROR", limit=…)`（与 runner 现有代理口径一致），与 `evidence_pool` 的 `row_hash` 差集比对；禁止 `api._q`。
- `insufficient_coverage` / `insufficient_citation` 作为新的 `SessionState.status`（或 `root_cause.label` + status 组合）；评测侧将二者从「健康假阴性 / no_fault_found」路径排除，避免污染 healthy_specificity。
- 引用不足阈值键入 `config/budget.yaml`（如 `report.min_citation_ratio: 0.5`），便于 NR-4 后续收紧。
- verifier 单批 claims 上限 5（配合 max_tokens=2048）；decisive：`supported` 或 `≥2 partial`（探索文档钉法）。
- 连续 barren 轮次 2→3：**不做**（探索文档建议，但非 ORCH 范围；留给 Phase 4 若需要）。
- reporter `max_tokens` 保持 2048（ORCH-04 只锁 planner/verifier）；不顺带改到 4096。
- 过程指标：出现真实 `llm.parse_failure` / `llm.truncation` / `plan.stop_rejected` 事件后，`eval/process.py` 优先计真实事件，代理口径降为 fallback 并更新脚注。

### Deferred Ideas (OUT OF SCOPE)
- DECP-*（提取器框架、planner 反馈闭环、注入安全）
- CONF-* / SKIL-* / DUAL-*（六级置信度、novel 开放根因、技能 Schema v2、证据通道）
- mock 改为「字面遵循提示词」（探索文档建议，非本阶段需求）
- `vela eval compare mock/real` 子命令
- 连续 barren 阈值调参、reporter 4096、候选集瘦身（C-25，属 SKIL-02）
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ORCH-01 | 首轮禁止 stop；`plan.stop_rejected`；`premature_stop_rate ≤ 0.05` | `node_plan` 解析后守卫；见 § Architecture Patterns / Code Examples |
| ORCH-02 | 提示词第 5 条重写（调查 vs 定论） | `PLANNER_SYSTEM` 规则 5；与 ORCH-01 联合 |
| ORCH-03 | `_parse_json` 加固 + 重试 2 次 + ALERT；`llm_parse_failure_rate ≤ 0.02` | 去掉跨段 `{}` 提取；`_llm_json`；指标从代理升级 |
| ORCH-04 | planner/verifier `max_tokens=2048` + `finish_reason==length` 告警；`llm_truncation_rate ≤ 0.02` | `llm.yaml` + gateway chat 路径感知截断 |
| ORCH-05 | verifier 枚举归一化 + `partial` 可推进；`verdict_supported_ratio ≥ 0.6` | `_norm_status` + decisive 放宽 |
| ORCH-06 | claim 改为根因假设，多证据支撑 | `node_verify` claims 构造 + `VERIFIER_SYSTEM` |
| ORCH-07 | 剔除回归 unproductive-only + `(skill_id, args_hash)` 去重 | `state.py` + retrieve/plan 探针过滤；改写既有单测 |
| ORCH-08 | 引用数 ≥ 链长 50%，不足重试一次 → `insufficient_citation` | `node_report` + citations 计数 |
| ORCH-09 | 落地前全局未解释错误哨兵；禁 `no_fault_found`；→ `insufficient_coverage`；`unexplained_error_rate ≤ 0.05` | `_unexplained_error_sweep` via LogQueryAPI |
| ORCH-10 | `SK-GENERIC-EVIDENCE-FIRST` + `fallback_only`；全零分注入 | `builtin.yaml` + `skills.retrieve` |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| 首轮 stop 守卫 / 技能剔除 / 探针去重 | API / Backend（`agent/`） | — | 控制流不变量，必须程序化，不信任模型 |
| 提示词契约（planner/verifier） | API / Backend（`gateway/prompts.py`） | — | 与守卫双层防御 |
| JSON 解析 / 截断感知 / max_tokens | API / Backend（`gateway/` + `graph`） | Config（`llm.yaml`） | 输出契约与供应商无关 |
| Verifier 判据与 claim 语义 | API / Backend（`graph.node_verify`） | — | 消除循环论证与脆弱匹配 |
| 报告引用比例闸门 | API / Backend（`graph.node_report` + `citations`） | Config（阈值） | 程序化校验优先于模型自述 |
| 未解释错误不变量 | Database / Storage（经 Query Plane） | API / Backend | SQL 事实 vs 会话 evidence_pool |
| 兜底技能注入 | API / Backend（`skills` + config YAML） | — | 配置驱动技能，零分时注入 |
| 过程指标验收 | API / Backend（`eval/process.py`） | — | Phase 2 基础设施；本阶段升级口径 |
| Browser / SSR / CDN | — | — | 本阶段无前端 |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| 现有 Python 运行时 | ≥3.11（本机 3.12.13） | 实现语言 | 项目约束 [VERIFIED: `pyproject.toml` / `python3 --version`] |
| duckdb / pyarrow / PyYAML / pytz / python-dotenv / openai | 已装于 `.venv` | 主链路依赖 | 铁律 + Phase 1 D-01；本阶段不新增 [VERIFIED: `.venv` import] |
| pytest | ≥8（dev） | 单测 / 回归门 | 既有 `make test` / `test-fast` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| 标准库 `json` / `hashlib` / `re` | stdlib | 解析、args_hash、状态归一化 | ORCH-03/07 |
| EventBus / Metrics | 项目内 | ALERT 与计数器 | 所有守卫与失败路径 |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| 加固 `json.loads` + 围栏剥离 | 引入 `json-repair` 等库 | 违反「无必要不增依赖」；json_mode 已保证对象形态，重试足够 |
| 新 SQL 工具 `unexplained_errors` | 复用 `search_logs` | 复用零 schema 膨胀；注意 `query` 必填可用 `""` [VERIFIED: `tools.py` + runner] |
| 提示词 few-shot 纠正 D1 | 仅提示词、无守卫 | 探索文档明确不足；必须程序守卫 |

**Installation:** 无。`make install-dev` 已足够。

**Version verification:** 本阶段无新包；`pip index` / slopcheck 不适用。若 planner 误加依赖 → 必须走 Package Legitimacy Gate。

## Package Legitimacy Audit

> 本阶段**不安装**外部包。

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| — | — | — | — | — | — | N/A — no installs |

**Packages removed due to slopcheck [SLOP] verdict:** none  
**Packages flagged as suspicious [SUS]:** none  

*slopcheck 未运行（无候选包）。*

## Architecture Patterns

### System Architecture Diagram

```text
                    ┌─────────────────┐
  diagnose() ──────►│ AgentGraph.run  │
                    └────────┬────────┘
                             ▼
              ┌──────────────────────────────┐
              │ node_plan                     │
              │  birdseye → retrieve skills    │
              │  → _llm_json(planner)          │
              │  → ORCH-01 驳回首轮 stop       │
              │  → ORCH-10 零分注入 GENERIC    │
              │  → ORCH-07 探针 args 去重      │
              └──────────────┬───────────────┘
                             ▼
              node_retrieve → node_compress
                             ▼
              ┌──────────────────────────────┐
              │ node_verify                   │
              │  ORCH-06 根因假设 claim       │
              │  ORCH-05 归一化 + partial     │
              └──────────────┬───────────────┘
                    decisive? / barren?
                             ▼
         ┌───────────────────┴───────────────────┐
         ▼                                       ▼
┌─────────────────────┐               ┌─────────────────────┐
│ node_report         │               │ unanswerable /      │
│ ORCH-08 引用比例    │               │ human_gate          │
│ ORCH-09 未解释错误  │◄──────────────│ ORCH-09 同样扫描    │
└─────────────────────┘               └─────────────────────┘
         │
         ▼
  EventBus + Metrics + eval/process 聚合
  （premature_stop / parse_failure / truncation /
    verdict_supported / unexplained_error）
```

### Recommended Project Structure

```
src/vela/
├── agent/
│   ├── graph.py          # 守卫、_llm_json、verify/report/sweep（主战场）
│   ├── state.py          # excluded_skills + executed_probes
│   ├── skills.py         # fallback_only / 零分注入
│   └── citations.py      # 可复用计数；ORCH-08 阈值校验可放此或 graph
├── gateway/
│   ├── prompts.py        # ORCH-02 / verifier 契约
│   ├── base.py           # finish_reason==length → ALERT + metrics
│   └── ...
├── eval/
│   └── process.py        # 真实事件优先聚合
└── config/
    ├── llm.yaml          # max_tokens 2048
    ├── budget.yaml       # citation ratio 阈值
    └── skills/builtin.yaml  # SK-GENERIC-EVIDENCE-FIRST
tests/
├── test_agent.py         # 改写 excluded；新增 ORCH 单测簇
├── test_gateway.py       # truncation / parse 辅助
└── test_eval.py          # 过程指标真实事件口径
```

### Pattern 1: 程序化守卫 + 提示词双层防御
**What:** 提示词引导正确行为；代码强制不变量（首轮禁 stop、解析失败重试、覆盖哨兵）。  
**When to use:** 凡「模型听话就会出错」或「模型不听话会逃逸」的逻辑必然缺陷。  
**Example:** 见下方 Code Examples（`plan.stop_rejected`）。

### Pattern 2: 输出契约经网关闭合
**What:** `json_mode` + 上调 `max_tokens` + `finish_reason` 观测 + 显式重试；解析器信任整段 JSON，不跨段抠花括号。  
**When to use:** planner/verifier/distiller 所有 JSON 逻辑模型。

### Pattern 3: 配置驱动技能兜底
**What:** `fallback_only: true` 技能不进常规召回；候选全零分或守卫需要 actions 时注入。  
**When to use:** ORCH-10 与 ORCH-01 驳回后的强制下钻。

### Anti-Patterns to Avoid
- **跨段 `{`…`}` 提取：** 会把截断/多对象噪声「伪造成功」，掩盖 D5/D6。[VERIFIED: `graph.py::_parse_json`]
- **`api._q` 扫库：** 违反查询唯一收口；用 `search_logs`。[VERIFIED: `AGENTS.md`]
- **仅改提示词修 D1：** mock 不读正文，真实模型也可能违例。
- **继续 `used ∪ unproductive` 剔除：** 与 D3 复合锁死正确技能。[VERIFIED: explore-docs D4]
- **用 top1 涨跌验收本阶段：** ADR-4 禁止；只看过程指标 + 回归门。
- **在 `agent/nodes/` 建文件：** 空目录；节点必须是 `AgentGraph` 方法。[VERIFIED: `AGENTS.md`]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON 模式请求 | 手写 HTTP | 现有 `openai` SDK + `response_format` | Phase 1 已落地 [VERIFIED: `openai_compat.py`] |
| 未解释错误查询 | 新 ORM / 裸 SQL 模块 | `LogQueryAPI.call("search_logs", …)` | 护栏、审计、铁律 |
| 引用抽取 | 新解析器 | `citations.extract_citations` / `verify_citations` | 已有 CITE_RX |
| 技能向量召回 | 新 embedding 服务 | 现有 `embed_local` + 词面并集 | 本地优先；本阶段只加 fallback 分支 |
| 事件/指标 | `logging` | `EventBus` + `Metrics` | 项目纪律 |

**Key insight:** 本阶段的复杂度在**控制流语义**，不在新基础设施——复用 Phase 2 尺子与现有网关即可。

## Common Pitfalls

### Pitfall 1: 改剔除策略却忘了改单测与 mock 假设
**What goes wrong:** `test_excluded_skills_includes_used_and_unproductive` 断言 `used ∪ unproductive`；改完必红。mock 依赖 `excluded_skills` 跳过已用技能，若只改 state 不改探针去重，可能无意义重跑烧预算。  
**Why:** 旧策略在 mock 下是「优化」。  
**How to avoid:** 同步交付 ORCH-07 去重 + 改写单测为 unproductive-only；加「productive 技能可在不同 args 下复用」用例。  
**Warning signs:** mock eval 轮次暴涨或非法重选。

### Pitfall 2: `_llm` 丢弃 `LLMResponse`
**What goes wrong:** 截断告警与「优先信任 json_mode 结果」无法实现——当前只返回 `resp.text`。[VERIFIED: `graph.py:124-128`]  
**How to avoid:** 内部改用完整 response；截断在 gateway.chat 统一 emit，避免每个节点分叉。

### Pitfall 3: 过程指标代理口径与真实事件不一致
**What goes wrong:** Phase 2 的 `llm_parse_failure_rate` 用「skill=None ∧ ¬stop ∧ ¬actions」代理，基线 0.7 可能混入「合法空 actions」；修好解析后若不算真实事件，验收失真。[VERIFIED: `eval/process.py` + 02-RESEARCH Open Q3]  
**How to avoid:** emit `llm.parse_failure` / `llm.truncation`；聚合优先真实事件；更新脚注去掉「Phase 3 前允许偏高」。

### Pitfall 4: `insufficient_*` 污染评测标签空间
**What goes wrong:** 把覆盖不足标成 `no_fault_found` 的反面修复后，若 `predicted_label=insufficient_coverage` 被算进 misdiagnosis，消融指标抖动。  
**How to avoid:** 明确 label/status 语义；聚合时对 `insufficient_*` 单独计数（诚实降级 ≠ 误诊）。

### Pitfall 5: 健康场景被 GENERIC 拖入无意义下钻
**What goes wrong:** 全零分注入对健康包也可能触发。  
**How to avoid:** 注入条件收紧为「全零分 **且**（存在错误级信号或 level 分布含 ERROR）」；健康包应走 birdseye 后无错误 → 允许后续 stop / no_fault_found（L0 通过）。[ASSUMED: 精确谓词由 planner 钉进单测表]

### Pitfall 6: config_hash / 缓存失效
**What goes wrong:** 改 `llm.yaml`/`prompts.py`/`builtin.yaml` 后旧 LLM 磁盘缓存仍命中旧行为。  
**How to avoid:** Phase 2 缓存键含 params+prompt_sha；提示词变更自然失效。验收真实指标时用 `--no-cache` 对照基线目录方法论。

### Pitfall 7: 回归门假绿
**What goes wrong:** 只跑 `test-fast` 宣称完成。  
**How to avoid:** 涉及 graph/query/推理 → `make test`；仿真回归数 = 0 一票否决。

## Code Examples

### ORCH-01 首轮 stop 守卫
```python
# Source: explore-docs/VELA-真实LLM准确率归因分析与优化方案.md §4.2(2)（适配本仓库 EventBus API）
if out.get("stop") and st.round_no == 1:
    self.bus.emit("plan.stop_rejected", Severity.ALERT, st.round_no,
                  reason="首轮不允许 stop", model_reason=out.get("reason"))
    self.metrics.inc("plan.stop_rejected")
    out["stop"] = False
    if not (out.get("actions") or []):
        sid = out.get("selected_skill") or _pick_fallback(cands)
        out["actions"] = self.skills.probes_of(sid) or self.skills.probes_of(
            "SK-GENERIC-EVIDENCE-FIRST")
```

### ORCH-03 解析（禁止跨段花括号）
```python
# 推荐替换当前 graph._parse_json [VERIFIED: 现状见 graph.py:51-65]
def _parse_json(text: str) -> dict:
    t = (text or "").strip()
    m = _JSON_FENCE.search(t)
    if m:
        t = m.group(1).strip()
    try:
        val = json.loads(t)
        return val if isinstance(val, dict) else {}
    except json.JSONDecodeError:
        return {}  # 不找第一个 { 与最后一个 }
```

### ORCH-05 判据归一化
```python
# Source: explore-docs §4.2(4)
_OK = {"supported", "partial", "partially_supported", "supported_with_caveats"}
def _norm_status(s: str) -> str:
    return str(s or "").strip().lower().replace("-", "_").replace(" ", "_")

supported = [v for v in verdicts if _norm_status(v.get("status")) == "supported"]
partial = [v for v in verdicts if _norm_status(v.get("status")) in _OK
           and _norm_status(v.get("status")) != "supported"]
decisive = ((bool(supported) or len(partial) >= 2)
            and has_error_evidence and skill_id is not None
            and self.skills.label_of(skill_id) is not None)
```

### ORCH-07 剔除回归
```python
# Source: explore-docs §4.2(5)；替换 state.excluded_skills
def excluded_skills(self) -> list[str]:
    return sorted(set(self.unproductive_skills))
```

### ORCH-09 扫描（经门面，非 _q）
```python
# 推荐：对齐 runner 代理口径，遵守 LogQueryAPI 铁律
def _unexplained_error_sweep(self, st: SessionState) -> dict:
    res = self.api.call("search_logs", query="", mode="substring",
                        min_level="ERROR", limit=200)
    if not res.ok:
        return {"clean": True, "unexplained": 0, "error": res.error}
    err_hashes = {r.get("row_hash") for r in res.rows if r.get("row_hash")}
    if not err_hashes:
        return {"clean": True, "unexplained": 0, "total_errors": 0}
    seen = {r.get("row_hash") for r in st.evidence_pool if r.get("row_hash")}
    unexplained = [r for r in res.rows if r.get("row_hash") not in seen]
    return {"clean": not unexplained, "total_errors": len(err_hashes),
            "unexplained": len(unexplained), "samples": unexplained[:10]}
```

## Current Code Locations（ORCH 缺陷地图）

| ORCH | 缺陷现状 | 主文件:符号 | 备注 |
|------|----------|-------------|------|
| 01 | 无首轮 stop 驳回；无 `plan.stop_rejected` | `graph.py::node_plan` ~152-168；`run` ~329 | 基线 premature=0 仍须守卫 |
| 02 | 规则 5：「证据不足时 stop=true」 | `prompts.py::PLANNER_SYSTEM` L36 | 与调查/定论混淆 |
| 03 | 失败→`{}`；跨段 `{}`；无重试/事件 | `graph.py::_parse_json`；`_llm` 只返 text | 基线 parse_fail≈0.63 |
| 04 | planner 1024 / verifier 768；无 truncation ALERT | `config/llm.yaml` L9-10；`base.py::chat` 记 finish_reason 但无告警 | 基线 trunc≈0.25 |
| 05 | `status == "supported"` 精确匹配；无 partial | `graph.py::node_verify` L237-239 | 基线 supported_ratio≈0.37 |
| 06 | claim=raw_line，citation=同行 | `graph.py::node_verify` L218-220 | 循环论证 |
| 07 | `used ∪ unproductive` | `state.py::excluded_skills` L65-73；测试 L57-61 | 须改测 |
| 08 | 仅 dangling strip，无比例重试/降级 | `graph.py::node_report` L251-258 | METR-01 闸门已在评测侧 |
| 09 | `_root_cause` 只看 chain 内 has_error；无全局哨兵 | `graph.py::_root_cause` L487-498；runner 仅事后算指标 | 基线 unexplained≈0.63 |
| 10 | 无 GENERIC 技能；retrieve 无 fallback_only | `skills.py::retrieve`；`builtin.yaml` | mock 全零分直接 stop |

## Recommended Implementation Approach（按 ORCH）

| ID | Approach | Touch list |
|----|----------|------------|
| ORCH-04 | yaml 上调 tokens；`LLMGateway.chat` 成功路径若 `finish_reason=="length"` → `bus` 需注入或 metrics 回调；graph 侧保证 ledger round 上下文 | `config/llm.yaml`, `gateway/base.py`, 或 `graph._llm` 包装 |
| ORCH-03 | `_parse_json` 去跨段；`_llm_json` retries=2 + `llm.parse_failure` ALERT；节点改用 `_llm_json` | `graph.py`, `eval/process.py`, `tests/test_agent.py` |
| ORCH-01+02 | 重写规则 5；`node_plan` 首轮驳回 stop 并补 actions | `prompts.py`, `graph.py` |
| ORCH-05+06 | claims=假设；VERIFIER 枚举含 partial；归一化 decisive | `graph.py`, `prompts.py`, mock `_verify` 兼容 partial |
| ORCH-07 | `excluded_skills`→unproductive-only；`executed_probes` 去重过滤 actions | `state.py`, `graph.py`, `tests/test_agent.py` |
| ORCH-10 | YAML 技能 + retrieve 排除 fallback_only + 零分/守卫注入 API | `builtin.yaml`, `skills.py`, `graph.py` |
| ORCH-08 | report 后 `len(cites) >= ceil(0.5*len(chain))`（或 valid 引用）；不足则修复提示重试 1 次；再不足 `status=insufficient_citation` | `graph.py`, `budget.yaml`, `citations.py`（可选 helper） |
| ORCH-09 | report/unanswerable 前 sweep；拦 `no_fault_found`；emit `coverage.unexplained_errors`；写入 case 指标供聚合 | `graph.py`, `eval/runner.py`（可选对齐）, `eval/process.py` |
| 验收 | 真实 LLM 过程指标对照基线；mock 回归门 | `make test`, `make eval`, 可选 `pytest -m realllm` |

**建议波次（供 planner）：**
1. Wave 0：单测骨架（parse / exclude / status norm / fallback retrieve）
2. Wave 1：ORCH-03+04（输出契约）— 解锁真实 parse/trunc 指标
3. Wave 2：ORCH-01+02+07+10（plan 路径止血）
4. Wave 3：ORCH-05+06（verify 路径）
5. Wave 4：ORCH-08+09（落地闸门）+ 过程指标口径升级 + 回归门

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| 无过程指标 | 7 项过程指标 + 决策轨迹（代理口径） | Phase 2 METR-05 | 本阶段可验收 |
| 接受 44.4% 单点 | 方差基线 top1 mean≈0.52±0.13 等 | Phase 2 METR-09 | 对比锚已变 |
| used∪unproductive 剔除 | → unproductive-only + 探针去重 | Phase 3（本阶段） | 解锁多轮深挖 |
| claim=日志原文 | → 根因假设 | Phase 3 | 消除自证循环 |

**Deprecated/outdated:**
- 用跨段花括号「抢救」截断 JSON
- 将 `premature_stop_rate` 代理与 `plan.stop_rejected` 混为一谈（前者是发生率，后者是守卫计数）
- 探索文档里的 `api._q` 示例（与现行铁律冲突）

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 健康包零分注入须额外要求「存在 ERROR 信号」 | Pitfall 5 | 健康特异性下降；须单测钉死 |
| A2 | decisive 采用「≥2 partial」阈值 | Discretion / ORCH-05 | 过宽假阳性 / 过严不收敛 |
| A3 | ORCH-08 计数用「引用次数 vs 链长」而非 citation_coverage 句子比 | ORCH-08 | 与 METR-01 口径并行列报，勿混用 |
| A4 | `insufficient_*` 不计入 misdiagnosis 分子 | Pitfall 4 | 消融报表被误解为退化 |
| A5 | gateway 截断 ALERT 可通过 Metrics 而不强制给 Gateway 挂 EventBus | ORCH-04 | 若只能在 graph 包装层做，计划须写清 |

**非空：** A1–A2 建议 planner 写入单测表即锁定，无需再开 discuss。

## Open Questions

1. **`insufficient_citation` / `insufficient_coverage` 是 `status` 还是 `root_cause.label`？**
   - What we know: REQUIREMENTS 写「降级为 … 状态」；现有 status 枚举在 `state.py` 注释中。
   - What's unclear: eval 的 `answered` 判定与 top1 是否包含这些终态。
   - Recommendation: `status` ∈ 新值；`root_cause.label` 同步为同名或保留证据标题；runner 视作非 answered 诚实终态。

2. **首轮守卫驳回后无 selected_skill 时选谁？**
   - What we know: 探索文档用 `_fallback_skill(cands)` 或 GENERIC。
   - Recommendation: 优先候选最高分非 fallback 技能；若无候选或全零分 → `SK-GENERIC-EVIDENCE-FIRST`（与 ORCH-10 合流）。

3. **真实 LLM 验收是否强制本阶段跑满 `--no-cache` N 次？**
   - What we know: ADR-4 说过程指标无需统计前置；回归门是 mock 177+仿真。
   - Recommendation: mock 单测 + 全量测试为合并门；另设可选 realllm 过程指标抽检对照 baseline，不阻断（除非 premature/parse/trunc 在抽检中仍远超标）。

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python `.venv` | 全部 | ✓ | 3.12.13 | `make install-dev` |
| 现有主依赖 | 编排/评测 | ✓ | pyproject | — |
| pytest | 回归 | ✓ | dev | — |
| `data/dataset` | eval 回归门 | 视本地 | — | `make sim` |
| volcengine `.env` | 可选真实过程指标抽检 | ✓（Phase 1） | — | 仅 mock 门也可合入逻辑修复 |
| 新系统包 / Docker | — | N/A | — | 不需要 |
| graphify | 研究增强 | ✗ 无 `graphs/` | — | 未用 |

**Missing dependencies with no fallback:** 无  

**Missing dependencies with fallback:** 真实 LLM 抽检无凭证时跳过，不阻逻辑合入。

Step 2.6: 已审计 — 纯代码/配置阶段，无新外部服务。

## Validation Architecture

> `workflow.nyquist_validation` 未在 `.planning/config.json` 设为 `false` → **启用**。

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
| ORCH-01 | round_no==1 时 stop 被驳回并 inc/emit `plan.stop_rejected` | unit | `pytest tests/test_agent.py -k stop_rejected -q` | ❌ Wave 0 |
| ORCH-02 | `PLANNER_SYSTEM` 含「禁止因尚无证据而 stop」类约束（契约快照或子串） | unit | `pytest tests/test_gateway.py -k planner_system -q` | ❌ Wave 0 |
| ORCH-03 | 非法 JSON 重试 2 次后仍失败→ALERT；合法围栏 JSON 成功；跨段提取不再「假成功」 | unit | `pytest tests/test_agent.py -k parse_json -q` | ❌ Wave 0 |
| ORCH-04 | llm.yaml planner/verifier max_tokens==2048；finish_reason=length 计 truncation | unit | `pytest tests/test_gateway.py -k 'max_tokens or truncation' -q` | ❌ Wave 0 |
| ORCH-05 | `Supported`/`partial`/`partially_supported` 可推进；仅 unsupported 不 decisive | unit | `pytest tests/test_agent.py -k verdict_norm -q` | ❌ Wave 0 |
| ORCH-06 | claims[0].claim 含根因假设而非 raw_line 自身循环 | unit | `pytest tests/test_agent.py -k verify_claim_hypothesis -q` | ❌ Wave 0 |
| ORCH-07 | excluded==unproductive only；同 skill 不同 args 可再跑；同 args 被去重 | unit | `pytest tests/test_agent.py -k 'excluded_skills or probe_dedup' -q` | ⚠️ 旧测须改写 |
| ORCH-08 | 引用不足→重试；仍不足→`insufficient_citation` | unit | `pytest tests/test_agent.py -k insufficient_citation -q` | ❌ Wave 0 |
| ORCH-09 | pool 无错误但库有 ERROR → 禁 no_fault_found，→ insufficient_coverage | unit/int | `pytest tests/test_agent.py -k unexplained_sweep -q` | ❌ Wave 0 |
| ORCH-10 | fallback_only 不出现在常规 retrieve；全零分时注入 GENERIC | unit | `pytest tests/test_agent.py -k generic_fallback -q` | ❌ Wave 0 |
| 过程指标 | 真实事件优先；目标阈值达标（集成/eval） | unit + eval | `pytest tests/test_eval.py -k process_metric -q` | ✅ 部分存在 |
| 回归门 | 177+ 全绿；仿真回归 0 | suite | `make test` + `make eval`（mock） | ✅ |

### Sampling Rate
- **Per task commit:** `make test-fast` + 相关 `-k` 单测
- **Per wave merge:** `make test`
- **Phase gate:** `make test` 绿 + mock `make eval` 回归数 0；过程指标对照 ROADMAP 成功标准（真实 LLM 抽检可选）
- **Max feedback latency:** fast ≤120s

### Wave 0 Gaps
- [ ] `tests/test_agent.py` — stop_rejected / parse_json / verdict_norm / claim_hypothesis / excluded 改写 / probe_dedup / citation_ratio / unexplained_sweep / generic_fallback
- [ ] `tests/test_gateway.py` — max_tokens 配置断言 / truncation 计数（若逻辑在 gateway）
- [ ] `tests/test_eval.py` — 过程指标改为消费 `llm.parse_failure` 等真实事件
- [ ] （可选）最小 fixture DB：含 ERROR 行但 evidence_pool 为空，供 ORCH-09

*(现有基础设施可跑；ORCH 专用用例大多缺失 → Wave 0 必做)*

### Success Criteria → Metrics Proof

| Success Criterion | Metric / Proof | How measured |
|-------------------|----------------|--------------|
| 1 首轮误停 | `premature_stop_rate ≤ 0.05`；存在 `plan.stop_rejected` | eval process + 单测守卫 |
| 2 解析/截断 | `llm_parse_failure_rate ≤ 0.02`；`llm_truncation_rate ≤ 0.02` | audit finish_reason + parse 事件 |
| 3 verifier | `verdict_supported_ratio ≥ 0.6` | verify.done supported/claims（归一化后） |
| 4 技能不误剔 | 专门单测：round1 选中且 productive 的技能 ∉ round2 excluded | unit（逻辑必然，不依赖 LLM） |
| 5 覆盖/兜底 | `unexplained_error_rate ≤ 0.05`；零分注入单测 | sweep + retrieve 单测；eval 聚合 |

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|------------------|
| V2 Authentication | no | — |
| V3 Session Management | no | — |
| V4 Access Control | no | 本地单租户 POC |
| V5 Input Validation | yes | JSON schema 工具参数；`_parse_json` 拒绝半截对象；日志原文本阶段不新开注入面（DECP-05 属 Phase 4） |
| V6 Cryptography | no | 不新手写密码学；沿用 blake2 指纹 |

### Known Threat Patterns for Agent+LLM stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| 模型输出驱动控制流逃逸（伪 stop / 伪 JSON） | Tampering | 程序化守卫 + 重试 + 指标 |
| 提示词诱导过早停机 | Elevation of Privilege（控制流） | ORCH-02 重写 + ORCH-01 硬拦 |
| 报告零引用伪装完成 | Spoofing | ORCH-08 + METR-01 |
| 未解释错误被报 no_fault_found | Repudiation / 错误结论 | ORCH-09 SQL 不变量 |
| 出站敏感数据 | Information Disclosure | 现有 `gateway/redact.py`（本阶段不削弱） |

## Project Constraints (from .cursor/rules/ + AGENTS.md)

- 无项目级 `.cursor/rules/`；约束以 `AGENTS.md` / `CLAUDE.md` 为准。[VERIFIED: glob]
- 查询唯一收口 `LogQueryAPI.call()`；禁止业务直连 DuckDB。
- 配置驱动；`load_yaml` 有 `lru_cache`，改配置须重启进程。
- Provider 可插拔；业务不写供应商专属逻辑。
- 程序化校验优先于模型自述。
- 图节点 = `AgentGraph` 方法；不在 `agent/nodes/` 建文件。
- 单线程同步；DuckDB `read_only=True`。
- 不用 `logging`；用 EventBus + `print`（CLI）。
- 不提交 `.env` / API key；出站经 redact；本地优先。
- 完成判据：`make test-fast`；涉及推理链路 → `make test`；行为变化同步 config/文档。

## Sources

### Primary (HIGH confidence)
- [VERIFIED: codebase] `src/vela/agent/graph.py`, `state.py`, `skills.py`, `citations.py`
- [VERIFIED: codebase] `src/vela/gateway/{prompts,base,mock,openai_compat}.py`, `config/llm.yaml`, `config/skills/builtin.yaml`
- [VERIFIED: codebase] `src/vela/eval/{process,runner,report}.py`
- [VERIFIED: baseline] `.planning/phases/02-metrics-baseline/baseline/eval_report.md`
- [CITED: explore-docs] `VELA-真实LLM准确率归因分析与优化方案.md` D1–D6 / §4.2
- [CITED: explore-docs] `VELA-技能知识库深度分析报告.md` §3.3 L0/L1
- [CITED: explore-docs] `VELA-多专家联合评审与系统性优化改造方案.md` C-03..C-10, C-22, C-23
- [VERIFIED: project] `.planning/REQUIREMENTS.md` ORCH-*；`.planning/ROADMAP.md` Phase 3；`AGENTS.md`

### Secondary (MEDIUM confidence)
- [CITED: explore-docs] 双驱动文档阶段划分（确认 ORCH 边界不含 DUAL）
- Phase 2 `02-RESEARCH.md` 过程指标代理口径决议

### Tertiary (LOW confidence)
- A1 健康包注入谓词细节（待单测钉死）
- 真实 LLM 抽检是否纳入 phase gate（Open Q3）

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — 无新依赖，版本已核
- Architecture: HIGH — 缺陷位点与修复钉法均有代码+探索文档双重来源
- Pitfalls: HIGH — 基线数字与既有失败测试点已核实；A1/A2 为策略灰度

**Research date:** 2026-08-01  
**Valid until:** 2026-08-31（编排语义稳定；若 Phase 4 改 payload 需重核 ORCH-01 交互）
