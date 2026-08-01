---
phase: 03-orch-logic-hemostasis
plan: 05
subsystem: agent-orchestration
tags: [ORCH-05, ORCH-06, _norm_status, partial, hypothesis-claim, verifier]

requires:
  - phase: 03-orch-logic-hemostasis
    provides: Wave 0 xfail skeletons for verdict_norm / verify_claim_hypothesis
  - phase: 03-orch-logic-hemostasis
    provides: 首轮 stop 守卫与 PLANNER 规则 5（03-04），verify 路径可被到达
provides:
  - "_norm_status + _OK 集合；decisive = supported 或 ≥2 partial"
  - "claims 为技能根因假设（非 raw_line 自证）；单假设多 citations；claims≤5"
  - "VERIFIER_SYSTEM / mock._verify 与 partial 归一化路径对齐"
affects:
  - 03-06 (citation ratio / unexplained sweep 依赖 verify 语义)
  - 03-07 (verdict_supported_ratio 验收)

tech-stack:
  added: []
  patterns:
    - "模型 status 字符串不可信 → 归一化后再进控制流"
    - "claim=技能假设 + citations=证据 row_hash，打破自证循环"

key-files:
  created: []
  modified:
    - src/vela/agent/graph.py
    - src/vela/gateway/prompts.py
    - src/vela/gateway/mock.py
    - tests/test_agent.py

key-decisions:
  - "默认构造 1 条根因假设 claim（技能 title/label/summary），citations 挂全部错误级证据 row_hash"
  - "weak 不计入 _OK/partial；mock 原 weak 路径改为 partial，避免评测分叉"
  - "verify.done 的 supported 计数仅含归一化后的 supported（partial 不进分子）"

patterns-established:
  - "node_verify 判据：_norm_status + (supported ∨ ≥2 partial) ∧ has_error_evidence ∧ skill label"

requirements-completed: [ORCH-05, ORCH-06]

duration: 2min
completed: 2026-08-01
---

# Phase 3 Plan 05: Verifier 判据归一化与假设 Claims Summary

**ORCH-05/06：`_norm_status` + partial 可推进，claims 改为技能根因假设，消除脆弱精确匹配与 raw_line 自证循环**

## Performance

- **Duration:** 2 min
- **Started:** 2026-08-01T06:11:26Z
- **Completed:** 2026-08-01T06:13:21Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- `node_verify` 以 `_hypothesis_claim` 构造根因假设（title/label/summary），多 citations，claims≤5
- `_norm_status` + `_OK`：`Supported` / `partially_supported` / `partially-supported` / `supported with caveats` 可识别；decisive = supported 或 ≥2 partial
- `VERIFIER_SYSTEM` 与 `mock._verify`（weak→partial）对齐真实归一化路径
- Wave 0 `verify_claim_hypothesis` / `verdict_norm` xfail 摘除并转绿

## Task Commits

1. **Task 1 RED: claim hypothesis 契约** - `c3b4772` (test)
2. **Task 1 GREEN: ORCH-06 假设 claims** - `987db6c` (feat)
3. **Task 2 RED: verdict_norm 契约** - `844e74a` (test)
4. **Task 2 GREEN: ORCH-05 归一化与 partial** - `e5cd337` (feat)

**Plan metadata:** _(pending final docs commit)_

## Files Created/Modified

- `src/vela/agent/graph.py` — `_norm_status` / `_OK` / `_hypothesis_claim`；decisive 放宽
- `src/vela/gateway/prompts.py` — VERIFIER_SYSTEM 假设语义 + partial 枚举与变体说明
- `src/vela/gateway/mock.py` — 弱支撑输出 `partial`
- `tests/test_agent.py` — ORCH-05/06 摘除 xfail 并转绿

## Decisions Made

- 单假设多 citations（而非每行一条 claim），消除「日志支撑自己」循环
- `weak` 保留在提示词枚举但不进 `_OK`；程序侧只认 supported/partial 族

## Deviations from Plan

None - plan executed exactly as written.

## TDD Gate Compliance

- RED commits: `c3b4772`, `844e74a`
- GREEN commits: `987db6c`, `e5cd337`
- 无独立 REFACTOR commit（无需清理）

## Verification

```text
pytest -k 'verdict_norm or verify_claim_hypothesis' → PASS
make test-fast PYTHON=.venv/bin/python3 → PASS
make test PYTHON=.venv/bin/python3 → PASS（剩余 xx 为后续 plan xfail）
rg 'status == "supported"' src/vela/agent/graph.py → 0
rg "def _norm_status|partially_supported" src/vela/agent/graph.py → 命中
```

## Self-Check: PASSED

- FOUND: `src/vela/agent/graph.py`（`_norm_status` / `_hypothesis_claim` / `partially_supported`）
- FOUND: `src/vela/gateway/prompts.py`（partial + 根因假设）
- FOUND: `src/vela/gateway/mock.py`（status=partial）
- FOUND: commits `c3b4772`, `987db6c`, `844e74a`, `e5cd337`
