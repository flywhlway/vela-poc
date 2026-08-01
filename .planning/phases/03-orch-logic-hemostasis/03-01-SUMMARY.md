---
phase: 03-orch-logic-hemostasis
plan: 01
subsystem: testing
tags: [pytest, xfail, ORCH, wave0, nyquist]

requires:
  - phase: 02-metrics-baseline
    provides: process metrics fixture shape and PROXY_FOOTNOTE
provides:
  - ORCH-01..10 可收集 xfail 单测骨架（-k 可定位）
  - 过程指标真实事件优先 / ablation insufficient 排除骨架
affects:
  - 03-02 (parse/truncation 摘除 xfail)
  - 03-03 (exclude/dedup/generic 摘除 xfail)
  - 03-04 (stop_rejected / planner_system 摘除 xfail)
  - 03-05 (verdict/claim 摘除 xfail)
  - 03-06 (citation/sweep/process metrics 摘除 xfail)

tech-stack:
  added: []
  patterns:
    - "strict xfail Wave 0：完整断言体 + reason 指向目标 plan；实现时摘除"
    - "子类覆盖 _llm 驱动守卫契约，禁止 unittest.mock"

key-files:
  created: []
  modified:
    - tests/test_agent.py
    - tests/test_gateway.py
    - tests/test_eval.py

key-decisions:
  - "Wave 0 不改生产代码；旧 test_excluded_skills_includes_used_and_unproductive 暂保留（仍绿），新测 unproductive_only 以 xfail 锁定目标契约"
  - "ORCH 需求勾选留给 03-02..03-07 实现转绿后再 mark-complete，本 plan 仅建立采样连续性"

patterns-established:
  - "AgentGraph 子类 Force*_llm 注入模型输出，直接调 node_* 断言守卫/指标/事件"
  - "xfail reason 格式：ORCH pending plan 03-NN"

requirements-completed: []

duration: 4min
completed: 2026-08-01
---

# Phase 3 Plan 01: ORCH Wave 0 单测骨架 Summary

**为 ORCH-01..10 建立可收集的 strict xfail 契约骨架，锁定 -k 关键字与后续 RED→GREEN 摘除路径**

## Performance

- **Duration:** 4 min
- **Started:** 2026-08-01T05:53:03Z
- **Completed:** 2026-08-01T05:56:48Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- `tests/test_agent.py`：9 个 ORCH 行为骨架（stop_rejected / parse_json / verdict_norm / claim_hypothesis / excluded unproductive-only / probe_dedup / insufficient_citation / unexplained_sweep / generic_fallback）
- `tests/test_gateway.py`：planner_system / max_tokens=2048 / truncation 计数骨架
- `tests/test_eval.py`：真实 parse/truncation 事件优先 + insufficient 状态消融排除骨架
- `make test-fast` 绿（gateway xfail 计为预期失败）；agent/eval `-k` 收集/执行为 xfail

## Task Commits

1. **Task 1: 写入 ORCH agent/gateway 单测骨架（xfail）** - `b859628` (test)
2. **Task 2: 写入过程指标真实事件优先骨架（xfail）** - `b8f3778` (test)

**Plan metadata:** （见 final docs commit）

## Files Created/Modified

- `tests/test_agent.py` — ORCH-01/03/05/06/07/08/09/10 Wave 0 xfail
- `tests/test_gateway.py` — ORCH-02/04 Wave 0 xfail
- `tests/test_eval.py` — 过程指标 / ablation Wave 0 xfail（→ 03-06）

## Decisions Made

- 旧 `test_excluded_skills_includes_used_and_unproductive` 保留且仍绿；新增 `test_excluded_skills_unproductive_only` 为 xfail，避免 Wave 0 因 strict XPASS 弄红 test-fast/全量门
- 不调用 `requirements.mark-complete`：本 plan 只交付测试契约，ORCH-01..10 实现验收在后续 plan

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- 03-02 可摘除 parse_json / max_tokens / truncation xfail 并转绿
- 后续 03-03..03-06 按 reason 映射摘除对应骨架 xfail

## Self-Check: PASSED

- FOUND: tests/test_agent.py（含 stop_rejected 等 ≥8 个 def）
- FOUND: tests/test_gateway.py（planner_system / max_tokens / truncation）
- FOUND: tests/test_eval.py（process_metrics_prefer / ablation_excludes_insufficient）
- FOUND: commit b859628
- FOUND: commit b8f3778

---
*Phase: 03-orch-logic-hemostasis*
*Completed: 2026-08-01*
