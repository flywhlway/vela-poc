---
phase: 03-orch-logic-hemostasis
plan: 03
subsystem: agent-orchestration
tags: [ORCH-07, ORCH-10, excluded_skills, executed_probes, fallback_only, GENERIC, A1]

requires:
  - phase: 03-orch-logic-hemostasis
    provides: Wave 0 xfail skeletons for unproductive-only / probe_dedup / generic_fallback
  - phase: 03-orch-logic-hemostasis
    provides: 可靠 JSON 契约（03-02）供 node_plan 守卫依赖
provides:
  - "excluded_skills = unproductive-only；productive used 可复用"
  - "executed_probes 键 {skill_id}:{blake2b(canonical_json(args),8)}"
  - "SK-GENERIC-EVIDENCE-FIRST + fallback_only；A1 全零分∧ERROR 注入"
affects:
  - 03-04 (首轮 stop 驳回后可合流 GENERIC 补 actions)
  - 03-05/06 (多轮深挖不再被 used 锁死)

tech-stack:
  added: []
  patterns:
    - "探针去重复用 hashlib.blake2b + canonical_json，禁止第二套 canonical"
    - "A1 注入谓词：词面全零分 AND ERROR 信号（levels/evidence/abort）"

key-files:
  created: []
  modified:
    - src/vela/agent/state.py
    - src/vela/agent/skills.py
    - src/vela/agent/graph.py
    - config/skills/builtin.yaml
    - tests/test_agent.py
    - tests/test_obs_and_config.py

key-decisions:
  - "有效候选分=词面命中；稠密噪声不算，空检索查询视为全零"
  - "A1 相对 REQUIREMENTS 字面收窄：健康包无 ERROR 不注入 GENERIC"
  - "generic_fallback 正例用 round>1 + levels.ERROR 构造全零分，避免 birdseye 写入匹配信号假阴性"

patterns-established:
  - "SessionState.executed_probes + graph._args_hash/_probe_key 为探针级去重唯一路径"
  - "fallback_only 技能仅经编排注入，retrieve pool 物理排除"

requirements-completed: [ORCH-07, ORCH-10]

duration: 4min
completed: 2026-08-01
---

# Phase 3 Plan 03: 技能剔除与 GENERIC 兜底 Summary

**ORCH-07 剔除回归 unproductive-only + blake2b 探针去重；ORCH-10 落地 SK-GENERIC-EVIDENCE-FIRST，仅全零分且存在 ERROR 时注入（A1）**

## Performance

- **Duration:** 4 min
- **Started:** 2026-08-01T06:02:28Z
- **Completed:** 2026-08-01T06:06:03Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- `excluded_skills()` → `sorted(set(unproductive_skills))`；删除 used∪unproductive 旧测
- `SessionState.executed_probes`；`node_plan` 过滤重复探针，`node_retrieve` 成功后记账
- `builtin.yaml` 新增 `SK-GENERIC-EVIDENCE-FIRST`（`fallback_only: true`，空 keywords，`root_cause_label: null`）
- `SkillRegistry.retrieve` 排除 `fallback_only`；`has_positive_lexical_score` + `_has_error_signal` 驱动 A1 注入
- 技能数断言 12→13；Wave 0 `excluded_skills` / `probe_dedup` / `generic_fallback` xfail 摘除并转绿

## Task Commits

1. **Task 1 RED: unproductive-only + probe_dedup 契约** - `8d6085a` (test)
2. **Task 1 GREEN: ORCH-07 剔除与探针去重** - `9bdfa7a` (feat)
3. **Task 2 RED: GENERIC A1 契约 + 技能数 13** - `297bfb9` (test)
4. **Task 2 GREEN: SK-GENERIC-EVIDENCE-FIRST + A1 注入** - `f0d4829` (feat)

**Plan metadata:** _(pending final docs commit)_

## Files Created/Modified

- `src/vela/agent/state.py` — unproductive-only + `executed_probes`
- `src/vela/agent/graph.py` — `_args_hash` / `_probe_key` / `_has_error_signal`；plan 去重与 A1 注入；retrieve 记账
- `src/vela/agent/skills.py` — `fallback_only` 过滤、`FALLBACK_SKILL_ID`、`has_positive_lexical_score`
- `config/skills/builtin.yaml` — GENERIC 技能
- `tests/test_agent.py` — ORCH-07/10 转绿；loads_all_13
- `tests/test_obs_and_config.py` — load_skills 计数 13（Rule 3）

## Decisions Made

- 词面命中作为「有效候选分」；避免 dense 噪声使「全零分」永不触发
- A1 健康特异性：全零分无 ERROR → 不注入（Pitfall 5）
- 正例单测避开 birdseye 写入 abort_reason（否则非全零），改用 `levels.ERROR` + 空召回查询

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 同步更新 load_skills 计数断言**
- **Found during:** Task 2
- **Issue:** `tests/test_obs_and_config.py::test_load_skills_returns_12_sorted_by_id` 在 builtin 增技能后必红
- **Fix:** 改为 `returns_13` 并断言含 `SK-GENERIC-EVIDENCE-FIRST`
- **Files modified:** `tests/test_obs_and_config.py`
- **Committed in:** `297bfb9`

**2. [Rule 1 - Bug] 修正 generic_fallback 正例构造**
- **Found during:** Task 2
- **Issue:** Wave 0 用 round1+UDS 信号会经 birdseye/召回产生非零词面分，A1 无法触发
- **Fix:** 正例改为 round=2、空召回信号 + `levels.ERROR`；反例健康包无 ERROR
- **Files modified:** `tests/test_agent.py`
- **Committed in:** `297bfb9`

## TDD Gate Compliance

- RED commits: `8d6085a`, `297bfb9`
- GREEN commits: `9bdfa7a`, `f0d4829`
- 无独立 REFACTOR commit（无需清理）

## Verification

```text
pytest tests/test_agent.py -k 'excluded_skills or probe_dedup or generic_fallback or loads_all'  → PASS
make test-fast PYTHON=.venv/bin/python3 → PASS
```

## Self-Check: PASSED

- FOUND: `src/vela/agent/state.py` (`executed_probes`)
- FOUND: `config/skills/builtin.yaml` (`SK-GENERIC-EVIDENCE-FIRST`, `fallback_only`)
- FOUND: commits `8d6085a`, `9bdfa7a`, `297bfb9`, `f0d4829`
