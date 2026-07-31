---
phase: 01-llm
plan: 08
subsystem: verification
tags: [regression-gate, ENV-01, ENV-02, ENV-03, ENV-04, doctor, realllm, volcengine, D-12, D-14]

requires:
  - phase: 01-llm/01-01
    provides: 01-BASELINE.md（pytest/eval 基线与解释器约定）
  - phase: 01-llm/01-03
    provides: .env 导入期静默加载（ENV-01 实现主体）
  - phase: 01-llm/01-05
    provides: EnvChecker + mask_secret + env_checks.yaml
  - phase: 01-llm/01-06
    provides: doctor 四项连通性 / 退出码分层 / --json
  - phase: 01-llm/01-07
    provides: pytest -m realllm 端到端用例与生产文档命令
provides:
  - 一票否决回归门六项实测结论（可追溯）
  - 真实火山引擎五步实测人工 approved 结论（脱敏）
  - ENV-01/ENV-02/ENV-03/ENV-04 阶段验收闭环
affects: [Phase 2 真实环境评测入口, ROADMAP Phase 1 完成]

tech-stack:
  added: []
  patterns:
    - "回归门全程 VELA_LLM_PROVIDER=mock shell 覆盖，勿改 .env"
    - "仿真回归数 = |基线正确集合 − 本次正确集合|，阈值为 0"
    - "方舟 BASE_URL 合法路径含 /api/v3 与 /api/plan/v3；坏例用 /api/v2"

key-files:
  created:
    - .planning/phases/01-llm/01-08-GATE-RESULTS.md
  modified:
    - run_all.sh
    - config/env_checks.yaml
    - docs/LLM_PRODUCTION.md
    - .env.example
    - tests/test_doctor.py
    - tests/test_envcheck.py
    - tests/test_realllm.py

key-decisions:
  - "方舟 BASE_URL 同时接受 /api/v3 与 /api/plan/v3；形态坏例改用 /api/v2（不再把 /api/plan/v3 当坏例）"
  - "realllm doctor 连通性断言收紧为四项全绿；diagnose 保留引用断言"
  - "ENV 四条需求在本 plan 实测后统一勾选完成"

patterns-established:
  - "Pattern: 回归门结果先落 GATE-RESULTS.md，Task 2 approved 后再写入 SUMMARY"
  - "Pattern: 付费实测仅人工触发；SUMMARY 只记脱敏结论与退出码"

requirements-completed: [ENV-01, ENV-02, ENV-03, ENV-04]

duration: continuation
completed: 2026-07-31
---

# Phase 1 Plan 8: 一票否决回归门与真实环境实测 Summary

**mock 下六项回归门全过（211 passed / eval 回归数 0 / demo 与 run_all 不中断），真实火山引擎五步实测经人工 approved：doctor 连通性四项全绿、形态坏例 EXIT=1、`pytest -m realllm` 2 passed、`.env` 未追踪。**

## Performance

- **Duration:** continuation（Task 1 于 2026-07-30；Task 2 人工验收后于 2026-07-31 收尾）
- **Started:** 2026-07-30T23:50:00Z（Task 1 记录起点）
- **Completed:** 2026-07-31
- **Tasks:** 2/2
- **Files modified:** 见下方（本 plan 以验证为主；Task 1/2 期间有必要修复提交）

## Accomplishments

- 一票否决回归门六项全部 PASS，数值与基线对比已落盘（见 `01-08-GATE-RESULTS.md`）
- 真实火山引擎五步实测经人工 `approved`，ROADMAP 四条成功判据闭环
- ENV-01/ENV-02/ENV-03/ENV-04 在本 plan 完成勾选
- 版本库无 `.env`、无真实凭证形态残留

## Task Commits

1. **Task 1: 一票否决回归门（六项）** - `7fc9740` (fix) + 结果文件 `01-08-GATE-RESULTS.md`
2. **Task 2: ENV-02/ENV-03 真实火山引擎实测验收** - 人工 `approved`；配套修复 `21fddb9` (fix)

**Plan metadata:** `9d2054e` (docs: complete plan；STATE/ROADMAP 收尾另提交)

## Task 1 — 六项回归门（mock）

全程 `VELA_LLM_PROVIDER=mock` shell 前置覆盖，未修改 `.env`。解释器：`.venv/bin/python3`。

| # | 门 | 命令要点 | 结果 |
|---|---|---|---|
| 1 | 语法 | `make lint` | EXIT=0 |
| 2 | 快速 | `make test-fast` | EXIT=0 |
| 3 | 全量测试 | `make test` | EXIT=0；`211 passed, 2 deselected`；failed=0；passed ≥ 基线 177；`deselected` 证明 realllm 默认排除 |
| 4 | 仿真基准回归 | `make eval` | EXIT=0；正确场景 = 基线 S0..S9 全集；**回归数 = 0**；top1=1.0 / FPR=0.0 / dangling=0.0 |
| 5 | 演示链路 | `./run_all.sh --skip-eval --skip-tests` + `make demo` | 二者 EXIT=0；doctor 在 `set -euo pipefail` 下未中断 |
| 6 | 凭证卫生 | `git ls-files` / `git status` / 凭证形态扫描 | `.env` 未追踪；改动文件无真实 `sk-` / `ep-2…` 命中 |

详细命令与数值见 [01-08-GATE-RESULTS.md](./01-08-GATE-RESULTS.md)。

## Task 2 — 真实火山引擎五步实测（人工 approved）

前置：`.env` 已配置方舟凭证；`VELA_LLM_PROVIDER=volcengine`；`VELA_ARK_BASE_URL` 使用合法路径 `/api/plan/v3`。全程无手工 `export`（ENV-01）。**以下不含任何真实 API key / 完整密钥。**

