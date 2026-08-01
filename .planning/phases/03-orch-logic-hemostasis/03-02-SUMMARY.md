---
phase: 03-orch-logic-hemostasis
plan: 02
subsystem: agent-orchestration
tags: [ORCH-03, ORCH-04, llm-json, parse-failure, truncation, max_tokens, EventBus]

requires:
  - phase: 03-orch-logic-hemostasis
    provides: Wave 0 xfail skeletons for parse_json / max_tokens / truncation
provides:
  - "_parse_json 禁止跨段花括号；围栏 JSON 合法 dict"
  - "AgentGraph._llm_json retries=2 + llm.parse_failure ALERT"
  - "planner/verifier max_tokens=2048；_llm 对 finish_reason=length emit llm.truncation"
affects:
  - 03-03 (plan 路径守卫可依赖可靠 JSON)
  - 03-06 (process metrics 真实 parse/truncation 事件)

tech-stack:
  added: []
  patterns:
    - "_llm_json 统一 JSON 逻辑模型；reporter 仍走文本 _llm"
    - "截断告警在 graph 包装层（A5），不给 Gateway 挂 EventBus"

key-files:
  created: []
  modified:
    - src/vela/agent/graph.py
    - config/llm.yaml
    - tests/test_agent.py
    - tests/test_gateway.py

key-decisions:
  - "空 dict 视为解析失败并重试；跨段 find/rfind 分支删除"
  - "truncation 观测落在 AgentGraph._llm；单测用 object.__new__ 避免 test-fast 拉 built fixture"

patterns-established:
  - "JSON 节点（plan/verify/distill）一律 _llm_json；文本节点用 _llm"
  - "llm.parse_failure / llm.truncation 为真实事件名，供 eval/process 优先聚合"

requirements-completed: [ORCH-03, ORCH-04]

duration: 3min
completed: 2026-08-01
---

# Phase 3 Plan 02: LLM JSON 契约与截断止血 Summary

**加固 `_parse_json`/`_llm_json`（禁跨段假成功、重试+ALERT）并将 planner/verifier `max_tokens` 提至 2048，截断经 graph 包装层可观测**

## Performance

- **Duration:** 3 min
- **Started:** 2026-08-01T05:58:25Z
- **Completed:** 2026-08-01T06:01:22Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- `_parse_json`：仅围栏剥离 + 整段 `json.loads` 且必须为 dict；删除 `find("{")/rfind("}")` 跨段抢救
- `_llm_json`：1 次初始 + 最多 2 次重试；耗尽 `llm.parse_failure` ALERT + metrics；plan/verify/distiller 接入
- `_llm`：`finish_reason=="length"` → `llm.truncation` ALERT + metrics（ORCH-04 / A5）
- `config/llm.yaml`：planner/verifier `max_tokens: 2048`；reporter 保持 2048
- Wave 0 `parse_json` / `max_tokens` / `truncation` xfail 摘除并转绿

## Task Commits

1. **Task 1 RED: 摘除 parse_json xfail** - `5acb96a` (test)
2. **Task 1 GREEN: _parse_json + _llm_json** - `58767d7` (feat)
3. **Task 2 RED: truncation 契约改测** - `c986f47` (test)
4. **Task 2 GREEN: max_tokens 2048 + 轻量 truncation 测** - `0548743` (feat)

**Plan metadata:** （待 docs commit）

## Files Created/Modified

- `src/vela/agent/graph.py` — `_parse_json` 加固、`_llm_json`、truncation emit、节点改用 `_llm_json`
- `config/llm.yaml` — planner/verifier max_tokens=2048
- `tests/test_agent.py` — ORCH-03 parse_json 去 xfail
- `tests/test_gateway.py` — ORCH-04 max_tokens/truncation 去 xfail；truncation 经 `_llm` 轻量壳

## Decisions Made

- 截断告警放在 `AgentGraph._llm`（RESEARCH A5），不给 Gateway 挂 EventBus
- truncation 单测用 `object.__new__(AgentGraph)` 绑定 metrics/bus/gw，避免 `test-fast` 拉 session `built`（会导入 pyarrow/建库）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] truncation 测改轻量壳以保住 test-fast**
- **Found during:** Task 2
- **Issue:** 初版用 `built`+完整 `AgentGraph` 构造，使 `make test-fast`（含 `test_gateway.py`）在非 venv/`built` 路径 ERROR
- **Fix:** 改为 `object.__new__` + 注入 Metrics/EventBus/LengthProvider gateway，直接调 `AgentGraph._llm`
- **Files modified:** `tests/test_gateway.py`
- **Verification:** `make test-fast PYTHON=.venv/bin/python3` 绿；`-k 'max_tokens or truncation'` 绿
- **Committed in:** `0548743`

---

**Total deviations:** 1 auto-fixed (blocking)
**Impact on plan:** 契约不变（仍测 graph 包装层 truncation）；仅降低 fixture 重量以兼容 test-fast。

## Issues Encountered

None beyond the test-fast fixture issue above.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 真实 `llm.parse_failure` / `llm.truncation` 事件已可被 03-06 process 聚合消费
- 03-03 可依赖稳定 JSON 解析路径做 stop/剔除/fallback 守卫

## Self-Check: PASSED

- FOUND: src/vela/agent/graph.py (`_llm_json`, `llm.parse_failure`, `llm.truncation`)
- FOUND: config/llm.yaml (planner/verifier max_tokens 2048)
- FOUND: commit 5acb96a
- FOUND: commit 58767d7
- FOUND: commit c986f47
- FOUND: commit 0548743

---
*Phase: 03-orch-logic-hemostasis*
*Completed: 2026-08-01*
