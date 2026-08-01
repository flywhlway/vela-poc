---
phase: 03-orch-logic-hemostasis
verified: 2026-08-01T06:24:57Z
status: passed
score: 7/7 must-haves verified
overrides_applied: 0
gaps: []
deferred: []
---

# Phase 3: 编排层逻辑止血 Verification Report

**Phase Goal:** 消除编排层的逻辑必然缺陷——首轮误停、JSON 解析静默失败、输出截断、verifier 判据脆弱匹配与循环论证、技能被误剔除、未解释错误被忽视、候选集全零分空手停止。
**Verified:** 2026-08-01T06:24:57Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | ------- | ---------- | -------------- |
| 1 | `premature_stop_rate` 可观测：`round_no==1` 禁止 stop，emit `plan.stop_rejected`；PLANNER 规则 5 区分「停止调查」与「无法定论」 | ✓ VERIFIED | `graph.py` L223–239 守卫 + metrics；`prompts.py` L36–38；`test_plan_stop_rejected_round1` / `test_planner_system_*` 绿；mock eval `premature_stop_rate=0.0` |
| 2 | `_parse_json` 禁跨段花括号；`_llm_json` 重试 2 次并发 `llm.parse_failure`；planner/verifier `max_tokens=2048`；`finish_reason==length` → `llm.truncation` | ✓ VERIFIED | `_parse_json` 仅 fence+`json.loads`；`_llm_json` L168–181；`config/llm.yaml` 2048；`_llm` L162–165；ORCH-03/04 单测绿 |
| 3 | verifier `_norm_status` 枚举匹配；`supported` 或 ≥2 `partial` 可 decisive；claim 为根因假设非 raw_line 自证 | ✓ VERIFIED | `_norm_status`/`_OK`/`decisive` L46–58,351–358；`_hypothesis_claim` L300–333；VERIFIER_SYSTEM 假设语义；ORCH-05/06 单测绿；mock `verdict_supported_ratio=1.0` |
| 4 | `excluded_skills` = unproductive-only；round1 选中且 productive 不被物理剔除；`(skill_id,args_hash)` 探针去重 | ✓ VERIFIED | `state.excluded_skills()` 仅 `unproductive_skills`；`executed_probes` + `_probe_key` 过滤；`test_excluded_skills_*` / `test_probe_dedup_*` 绿 |
| 5 | 未解释 ERROR 哨兵禁 `no_fault_found`→`insufficient_coverage`；全零分且 ERROR 信号注入 `SK-GENERIC-EVIDENCE-FIRST` | ✓ VERIFIED | `_unexplained_error_sweep` 经 `api.call("search_logs")`；`_guard_unexplained_errors`；A1 注入 L216–222；builtin `fallback_only: true`；ORCH-09/10 单测绿 |
| 6 | ORCH-08：引用数 ≥ `ceil(min_citation_ratio * chain_len)`，不足重试 1 次，仍不足 `insufficient_citation` | ✓ VERIFIED | `budget.yaml` `min_citation_ratio: 0.5`；`node_report` L389–415 + `citation_ratio_ok`；`test_insufficient_citation_*` 绿 |
| 7 | 回归门：`make test` 全绿；mock `make eval` `regression_count=0`；ORCH-01..10 已勾选且无残留 xfail | ✓ VERIFIED | `03-GATE-RESULTS.md`：247 passed / 0 failed / regression=0；REQUIREMENTS 10×`[x]`；`@pytest.mark.xfail` 无 ORCH 残留 |

