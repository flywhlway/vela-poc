---
phase: 02-metrics-baseline
plan: 04
subsystem: eval
tags: [repeat, reuse-workspace, scipy, no-cache, METR-04, METR-07]

requires:
  - phase: 02-01
    provides: None-safe metrics
  - phase: 02-03
    provides: LLM cache switch
provides:
  - "--repeat N 聚合与 CI"
  - "--reuse-workspace 三条件复用"
  - "--no-cache CLI 接线"
affects: [02-05, 02-06]

key-files:
  created: [src/vela/eval/stats.py]
  modified: [pyproject.toml, requirements-optional.txt, src/vela/eval/runner.py, src/vela/eval/report.py, src/vela/cli.py, src/vela/agent/graph.py, Makefile, tests/test_eval.py]

requirements-completed: [METR-04, METR-07]
duration: 25min
completed: 2026-07-31
---

# Phase 02: Plan 04 Summary

**`--repeat` / `--reuse-workspace` / `--no-cache` 可测；scipy t-CI 入 optional。**

退出码：repeat 模式用聚合均值对照原四条件。

## Self-Check: PASSED
