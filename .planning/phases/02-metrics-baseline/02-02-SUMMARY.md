---
phase: 02-metrics-baseline
plan: 02
subsystem: config-fingerprint
tags: [config_hash, NR-6, skills, budget, llm, prompts]

requires: []
provides:
  - "扩展后的 config_hash payload（skills/budget/llm/prompts_sha256）"
  - "docs/CONFIG_HASH_HISTORY.md 断代首行"
affects: [02-06, evidence-pack-salt]

tech-stack:
  added: []
  patterns: ["prompts 按文件字节哈希；env_checks 永不入 payload"]

key-files:
  created:
    - docs/CONFIG_HASH_HISTORY.md
  modified:
    - src/vela/config.py
    - tests/test_obs_and_config.py

key-decisions:
  - "D-05：纳入 skills/budget/llm/prompts"
  - "D-06：排除 env_checks"
  - "D-07：HISTORY 记录 old→new"

requirements-completed: [METR-03]
duration: 15min
completed: 2026-07-31
---

# Phase 02: Plan 02 Summary

**config_hash 覆盖技能/预算/LLM/提示词，并落盘 NR-6 断代表。**

## Task Commits

1. **Task 1: 扩展 config_hash + 扰动单测** - `b0c0e7c` (feat)
2. **Task 2: CONFIG_HASH_HISTORY** - （本 SUMMARY 同批 docs commit）

## Verification

- `pytest tests/test_obs_and_config.py -k config_hash -q` PASS
- old=`sha256:32d709b3…` → new=`sha256:7fe5f44c…`

## Self-Check: PASSED
