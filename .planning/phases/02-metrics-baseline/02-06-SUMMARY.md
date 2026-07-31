---
phase: 02-metrics-baseline
plan: 06
subsystem: baseline
tags: [METR-09, PERF-01, volcengine, no-cache, NR-1]

requires: [02-01, 02-02, 02-03, 02-04, 02-05]
provides:
  - "baseline/report.md + result.json（N=3 volcengine no-cache）"
  - "make baseline / bench-volc 脚手架"
  - "02-GATE-RESULTS.md 回归门 failed=0 regression=0"
affects: [phase-03+]

key-files:
  created:
    - .planning/phases/02-metrics-baseline/baseline/README.md
    - .planning/phases/02-metrics-baseline/baseline/report.md
    - .planning/phases/02-metrics-baseline/baseline/result.json
    - .planning/phases/02-metrics-baseline/02-GATE-RESULTS.md
    - tests/test_realllm_baseline.py
  modified:
    - scripts/bench.py
    - Makefile

requirements-completed: [METR-09, PERF-01]
duration: 45min
completed: 2026-08-01
---

# Phase 02: Plan 06 Summary

**真实无缓存基线已落盘：N=3 volcengine，NR-1 退役 44.4%；回归门 failed=0 / regression=0。**

## Task Commits

1. **Task 1: bench/Makefile/README** — `fa514b4` / `1a4d4ee`
2. **Task 2: GATE-RESULTS** — `efd628e`
3. **Task 3: 付费基线落盘** — 本 SUMMARY 同批（report.md + result.json）

## Key numbers

- top1 mean ≈ **0.5185**，95% CI ≈ **[0.20, 0.84]**（N=3）
- diagnose P95 ≈ **109.8 s**（末次 run）
- METR-09 / PERF-01: **done**（有凭证路径）

## Self-Check: PASSED
