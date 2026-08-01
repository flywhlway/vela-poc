---
phase: 03-orch-logic-hemostasis
plan: 06
subsystem: agent-orchestration
tags: [ORCH-08, ORCH-09, citation-ratio, unexplained-error-sweep, process-metrics, LogQueryAPI]

requires:
  - phase: 03-orch-logic-hemostasis
    provides: Wave 0 xfail skeletons for insufficient_citation / unexplained_sweep / process metrics
  - phase: 03-orch-logic-hemostasis
    provides: verify 假设 claims 与 partial 归一化（03-05），report 路径可到达
provides:
  - "ORCH-08：min_citation_ratio 闸门 + 单次修复重试 → insufficient_citation"
  - "ORCH-09：_unexplained_error_sweep via LogQueryAPI；禁 no_fault_found → insufficient_coverage + samples[:10]"
  - "过程指标真实事件优先；MISDIAGNOSIS_EXCLUDED_STATUSES；PROXY_FOOTNOTE 去 Phase 3 偏高脚注"
affects:
  - 03-07 (过程指标验收与回归门)
  - eval/runner healthy_specificity（insufficient_* 非 answered）

tech-stack:
  added: []
  patterns:
    - "引用比例读 budget.yaml report.min_citation_ratio，禁止 graph 硬编码阈值"
    - "ERROR 扫描只经 api.call(search_logs)，差集对 evidence_pool.row_hash"
    - "aggregate_process_metrics：真实事件优先、代理 fallback"

key-files:
  created: []
  modified:
    - config/budget.yaml
    - src/vela/agent/citations.py
    - src/vela/agent/graph.py
    - src/vela/agent/state.py
    - src/vela/eval/process.py
    - tests/test_agent.py
    - tests/test_eval.py

key-decisions:
  - "status 与 root_cause.label 同步 insufficient_*；run 不覆盖诚实终态"
  - "降级时 samples 同时进 emit payload、root_cause.unexplained_samples、报告附录"
  - "过程指标按批次是否含真实事件切换口径；ablation 分母仍含 insufficient_*、分子排除"

patterns-established:
  - "node_report：dangling → 比例闸门重试 → insufficient_citation；ORCH-09 守卫在 reporter 之前"
  - "node_unanswerable 亦跑 sweep，库有未解释 ERROR 时改 insufficient_coverage"

requirements-completed: [ORCH-08, ORCH-09]

duration: 4min
completed: 2026-08-01
---

# Phase 3 Plan 06: 引用比例闸门与未解释错误哨兵 Summary

**ORCH-08/09：报告引用比例闸门 + LogQueryAPI 未解释 ERROR 哨兵，过程指标改为真实事件优先聚合**

## Performance

- **Duration:** 4 min
- **Started:** 2026-08-01T06:15:34Z
- **Completed:** 2026-08-01T06:19:14Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments

- `budget.yaml` 增加 `report.min_citation_ratio: 0.5`；`citation_ratio_ok`；不足则带修复提示重试 1 次 → `insufficient_citation`
- `_unexplained_error_sweep` 经 `api.call("search_logs")`；禁 `no_fault_found` → `insufficient_coverage`，`samples[:10]` 附着 emit / root_cause / 报告
- `aggregate_process_metrics` 优先 `llm.parse_failure` / `llm.truncation` / `plan.stop_rejected`；`MISDIAGNOSIS_EXCLUDED_STATUSES`；脚注去掉「Phase 3 前允许偏高」
- Wave 0 四测摘除 xfail 并转绿

## Task Commits

1. **Task 1 RED: citation ratio 契约** - `76c207f` (test)
2. **Task 1 GREEN: ORCH-08 引用比例闸门** - `877a2aa` (feat)
3. **Task 2 RED: sweep / process metrics 契约** - `0a729c6` (test)
4. **Task 2 GREEN: ORCH-09 哨兵与真实事件口径** - `05207d3` (feat)

**Plan metadata:** _(pending docs commit)_

## Files Created/Modified

- `config/budget.yaml` — `report.min_citation_ratio`
- `src/vela/agent/citations.py` — `citation_ratio_ok`
- `src/vela/agent/graph.py` — 比例闸门、`_unexplained_error_sweep`、`_guard_unexplained_errors`、unanswerable 守卫
- `src/vela/agent/state.py` — status 注释含 insufficient_*
- `src/vela/eval/process.py` — 真实事件优先 + ablation 排除
- `tests/test_agent.py` / `tests/test_eval.py` — 摘除 xfail

## Decisions Made

- 诚实终态用 `SessionState.status` 新值，`root_cause.label` 同步；`run` 仅在 `status=="running"` 时写 `answered`
- samples 字段名 `unexplained_samples`（root_cause）与 emit `samples`（≤10）
- insufficient_coverage 优先于引用比例降级（覆盖不足已是终态）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical] run() 覆盖诚实终态**
- **Found during:** Task 1
- **Issue:** `node_report` 设 `insufficient_citation` 后，`run` 仍无条件写 `answered`/`human_gate`
- **Fix:** 仅当 `status=="running"`（或非 insufficient_*）时写入后续终态
- **Files modified:** `src/vela/agent/graph.py`
- **Committed in:** `877a2aa`

**Total deviations:** 1 auto-fixed (Rule 2)
**Impact on plan:** 正确性必需；无范围蔓延。

## TDD Gate Compliance

- RED commits: `76c207f`, `0a729c6`
- GREEN commits: `877a2aa`, `05207d3`
- 无独立 REFACTOR commit

## Verification

```text
PYTHONPATH=src VELA_CONFIG_DIR=config .venv/bin/python3 -m pytest \
  tests/test_agent.py tests/test_eval.py \
  -k 'insufficient_citation or unexplained_sweep or process_metrics_prefer or ablation_excludes_insufficient' -q
# 4 passed

PYTHON=.venv/bin/python3 make test-fast
# 全绿

PYTHONPATH=src VELA_CONFIG_DIR=config .venv/bin/python3 -m pytest tests/test_agent.py tests/test_eval.py -q
# 全绿
```

## Known Stubs

None.

## Next Phase Readiness

- ORCH-08/09 落地；03-07 可对照过程指标做回归验收
- 无阻断项

## Self-Check: PASSED

- FOUND: `config/budget.yaml` (`min_citation_ratio`)
- FOUND: `src/vela/agent/graph.py` (`_unexplained_error_sweep`, `insufficient_citation`, `coverage.unexplained_errors`)
- FOUND: `src/vela/eval/process.py` (`llm.parse_failure`, `MISDIAGNOSIS_EXCLUDED_STATUSES`)
- FOUND commits: `76c207f`, `877a2aa`, `0a729c6`, `05207d3`
---
*Phase: 03-orch-logic-hemostasis*
*Completed: 2026-08-01*
