# Phase 3: 编排层逻辑止血 - Pattern Map

**Mapped:** 2026-08-01
**Files analyzed:** 15
**Analogs found:** 15 / 15

> 本阶段几乎全是**既有文件上的语义止血**，无新基础设施模块。多数「Closest Analog」= 文件自身既有模式（extend-in-place）；跨文件复用点写在 Shared Patterns。

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/vela/agent/graph.py` | service（编排器） | request-response + transform | 自身：`plan.illegal_skill` 守卫 / `_llm` / `node_*` | exact |
| `src/vela/agent/state.py` | model | transform | 自身：`excluded_skills` + `to_dict`/`from_dict` | exact |
| `src/vela/agent/skills.py` | service | transform | 自身：`retrieve` 过滤 pool + `compact` | exact |
| `src/vela/agent/citations.py` | utility | transform | 自身：`extract_citations` / `verify_citations` | exact |
| `src/vela/gateway/prompts.py` | config / utility | request-response | 自身：`PLANNER_SYSTEM` / `VERIFIER_SYSTEM` | exact |
| `src/vela/gateway/base.py` | middleware / provider | request-response | 自身：`LLMGateway.chat` 成功路径 + `finish_reason` | exact |
| `src/vela/gateway/mock.py` | provider | request-response | 自身：`_verify` status 枚举 | exact |
| `src/vela/eval/process.py` | utility | batch / transform | 自身：`aggregate_process_metrics` 代理口径 | exact |
| `src/vela/eval/runner.py` | service | batch | 自身：`search_logs` 未解释错误代理 | exact |
| `config/llm.yaml` | config | — | 自身：`logical_models.*.max_tokens` | exact |
| `config/budget.yaml` | config | — | 自身：`cost.*` / `profiles.*.budget` 键风格 | role-match |
| `config/skills/builtin.yaml` | config | — | 自身：现有 skill 条目（如 `SK-PHASE-OVERVIEW`） | exact |
| `tests/test_agent.py` | test | — | 自身：`test_excluded_skills_*` / e2e diagnose | exact |
| `tests/test_gateway.py` | test | — | 自身：mock planner/verifier + finish_reason | exact |
| `tests/test_eval.py` | test | — | 自身：`test_process_metrics_keys_and_trace` | exact |

## Pattern Assignments

### `src/vela/agent/graph.py`（service, request-response + transform）

**Analog:** 自身 — 程序化守卫、`_llm`/`_parse_json`、节点方法、EventBus/Metrics

**Imports pattern** (lines 15-39):
```python
from __future__ import annotations

import json
import re
# ...
from vela.agent.citations import strip_dangling, verify_citations
from vela.agent.skills import SkillRegistry
from vela.agent.state import RoundRecord, SessionState
from vela.config import load_budget, load_yaml
from vela.gateway import LLMRequest, build_gateway
from vela.gateway.prompts import (DISTILLER_SYSTEM, PLANNER_SYSTEM, REPORTER_SYSTEM,
                                  VERIFIER_SYSTEM, distiller_user, planner_user,
                                  reporter_user, verifier_user)
from vela.obs.events import EventBus, Severity
from vela.obs.metrics import Metrics
from vela.query.api import LogQueryAPI
```

**Guard pattern — 非法技能驳回（ORCH-01 应镜像此结构）** (lines 154-160):
```python
if sid and sid in set(st.excluded_skills()):
    self.bus.emit("plan.illegal_skill", Severity.ALERT, st.round_no, skill=sid)
    self.metrics.inc("plan.illegal_skill")
    out["stop"] = True
    out["reason"] = f"模型选择了已被程序剔除的技能 {sid}（历史规避约束）"
    sid = None
```
ORCH-01 落地时：同结构 emit `plan.stop_rejected` + `metrics.inc`，但语义相反——驳回 `stop`、必要时补 `actions`（见 RESEARCH Code Examples）。

**LLM 调用现状（ORCH-03/04 升级点）** (lines 124-128, 152):
```python
def _llm(self, logical: str, system: str, user: str) -> str:
    with self.metrics.timer(f"llm.{logical}"):
        resp = self.gw.chat(LLMRequest(logical_model=logical, system=system, user=user))
    self.metrics.inc(f"llm.{logical}.calls")
    return resp.text

