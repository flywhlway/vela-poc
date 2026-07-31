---
phase: 02-metrics-baseline
plan: 01
subsystem: eval-metrics
tags: [citations, citation_coverage, dangling_rate, None-safe]

requires: []
provides:
  - "CitationReport 零引用闸门（ok=False / dangling_rate=None / has_citations）"
  - "citation_coverage 事实句覆盖率"
  - "EvalRunner/report None-safe 聚合与报表目标"
affects: [02-04, 02-05, 02-06]

tech-stack:
  added: []
  patterns: ["None-safe dangling_rate 聚合；coverage 入 _TARGETS 但不进 cmd_eval 硬门"]

key-files:
  created: []
  modified:
    - src/vela/agent/citations.py
    - src/vela/eval/runner.py
    - src/vela/eval/report.py
    - src/vela/obs/metrics.py
    - src/vela/agent/graph.py
    - src/vela/cli.py
    - tests/test_agent.py
    - tests/test_eval.py

key-decisions:
  - "D-01/D-02：total==0 → dangling_rate=None、ok=False"
  - "D-03：citation_coverage 确定性启发式切分；无事实句=1.0"
  - "D-04/D-24：仅 None-safe 计量，未改 node_report 控制流"
  - "D-25：cmd_eval 硬退出不纳入 has_citations"

patterns-established:
  - "Metrics.gauge 忽略 None"
  - "dangling_citation_rate 仅对有引用用例求均值"

requirements-completed: [METR-01, METR-02]

duration: 25min
completed: 2026-07-31
---

# Phase 02: Plan 01 Summary

**消除 F-01 零引用悖论：度量侧强制失败 + coverage 入报表，且不改推理控制流。**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-07-31T15:34:54Z
- **Completed:** 2026-07-31T15:42:00Z
- **Tasks:** 2/2
- **Files modified:** 8

## Accomplishments
- `CitationReport`：零引用 `ok=False`、`dangling_rate=None`、`has_citations`
- `citation_coverage` / `split_factual_sentences` 模块级 API + 单测
- Eval/CLI None-safe；`_TARGETS` 增加 coverage（G1≥0.9 仅报表）

## Task Commits

1. **Task 1: 零引用闸门与 coverage** - `a5e9244` (feat)
2. **Task 2: None-safe 聚合入报表** - `11293ae` (feat)

## Files Created/Modified
- `src/vela/agent/citations.py` — 闸门语义 + coverage
- `src/vela/eval/runner.py` / `report.py` — 聚合与目标
- `src/vela/obs/metrics.py` / `graph.py` — None-safe gauge/事件
- `src/vela/cli.py` — 展示 + 退出码 None 守卫
- `tests/test_agent.py` / `tests/test_eval.py` — 边界单测

## Deviations
- 无

## Verification
- `pytest tests/test_agent.py tests/test_eval.py -q` PASS
- `make test-fast` PASS
- graph.py 仅 None-safe 计量，无重试/status 改动

## Self-Check: PASSED
- key-files 均存在；`git log --grep=02-01` 有提交
- acceptance_criteria 已复核