**Score:** 7/7 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | ---------- | ------ | ------- |
| `src/vela/agent/graph.py` | 守卫 / `_llm_json` / `_norm_status` / sweep / 引用闸门 | ✓ VERIFIED | 实质性实现 + 主循环接线；非 stub |
| `src/vela/agent/state.py` | unproductive-only + `executed_probes` | ✓ VERIFIED | `excluded_skills()` 已改口径 |
| `src/vela/agent/skills.py` | `fallback_only` 排除 + 词面零分检测 | ✓ VERIFIED | `FALLBACK_SKILL_ID` / `has_positive_lexical_score` |
| `src/vela/gateway/prompts.py` | PLANNER 规则 5 + VERIFIER 假设语义 | ✓ VERIFIED | 旧「证据不足即 stop」诱导已消除 |
| `config/llm.yaml` | planner/verifier max_tokens 2048 | ✓ VERIFIED | 均为 2048，json_mode true |
| `config/budget.yaml` | `report.min_citation_ratio` | ✓ VERIFIED | 0.5 |
| `config/skills/builtin.yaml` | `SK-GENERIC-EVIDENCE-FIRST` | ✓ VERIFIED | `fallback_only: true`，keywords=[]，13 技能 |
| `src/vela/eval/process.py` | 真实事件优先聚合 | ✓ VERIFIED | parse/truncation/stop_rejected；脚注无「Phase 3 前偏高」 |
| `03-GATE-RESULTS.md` | 回归门实测 | ✓ VERIFIED | gate_status PASSED |
| `tests/test_{agent,gateway,eval}.py` | ORCH 行为单测（无 xfail） | ✓ VERIFIED | 本轮 `-k` ORCH 相关 15 测全绿 |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | --- | --- | ------ | ------- |
| `node_plan` / `node_verify` / `node_distill` | `_llm_json` | 统一 JSON 调用 | ✓ WIRED | 手写重试环已移除 |
| `_llm` | `llm.truncation` EventBus | `finish_reason==length` | ✓ WIRED | emit + `metrics.inc` |
| `out.stop` + `round_no==1` | `plan.stop_rejected` | 程序驳回后补 actions | ✓ WIRED | 再进主循环 stop 分支时 stop 已为 false |
| `excluded_skills` | `skills.retrieve` | unproductive-only | ✓ WIRED | used∪ 物理锁死已消除 |
| 全零分 + ERROR | `SK-GENERIC-EVIDENCE-FIRST` | A1 注入 | ✓ WIRED | 健康包无 ERROR 不注入（单测覆盖） |
| `node_verify` claims | `_hypothesis_claim` | 技能语义 | ✓ WIRED | claim ≠ raw_line |
| `verdicts.status` | `decisive` | `_norm_status` + partial≥2 | ✓ WIRED | weak 不推进 |
| `node_report` | `citation_ratio_ok` / budget | 重试→`insufficient_citation` | ✓ WIRED | `insufficient_coverage` 不被覆盖 |
| `_unexplained_error_sweep` | `LogQueryAPI.call` | `search_logs` | ✓ WIRED | 无 `api._q` 直连 |
| sweep samples | emit + root_cause/报告 | `coverage.unexplained_errors` | ✓ WIRED | report/unanswerable 双路径 |
| GATE-RESULTS | REQUIREMENTS ORCH 勾选 | 先测后勾 | ✓ WIRED | 10/10 `[x]` |

### Data-Flow Trace (Level 4)

本阶段产物为编排/配置/评测聚合（非 UI 渲染）。动态数据流抽查：

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `_unexplained_error_sweep` | `samples` | `api.call("search_logs", min_level=ERROR)` | 真实 DuckDB 行 vs evidence_pool | ✓ FLOWING |
| `node_plan` A1 | `sid`/`actions` | `has_positive_lexical_score` + `_has_error_signal` + probes | 注入 GENERIC 探针列表 | ✓ FLOWING |
| `aggregate_process_metrics` | rates | case `events` 真实 kind 优先 | 有真实事件时不用代理空 plan | ✓ FLOWING |
| `node_report` 引用闸门 | `text`/`st.status` | reporter LLM → `citation_ratio_ok` | 不足则重写或降级 | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| ORCH 单测子集 | `pytest … -k "stop_rejected or parse_json or …"` | 15 passed, exit 0 | ✓ PASS |
| `_parse_json` 禁跨段 | 直接调用跨段输入 | `{}` | ✓ PASS |
| `_norm_status` | `"Partially Supported"` | `partially_supported` | ✓ PASS |
| excluded unproductive-only | SessionState fixture | `["SK-B"]` only | ✓ PASS |
| GENERIC 不进常规 retrieve | `SkillRegistry.retrieve` | fallback 不在 top_n | ✓ PASS |
| 技能注册表规模 | `len(skills)` | 13 | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| ----- | ------- | ------ | ------ |
| — | — | 本阶段无 `scripts/*/tests/probe-*.sh` 声明 | SKIP |