out = _parse_json(self._llm("planner", PLANNER_SYSTEM, planner_user(payload)))
```
Planner 应改为 `_llm_json(...)`；保留完整 `LLMResponse` 以便截断告警。

**Anti-pattern to remove — 跨段花括号** (lines 51-65):
```python
def _parse_json(text: str) -> dict:
    # ...
    except json.JSONDecodeError:
        i, j = t.find("{"), t.rfind("}")
        if i >= 0 and j > i:
            try:
                return json.loads(t[i:j + 1])
            except json.JSONDecodeError:
                pass
    return {}
```
ORCH-03：围栏剥离后只做整段 `json.loads`；失败返回 `{}`，由 `_llm_json` 重试并发 `llm.parse_failure`。

**Verify decisive（ORCH-05/06 改造点）** (lines 218-239):
```python
claims = [{"claim_id": f"C{i+1}",
           "claim": str(r.get("raw_line") or r.get("preview") or "")[:200],
           "citations": [r.get("row_hash")]} for i, r in enumerate(ev) if r.get("row_hash")]
# ...
supported = [v for v in verdicts if v.get("status") == "supported"]
decisive = (bool(supported) and has_error_evidence and skill_id is not None
            and self.skills.label_of(skill_id) is not None)
```
改为根因假设 claim + `_norm_status` + `partial` 可推进。

**Report 引用校验（ORCH-08 扩展点）** (lines 251-266):
```python
text = self._llm("reporter", REPORTER_SYSTEM, reporter_user(payload))
rep = verify_citations(text, [c["row_hash"] for c in chain], api=self.api)
if rep.dangling:
    text = strip_dangling(text, rep.dangling)
    # ... emit report.dangling_citation ALERT
```
在此之后加：`len(cites) >= ceil(0.5 * len(chain))`（阈值来自 `budget.yaml`）；不足则修复提示重试 1 次 → `status=insufficient_citation`。

**no_fault_found 路径（ORCH-09 拦截点）** (lines 487-498):
```python
has_error = any(str(c.get("level_norm") or "").upper() in ("ERROR", "FATAL")
                for c in chain)
if not has_error:
    return {"label": "no_fault_found",
            "title": "未发现故障证据（本次升级日志无错误级事件）",
            ...}
```
落地前调用 `_unexplained_error_sweep`；库中有未入池 ERROR 时禁止该标签 → `insufficient_coverage`。

**主循环 stop 分支（ORCH-01/09 挂钩）** (lines 329-338):
```python
if plan["stop"] or not plan["actions"]:
    st.rounds.append(rec)
    self.ckpt.save(st)
    if st.evidence_pool:
        self.node_report(st, _last_productive_skill(st))
        st.status = "answered"
    else:
        self.node_unanswerable(...)
```
首轮守卫应在 `node_plan` 内完成，避免此处把假 stop 当终态。

**Query facade（ORCH-09 必须遵循）** — retrieve 已示范：
```python
res = self.api.call(tool, **args)  # 禁止 api._q 扫业务错误行
```

---

### `src/vela/agent/state.py`（model, transform）

**Analog:** 自身 `excluded_skills` + dataclass 字段扩展惯例

**Core pattern — 剔除策略（ORCH-07）** (lines 65-73):
```python
def excluded_skills(self) -> list[str]:
    """程序化历史规避：从候选集中物理剔除，而不是"提示模型别选"。"""
    return sorted(set(self.used_skills) | set(self.unproductive_skills))
```
替换为：`return sorted(set(self.unproductive_skills))`。

**Field extension pattern** (lines 40-51): 新增 `executed_probes: list[str] = field(default_factory=list)` 与 `status` 注释扩展（`insufficient_citation` / `insufficient_coverage`），保持 `to_dict`/`from_dict` 经 `asdict` 自动序列化（无需手写映射，除非加非 dataclass 字段）。

**Status enum comment** (line 36):
```python
status: str = "running"  # running | answered | human_gate | unanswerable | budget_exhausted
```
ORCH-08/09 扩展注释与赋值点（`node_report` / sweep 后）。

---

### `src/vela/agent/skills.py`（service, transform）

**Analog:** 自身 `retrieve` pool 过滤

**Core retrieve filter** (lines 65-75, 100):
```python
def retrieve(self, query: str, top_n: int = 8, exclude: list[str] | None = None) -> list[dict]:
    ex = set(exclude or [])
    pool = [s for s in self.skills if s["id"] not in ex]
    if not pool:
        return []
    # ... dense + lex 并集 ...
    return [compact(self.by_id[sid]) for sid in picked[:top_n]]
