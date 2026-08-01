---
phase: 03-orch-logic-hemostasis
plan: 04
subsystem: agent-orchestration
tags: [ORCH-01, ORCH-02, stop_rejected, PLANNER_SYSTEM, premature_stop]

requires:
  - phase: 03-orch-logic-hemostasis
    provides: Wave 0 xfail skeletons for stop_rejected / planner_system
  - phase: 03-orch-logic-hemostasis
    provides: SK-GENERIC-EVIDENCE-FIRST + A1 注入（03-03）供驳回后补 actions 合流
provides:
  - "round_no==1 时 stop 程序化驳回 + plan.stop_rejected 可观测"
  - "PLANNER_SYSTEM 规则 5：停止调查 ≠ 无法定论；禁止尚无证据即 stop"
affects:
  - 03-05/06 (多轮 stop 仍合法；report/unanswerable 不再被首轮假 stop 短路)
  - 03-07 (premature_stop_rate / plan.stop_rejected 验收)

tech-stack:
  added: []
  patterns:
    - "控制流硬拦镜像 plan.illegal_skill：emit ALERT + metrics.inc + 改写模型标志"
    - "提示词引导 + 程序守卫双层防御（mock 不读正文，单测必须打守卫）"

key-files:
  created: []
  modified:
    - src/vela/gateway/prompts.py
    - src/vela/agent/graph.py
    - tests/test_gateway.py
    - tests/test_agent.py

key-decisions:
  - "驳回后无有效 selected_skill：取 retrieve 候选首项（已按相关度降序且排除 fallback_only），再否则 GENERIC"
  - "守卫置于 A1 GENERIC 注入之后、探针去重之前，避免假 stop 进主循环"

patterns-established:
  - "node_plan 内模型 stop 不可信；round1 强制 out[stop]=False 并保证可执行 actions"

requirements-completed: [ORCH-01, ORCH-02]

duration: 2min
completed: 2026-08-01
---

# Phase 3 Plan 04: 首轮 stop 守卫与规则 5 Summary

**ORCH-01/02：程序驳回 round1 stop（plan.stop_rejected）并重写 PLANNER_SYSTEM 规则 5，消除「证据不足→stop」诱导**

## Performance

- **Duration:** 2 min
- **Started:** 2026-08-01T06:08:07Z
- **Completed:** 2026-08-01T06:09:51Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- `PLANNER_SYSTEM` 规则 5 区分「停止调查」与「无法定论」；禁止首轮/尚无证据时 stop
- `node_plan`：`round_no==1 ∧ stop` → emit/inc `plan.stop_rejected`，清空 stop；空 actions 时按有效 skill → 候选首项 → `SK-GENERIC-EVIDENCE-FIRST` 补探针
- Wave 0 `planner_system` / `stop_rejected` xfail 摘除并转绿；round2+ stop 不被本守卫拦截

## Task Commits

1. **Task 1 RED: planner_system 契约** - `0020c85` (test)
2. **Task 1 GREEN: ORCH-02 规则 5 重写** - `4444f2f` (feat)
3. **Task 2 RED: stop_rejected 契约** - `14c63ee` (test)
4. **Task 2 GREEN: ORCH-01 首轮 stop 守卫** - `bf43f50` (feat)

**Plan metadata:** （待 docs commit）

## Files Created/Modified

- `src/vela/gateway/prompts.py` — PLANNER_SYSTEM 规则 5
- `src/vela/agent/graph.py` — `plan.stop_rejected` 守卫与 actions 回填
- `tests/test_gateway.py` — ORCH-02 转绿
- `tests/test_agent.py` — ORCH-01 转绿（含 round2 负例、actions 非空）

## Decisions Made

- 候选「最高分」用 `retrieve` 返回序的首项（池内已无 fallback_only），与 RESEARCH Open Q2 一致
- 守卫在 A1 之后：A1 已清 stop 时不再重复计数；仅模型仍主张 stop 时计量

## Deviations from Plan

None - plan executed exactly as written.

## TDD Gate Compliance

- RED commits: `0020c85`, `14c63ee`
- GREEN commits: `4444f2f`, `bf43f50`
- 无独立 REFACTOR commit（无需清理）

## Verification

```text
pytest -k 'stop_rejected or planner_system' → PASS
make test-fast PYTHON=.venv/bin/python3 → PASS
rg "证据不足时输出 stop=true" src/vela/gateway/prompts.py → 0
rg "plan\\.stop_rejected" src/vela/agent/graph.py → emit + inc
```

## Self-Check: PASSED

- FOUND: `src/vela/gateway/prompts.py`（规则 5：停止调查 / 无法定论 / 尚无证据禁止 stop）
- FOUND: `src/vela/agent/graph.py`（`plan.stop_rejected` emit + inc）
- FOUND: commits `0020c85`, `4444f2f`, `14c63ee`, `bf43f50`