回归门以 `make test` / `make eval` 为准（见 `03-GATE-RESULTS.md`，非 probe 脚本）。本 verifier 复跑 ORCH 相关 pytest；全量 247 / eval regression=0 采信 GATE 实测落盘（与用户提供的 03-07 证据一致）。

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ---------- | ----------- | ------ | -------- |
| ORCH-01 | 03-04 | 首轮 stop 守卫 + `plan.stop_rejected` | ✓ SATISFIED | graph 守卫 + 单测 |
| ORCH-02 | 03-04 | PLANNER 规则 5 重写 | ✓ SATISFIED | prompts.py |
| ORCH-03 | 03-02 | JSON 解析/重试/ALERT | ✓ SATISFIED | `_parse_json`/`_llm_json` |
| ORCH-04 | 03-02 | max_tokens + truncation | ✓ SATISFIED | llm.yaml + `_llm` |
| ORCH-05 | 03-05 | verdict 归一化 + partial | ✓ SATISFIED | `_norm_status`/decisive |
| ORCH-06 | 03-05 | claim=根因假设 | ✓ SATISFIED | `_hypothesis_claim` |
| ORCH-07 | 03-03 | unproductive-only + 探针去重 | ✓ SATISFIED | state/graph |
| ORCH-08 | 03-06 | 引用比例闸门 | ✓ SATISFIED | node_report + budget |
| ORCH-09 | 03-06 | 未解释 ERROR 哨兵 | ✓ SATISFIED | sweep + guard |
| ORCH-10 | 03-03 | GENERIC A1 注入 | ✓ SATISFIED | skills + node_plan |

无 ORPHANED 需求：REQUIREMENTS 映射 Phase 3 的 ORCH-01..10 均被计划覆盖并勾选 Complete。

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| — | — | 阶段改动源文件无 `TBD`/`FIXME`/`XXX` | — | 无阻断债务标记 |
| `tests/test_*.py` | 注释 | 「Wave 0 skeletons (xfail)」仅为历史标题 | ℹ️ Info | 无 `@pytest.mark.xfail` |

### Human Verification Required

无强制人工项。PLAN 未含 `<human-check>`；真实 LLM `--no-cache` 过程指标抽检在 03-07 / GATE-RESULTS 明确为**非阻断可选**（ADR-4：逻辑必然缺陷以确定性过程指标验收；mock 回归门为一票否决项且已通过）。

### Gaps Summary

无 gaps。目标「消除编排层逻辑必然缺陷」在代码层以程序化守卫 + 提示词双层防御落地；ORCH-01..10 均有实现、接线与单测；回归门记录与 REQUIREMENTS 勾选一致。

**反证备注（Confirmation Bias Counter，不构成 gap）：**
1. 真实 LLM 下 `premature_stop_rate` / `llm_parse_failure_rate` 等数值阈值未在本机复测——按计划属可选，mock 下均满足阈值。
2. ORCH-03「优先信任 json_mode」实现为信任 `json_mode` 返回的 JSON 文本再 `json.loads`，无独立 structured-object 字段；意图满足。
3. `premature_stop_rate` 在存在 `plan.stop_rejected` 时按「首轮被驳回」计——度量的是模型企图误停（被拦住）的频率；守卫保证误停无法生效。

---

_Verified: 2026-08-01T06:24:57Z_
_Verifier: Claude (gsd-verifier)_