```
ORCH-10：在 `pool = [...]` 处额外排除 `s.get("fallback_only")`；另提供注入 API（如 `fallback_skill()` / graph 侧零分时 `probes_of("SK-GENERIC-EVIDENCE-FIRST")`）。

**blake2b 指纹惯例**（探针 `args_hash` 可复用） (lines 30-35):
```python
h = int.from_bytes(hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest(), "big")
```
结合 `vela.util.jsonl.canonical_json`（见 Shared Patterns）构造 `(skill_id, args_hash)`。

---

### `src/vela/agent/citations.py`（utility, transform）

**Analog:** 自身抽取/校验 API

**Count citations** (lines 72-83):
```python
def extract_citations(text: str) -> list[str]:
    out = list(dict.fromkeys(CITE_RX.findall(text or "")))
    # ... trailer JSON ...
    return out
```
ORCH-08 helper（可选）：`citation_count_vs_chain(text, chain_len, min_ratio)` —— 复用 `extract_citations` / `verify_citations`，**不要**新建解析器。计数口径 = 引用次数 vs 链长（A3），勿与 `citation_coverage`（事实句比）混用。

---

### `src/vela/gateway/prompts.py`（config/utility, request-response）

**Analog:** 自身系统提示词契约

**ORCH-02 改造点** (lines 30-39):
```python
PLANNER_SYSTEM = """...
5. 证据不足时输出 stop=true 并说明还缺什么，不允许编造。
只输出 JSON，格式：
{"thought": "...", "selected_skill": "...", "actions": [...],
 "stop": false, "reason": ""}"""
```
规则 5 重写：区分「停止调查」与「无法定论」；禁止因尚无证据而首轮 stop。

**ORCH-05/06 verifier 契约** (lines 41-43):
```python
VERIFIER_SYSTEM = """...
只输出 JSON：{"verdicts":[{"claim_id":"C1","status":"supported|weak|unsupported","citations":["row_hash"],"note":""}]}"""
```
枚举加入 `partial` / 变体说明；claim 语义改为根因假设（与 graph claims 构造对齐）。

**State embed** (lines 16-17) — 保持 `sort_keys=True`，mock 依赖此契约。

---

### `src/vela/gateway/base.py`（middleware, request-response）

**Analog:** 自身 `chat` 成功返回路径

**finish_reason 已贯通审计** (lines 145-146, 188-199):
```python
finish_reason=str(cached.get("finish_reason") or "stop"),
# ...
self.cache.put(key, response_text=resp.text, ..., finish_reason=resp.finish_reason)
rec = self.auditor.record(..., finish_reason=resp.finish_reason, cache_hit=False)
```
ORCH-04：在成功返回前（缓存命中与 live 完成两处）若 `resp.finish_reason == "length"`，触发 ALERT/metrics。Gateway **当前无 EventBus**——优先在 `graph._llm`/`_llm_json` 包装层 `self.bus.emit("llm.truncation", Severity.ALERT, ...)` + `self.metrics.inc("llm.truncation")`（RESEARCH A5）；若注入回调再考虑挂 bus。

**LLMResponse 已含字段** (lines 46-58) — graph 必须停止只取 `.text`。

---

### `src/vela/gateway/mock.py`（provider, request-response）

**Analog:** 自身 `_verify`

**Status assignment** (lines 121-135):
```python
def _verify(self, state: dict) -> str:
    # ...
    status = "supported" if ok and not bad else ("weak" if ok else "unsupported")
    verdicts.append({"claim_id": c.get("claim_id"), "status": status, ...})
```
ORCH-05：mock 需兼容 `partial`（例如弱支撑可标 `partial`），否则真实归一化路径与 mock 评测分叉。`blake2b` 假哈希 (lines 20-21) 是 `args_hash` 长度/风格参考。

---

### `src/vela/eval/process.py`（utility, batch）

**Analog:** 自身代理聚合

**Proxy parse/trunc/premature** (lines 85-103):
```python
# premature：首轮 stop=True
if first and _payload(first).get("stop"):
    premature += 1
