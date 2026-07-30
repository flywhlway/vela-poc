---
phase: 01-llm
plan: 06
subsystem: cli-doctor
tags: [doctor, ENV-03, ENV-04, D-12, D-13, D-14, D-15, D-18, --json, exit-code]

requires:
  - phase: 01-llm/01-03
    provides: dotenv_report() → {path, loaded, keys, shadowed}（只含键名）
  - phase: 01-llm/01-04
    provides: OpenAICompatProvider.probe() 五键归因
  - phase: 01-llm/01-05
    provides: EnvChecker.run() → list[{name,ok,detail,kind=local}] + mask_secret
provides:
  - cmd_doctor 双通道渲染（list[dict] → 人读 / --json）
  - --offline / --online / --json 三参数与互斥校验（rc=2）
  - D-14 退出码分层（local→1，connectivity→0）
  - 八条 tests/test_doctor.py 护栏
affects: [01-llm/01-07, 01-llm/01-08, Phase 2 评测环境指纹]

tech-stack:
  added: []
  patterns:
    - "先收集 checks:list[dict] 再双通道遍历同一变量（照 qa.py）"
    - "hasattr(provider, 'probe') 判定可探测性，CLI 不 import openai"
    - "local_bad 决定退出码；连通性失败只标 ❌"

key-files:
  created:
    - tests/test_doctor.py
  modified:
    - src/vela/cli.py

key-decisions:
  - "跳过网络时前三项 warn 跳过；第 4 项仍本地 models_for，保证输出含四个逻辑模型名"
  - "--json 顶层键钉死供 Phase 2 消费（见下文清单）"
  - "ENV-03/ENV-04 呈现层本 plan 交付；REQUIREMENTS 勾选随 roadmap 更新"

patterns-established:
  - "Pattern: doctor checks 五键 {name, ok, detail, kind, warn}"
  - "Pattern: do_probe = online or (not offline and provider != mock)"
  - "Pattern: 去重物理模型各 probe 一次，聚合 reachable/authenticated/model_ok"

requirements-completed: [ENV-03, ENV-04]

duration: 3min
completed: 2026-07-30
---

# Phase 1 Plan 6: doctor 双通道自检与退出码分层 Summary

**`vela doctor` 重构为单一 `checks` 列表 + 人读/`--json` 同源渲染：EnvChecker 形态错误 rc=1，连通性失败仅标 ❌ 仍 rc=0；mock 零网络，八条护栏全绿。**

## Performance

- **Duration:** 3min
- **Started:** 2026-07-30T23:34:00Z
- **Completed:** 2026-07-30T23:36:27Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `cmd_doctor`：配置/依赖/`EnvChecker`/连通性四项 → `list[dict]` → 双通道（D-18）
- D-12/D-13：provider 自动判定探测；`--offline`/`--online` 双向覆盖，互斥返 2
- D-14：`local_bad → 1`，连通性失败不影响退出码（注释指向 `run_all.sh` / Makefile）
- D-15：逻辑模型映射本地 `models_for`；有 `probe` 时去重物理模型最小 chat
- `tests/test_doctor.py`：8 条护栏（跳过/JSON/互斥/掩码/形态/D-14/dotenv 不泄值）
- 全量 pytest 211 passed（≥ 基线 177）

## Task Commits

1. **Task 1: 重构 cmd_doctor 为 list[dict] 收集 + 双通道渲染** - `81baf2e` (feat)
2. **Task 2: 新建 tests/test_doctor.py 六类护栏** - `00c5ead` (test)

**Plan metadata:** `bd52900` (docs: complete plan)

## 供 Phase 2 消费：`--json` 顶层键清单

`vela doctor --json` 经 `_p()` 输出，stdout 可被 `json.loads` 直接消费：

| 键 | 类型 | 含义 |
|----|------|------|
| `vela_version` | `str` | 包版本 |
| `python` | `str` | 解释器短版本 |
| `config_dir` | `str` | 配置目录绝对路径 |
| `config_hash` | `str` | 配置指纹（与推理侧一致） |
| `provider` | `str` | 解析后的 provider 名 |
| `probed` | `bool` | 本次是否实际调用了 `probe` |
| `dotenv` | `object` | `{path, loaded, keys, shadowed}`——只含键名，无值 |
| `checks` | `list[dict]` | `{name, ok, detail, kind, warn}`；掩码已在 detail 内 |
| `checks_passed` | `bool` | 全部 `ok` |
| `local_ok` | `bool` | 全部 `kind=="local"` 项 `ok` |

## Files Created/Modified

- `src/vela/cli.py` — `cmd_doctor` + doctor 三参数；辅助 `_doctor_item` / `_doctor_icon`
- `tests/test_doctor.py` — 八条回归护栏（118 行）

## Decisions Made

- 跳过网络时前三项记 warn 跳过；第 4 项「四个逻辑模型映射完整性」仍跑本地 `models_for`，以满足验收「输出含四个逻辑模型名」，且零网络成本。
- CLI 用 `hasattr(provider, "probe")` 判定，禁止 `import openai`（AGENTS.md 铁律 3）。

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 本地 `.env` 的 base_url 为 `/api/plan/v3` 导致接入 EnvChecker 后 doctor/既有用例 rc=1**
- **Found during:** Task 1（验收前探测）
- **Issue:** 真实 `.env` 含常见笔误，EnvChecker 正确判失败；与「mock 下 doctor rc=0」及 `test_cli_doctor_runs_and_reports_ok` 冲突
- **Fix:** 仅修正本地 `.env` 路径为 `/api/v3`（gitignored，未提交）；验证了 ENV-04 接线有效
- **Files modified:** `.env`（未入库）
- **Committed in:** n/a（环境侧）

**2. [Rule 2 - Critical] 跳过探测时仍保留第 4 项本地映射检查**
- **Found during:** Task 1（对照验收「四个逻辑模型名」）
- **Issue:** 计划字面「四项均记跳过」会使 mock 输出不含 `planner` 等模型名
- **Fix:** 前三项 warn 跳过；第 4 项始终本地 `models_for` 并展示链
- **Files modified:** `src/vela/cli.py`
- **Committed in:** `81baf2e`

---

**Total deviations:** 2 auto-fixed（Rule 3 ×1，Rule 2 ×1）
**Impact on plan:** 无范围膨胀；强化验收与 ENV-04 可观测性。

## Issues Encountered

None beyond the `.env` typo discovered during Task 1 verification.

## TDD Gate Compliance

Task 2 标注 `tdd="true"`，但实现已在同 plan Task 1 交付；护栏用例写入后即 GREEN，无独立 RED 失败提交。顺序符合本 plan「先呈现层、后护栏」编排，非跳过实现。

## Known Stubs

None.

## Threat Flags

None — 威胁面均在计划 `<threat_model>` 内（T-06-01~07），掩码同源与 `hasattr(probe)` 已落地。

## Self-Check: PASSED

- FOUND: `.planning/phases/01-llm/01-06-SUMMARY.md`
- FOUND: `src/vela/cli.py`（含 `--offline` / `EnvChecker` / `connectivity`）
- FOUND: `tests/test_doctor.py`（≥8 `test_`）
- FOUND: commit `81baf2e`
- FOUND: commit `00c5ead`