| Step | 验收点 | 结论 |
|------|--------|------|
| 1 | doctor 人读 | EXIT=0；`.env` 命中；连通性四项全绿；API key 为前 4 后 4 掩码；`base_url` / 接入点 ID 明文可见 |
| 2 | doctor `--json` | EXIT=0；`local_ok=true`；纯 JSON；掩码与人读一致；连通性四项全绿 |
| 3 | 形态错误路径 | 临时改用非法路径 `/api/v2`（**不再**用 `/api/plan/v3` 作坏例）；EXIT=1；提示双合法路径（`/api/v3` 与 `/api/plan/v3`）；确认后改回 |
| 4 | `pytest -m realllm` | **2 passed**（含 diagnose 引用断言与收紧后的 doctor 连通性断言）；非 skipped |
| 5 | 凭证卫生终检 | `.env` 未追踪；实测 workspace / 审计日志未入库 |

**人工信号：** `approved`（2026-07-31）。

### ROADMAP 四条成功判据对照

| # | 判据 | 确认 |
|---|------|------|
| 1 | 不手工 export，仅凭 `.env` 读到凭证与 base_url | ✅ Step1/2（ENV-01） |
| 2 | volcengine 下 diagnose 端到端产出含 `[[EV:row_hash]]` 的报告 | ✅ Step4（ENV-02） |
| 3 | doctor 四项连通性自检一次给出结论 | ✅ Step1/2（ENV-03） |
| 4 | doctor 识别 base_url 路径异常；`.env.example` 无行尾注释污染 | ✅ Step3 + Plan 05（ENV-04） |

## Decisions Made

- 方舟 BASE_URL 形态规则放宽为同时接受 `/api/v3` 与 `/api/plan/v3`；错误路径验收改用 `/api/v2`
- realllm 中 doctor 连通性断言收紧为四项全绿，与真实验收口径对齐
- ENV 四条需求的 REQUIREMENTS 勾选统一在本 plan 收尾完成（ENV-02/03/04 此前已勾选；ENV-01 本 plan 勾选）

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] run_all.sh 解释器与 set -u 问题**
- **Found during:** Task 1（演示链路门）
- **Issue:** 硬编码系统 `python3` 缺 duckdb/pyarrow；全角逗号触发 `set -u` 误解析
- **Fix:** 优先 `PYTHON=` / `.venv/bin/python3`；修正变量展开
- **Files modified:** `run_all.sh`
- **Verification:** `./run_all.sh --skip-eval --skip-tests` EXIT=0
- **Committed in:** `7fc9740`

**2. [Rule 3 - Blocking] 文档占位符触发凭证扫描**
- **Found during:** Task 1（凭证卫生门）
- **Issue:** `docs/LLM_PRODUCTION.md` 示例 `ep-20260101000000-xxxxx` 命中扫描模式
- **Fix:** 改为 `ep-xxxx`
- **Files modified:** `docs/LLM_PRODUCTION.md`
- **Verification:** 凭证形态扫描无命中
- **Committed in:** `7fc9740`

**3. [Rule 1 - Bug] 方舟 BASE_URL 形态规则与真实路径不符**
- **Found during:** Task 2 人工实测（Step3 原计划以 `/api/plan/v3` 为坏例）
- **Issue:** 生产常用 `/api/plan/v3` 被误判为形态错误；与真实环境冲突
- **Fix:** 放宽规则接受双合法路径；坏例改为 `/api/v2`；收紧 realllm doctor 连通性断言
- **Files modified:** `config/env_checks.yaml`, `docs/LLM_PRODUCTION.md`, `.env.example`, `tests/test_doctor.py`, `tests/test_envcheck.py`, `tests/test_realllm.py`
- **Verification:** Step3 EXIT=1 + 双合法路径提示；Step4 `2 passed`
- **Committed in:** `21fddb9`

---

**Total deviations:** 3 auto-fixed（2× Rule 3，1× Rule 1）
**Impact on plan:** 均为正确性/可验收修复；未扩大功能范围。

## Issues Encountered

- Task 2 原 how-to-verify 将 `/api/plan/v3` 列为坏例，与方舟生产路径冲突；已通过 `21fddb9` 修正规则与文档，人工按新坏例 `/api/v2` 复验后 approved。

## User Setup Required

真实火山引擎实测需本地 `.env`（勿提交）：`VELA_ARK_API_KEY`、`VELA_ARK_MODEL`、`VELA_ARK_BASE_URL`、`VELA_LLM_PROVIDER=volcengine`。日常回归保持 mock。

## Next Phase Readiness

- Phase 1 ENV 四条需求全部闭环；回归门与真实连通性已核验
- 可进入 Phase 2（度量可信与真实基线）；后续真实评测沿用 `.env` 自动加载 + `pytest -m realllm` / doctor 入口
- 无阻塞项

## Self-Check: PASSED

- FOUND: `.planning/phases/01-llm/01-08-SUMMARY.md`
- FOUND: `.planning/phases/01-llm/01-08-GATE-RESULTS.md`
- FOUND: commit `7fc9740` (Task 1)
- FOUND: commit `21fddb9` (Task 2 配套修复)
- FOUND: commit `9d2054e` (SUMMARY)
- FOUND: ROADMAP Phase 1 plans 8/8 Complete；ENV-01..04 均已勾选
- FOUND: `.env` 未追踪（`git ls-files | grep -c '^\.env$'` = 0）

---
*Phase: 01-llm*
*Completed: 2026-07-31*