# parse failure 代理：skill is None ∧ ¬stop ∧ ¬actions
# truncation：audit finish_reason==length
```
ORCH 验收升级：优先计真实事件 `llm.parse_failure` / `llm.truncation` / `plan.stop_rejected`；代理降为 fallback；更新 `PROXY_FOOTNOTE`（去掉「Phase 3 前允许偏高」）。

**Ablation / insufficient_*** (lines 144-161): `answered`/`mis` 判定需排除 `insufficient_citation` / `insufficient_coverage`，避免污染健康特异性与 misdiagnosis。

---

### `src/vela/eval/runner.py`（service, batch）

**Analog:** 自身未解释错误代理（ORCH-09 graph sweep **必须抄此门面调用，禁止 `_q`**）

**Exact pattern** (lines 248-255):
```python
err_rows = g.api.call("search_logs", query="", min_level="ERROR", limit=200).rows
err_hashes = {r.get("row_hash") for r in err_rows if r.get("row_hash")}
if err_hashes:
    unseen = err_hashes - set(res.state.seen_row_hashes)
    unexplained = round(len(unseen) / len(err_hashes), 4)
```
Graph 侧 sweep 对齐：差集对 `evidence_pool` 的 `row_hash`（RESEARCH 推荐）；runner 可后续改为消费 session 事件/字段，但本阶段可选。

---

### `config/llm.yaml`（config）

**Analog:** 自身 logical_models 块 (lines 8-12):
```yaml
logical_models:
  planner:   {temperature: 0.1, max_tokens: 1024, json_mode: true}
  verifier:  {temperature: 0.0, max_tokens: 768,  json_mode: true}
  reporter:  {temperature: 0.2, max_tokens: 2048, json_mode: false}
  distiller: {temperature: 0.3, max_tokens: 1536, json_mode: true}
```
ORCH-04：仅 `planner`/`verifier` → `2048`；reporter 保持 2048（不顺带 4096）。注意 `load_yaml` 有 `lru_cache`——改后须重启进程。

---

### `config/budget.yaml`（config）

**Analog:** 文件尾部 `cost:` 块风格 (lines 56-60) — 顶层命名空间键

**Pattern to copy:**
```yaml
cost:
  input_per_1k: 0.0
  diagnose_cost_alert: 1.0
```
ORCH-08 新增类似：
```yaml
report:
  min_citation_ratio: 0.5   # NR-4 先宽后紧
```
经 `load_budget` / `load_yaml("budget.yaml")` 读取；**禁止**在 graph 硬编码 `0.5`。

---

### `config/skills/builtin.yaml`（config）

**Analog:** `SK-PHASE-OVERVIEW` 条目结构 (lines 8-20)

**Skill entry shape:**
```yaml
- id: SK-PHASE-OVERVIEW
  version: 3
  title: ...
  trigger: ...
  summary: ...
  tags: [...]
  root_cause_label: null
  tools: [...]
  probes:
    - {tool: ..., args: {...}}
  keywords: [...]
```
ORCH-10：新增 `SK-GENERIC-EVIDENCE-FIRST`，`fallback_only: true`，空/宽关键词，`root_cause_label: null`，probes 走通用 `search_logs`/`top_templates` 取证。现有加载器 `load_skills()` 会吞未知键——确认 `fallback_only` 保留在 dict 上供 `skills.retrieve` 过滤。

**注意：** `test_skill_registry_loads_all_12` 硬编码 `len == 12` → 增技能后改断言为 13。

---

### `tests/test_agent.py`（test）

**Analog:** 自身单元 + e2e

**Must rewrite** (lines 57-61):
```python
def test_excluded_skills_includes_used_and_unproductive():
    st = SessionState(session_id="s1", db_path="x")
    st.used_skills = ["SK-A"]
    st.unproductive_skills = ["SK-B"]
    assert st.excluded_skills() == ["SK-A", "SK-B"]
```
→ 断言仅 `["SK-B"]`；另加 productive 技能不同 args 可复用 / 同 args 去重。

**E2E 风格** (lines 208+): `AgentGraph(...).run()` + 断言 `metrics`/`status`/`root_cause`——ORCH 守卫单测优先直接调 `node_plan`/`_parse_json`/`_norm_status`，因 mock 不读提示词正文。

**Skill count** (lines 20-23): 随 GENERIC 技能更新。

---

### `tests/test_gateway.py`（test）

**Analog:** mock 契约测试 (lines 80-124) + finish_reason 断言 (~288)

**Patterns:**
- 用 `build_gateway("mock")` + `LLMRequest(logical_model=...)` 驱动
- 配置断言：`load_yaml("llm.yaml")["logical_models"]["planner"]["max_tokens"] == 2048`
- ORCH-02：子串断言 `PLANNER_SYSTEM` 含调查/定论区分
- truncation：构造/注入 `finish_reason="length"` 的响应路径，断言 metrics/事件（若逻辑在 graph 包装层则测 graph）

---

### `tests/test_eval.py`（test）

**Analog:** `test_process_metrics_keys_and_trace` (lines 209-233)

**Fixture shape:**
```python
cases = [{
    "case_id": "C1",
    "events": [
        {"kind": "plan.done", "round_no": 1, "payload": {...}},
        {"kind": "verify.done", "round_no": 1, "payload": {"supported": 1, "claims": 2}},
    ],
    "rounds": [...],
    "audit": [{"finish_reason": "stop"}, {"finish_reason": "length"}],
    "unexplained_error_rate": 0.25,
}]
```
升级后：增加含 `llm.parse_failure` / `llm.truncation` 事件的用例，断言真实事件优先于代理；脚注文案同步。

## Shared Patterns

### EventBus ALERT + Metrics.inc
**Source:** `src/vela/agent/graph.py` (plan.illegal_skill), `src/vela/obs/events.py` emit
**Apply to:** ORCH-01 stop_rejected、ORCH-03 parse_failure、ORCH-04 truncation、ORCH-08/09 降级
```python
self.bus.emit("plan.illegal_skill", Severity.ALERT, st.round_no, skill=sid)
self.metrics.inc("plan.illegal_skill")
```
```python
# events.py
def emit(self, kind: str, severity: Severity = Severity.PROGRESS,
         round_no: int = 0, **payload) -> Event:
```
禁止 `logging` 模块。

### LogQueryAPI 唯一收口
**Source:** `src/vela/eval/runner.py` 249-251；`graph.node_retrieve`
**Apply to:** ORCH-09 `_unexplained_error_sweep`
```python
res = self.api.call("search_logs", query="", mode="substring",
                    min_level="ERROR", limit=200)
```
禁止 `api._q` / 裸 SQL。

### args_hash = blake2b(canonical_json)
**Source:** `src/vela/util/jsonl.py` `canonical_json`；`gateway/mock.py` `_fake_hash`
**Apply to:** ORCH-07 `executed_probes` 键
```python
from vela.util.jsonl import canonical_json
import hashlib

def args_hash(args: dict) -> str:
    return hashlib.blake2b(
        canonical_json(args or {}).encode("utf-8"), digest_size=8
    ).hexdigest()
# probe key: f"{skill_id}:{args_hash(args)}"
```

### 程序化校验优先于模型自述
**Source:** `graph.node_verify` dangling 独立校验；`citations.verify_citations`
**Apply to:** ORCH-01/03/08/09 全部守卫——提示词只引导，不变量在代码强制。

### 图节点即方法
**Source:** `AGENTS.md` 铁律 5；`AgentGraph.node_*`
**Apply to:** 全部新控制流——在 `graph.py` 加方法（如 `_llm_json`、`_unexplained_error_sweep`），**禁止**在 `agent/nodes/` 建文件。

### 配置驱动阈值
**Source:** `load_budget` / `load_yaml("llm.yaml")`；`budget.yaml` `cost:` 风格
**Apply to:** `max_tokens`、`min_citation_ratio`、`fallback_only` 技能——业务代码只读配置。

### LLM 磁盘缓存失效
**Source:** `gateway/cache.py` 键含 `prompt_sha256` + params
**Apply to:** 改 `prompts.py` / `llm.yaml` 后自然失效；真实验收用 `--no-cache`。

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| — | — | — | 本阶段无全新模块；`insufficient_*` 状态值为新枚举成员，模式仍对齐现有 `st.status = "unanswerable"` |

可选 helper（若拆出）无独立新文件必要——优先落在 `graph.py` / `citations.py`。

## Metadata

**Analog search scope:** `src/vela/agent/`, `src/vela/gateway/`, `src/vela/eval/`, `src/vela/obs/`, `src/vela/util/`, `config/`, `tests/`
**Files scanned:** ~25（核心 touch list + 共享工具）
**Strong analogs used:** 5 簇 — (1) graph 守卫/节点 (2) state/skills 剔除检索 (3) gateway chat/prompts/mock (4) eval process/runner 指标与 search_logs (5) tests 既有断言风格
**Pattern extraction date:** 2026-08-01
