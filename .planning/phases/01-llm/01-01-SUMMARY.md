---
phase: 01-llm
plan: 01
subsystem: infra
tags: [baseline, python-dotenv, openai, pytest-markers, realllm, supply-chain, d-03, d-19]

requires:
  - phase: 01-llm 讨论阶段（01-CONTEXT.md）
    provides: D-03 必需依赖（python-dotenv / openai）、D-19 realllm 默认排除、回归门口径
provides:
  - 改动前 mock 回归基线（177 passed + 10 场景正确 ID 集合）供 Plan 08 判定「回归数 = 0」
  - requirements.txt / pyproject.toml 中 python-dotenv>=1.0 与 openai>=1.40 必需依赖声明
  - pytest `realllm` 标记注册与 addopts 默认 `-m 'not realllm'`
  - 后续 Plan 统一解释器约定：`PYTHON=.venv/bin/python3`
affects: [01-03, 01-04, 01-07, 01-08]

tech-stack:
  added: [python-dotenv>=1.0, openai>=1.40]
  patterns:
    - "必需依赖双清单一致（requirements.txt + pyproject.toml [project] dependencies）"
    - "pytest 付费用例默认排除：addopts 含 -m 'not realllm'，显式 -m realllm 覆盖"

key-files:
  created:
    - .planning/phases/01-llm/01-BASELINE.md
  modified:
    - requirements.txt
    - pyproject.toml

key-decisions:
  - "解释器约定：make install-dev 装进 .venv；所有 make/pytest 用 PYTHON=.venv/bin/python3（或直接调 .venv/bin/python3 -m pytest）"
  - "python-dotenv / openai 写入必需依赖组，禁止 try-import 降级（D-03）；不进 requirements-optional.txt"
  - "ENV-01 / ENV-02 本 plan 仅交付依赖与基线基座；完成勾选留给后续 plan / Plan 08 实测验收（与 01-02 决策一致）"

patterns-established:
  - "Phase 1 起所有验证命令前缀 PYTHON=.venv/bin/python3"
  - "供应链闸门：ASSUMED 新 pip 包必须 checkpoint:human-verify gate=blocking-human 放行后才可写入依赖清单"

requirements-completed: []  # ENV-01/ENV-02 为多 plan 共同交付；本 plan 仅依赖与基线基座

duration: 跨会话（Task1 基线采集 + 续跑约 1min）
completed: 2026-07-31
---

# Phase 1 Plan 1: mock 回归基线 + 必需依赖与 realllm 默认排除 Summary

**落盘改动前 mock 基线（177 测试全过、黄金评测 10/10），人工核验放行后将 `python-dotenv`/`openai` 写入必需依赖，并注册 pytest `realllm` 标记默认排除，保证 `make test` 不会误打付费 API。**

## Performance

- **Duration:** 跨会话（Task 1 基线采集含 `make eval`；续跑 Task 3 约 1 min）
- **Started (续跑):** 2026-07-30T23:16:32Z
- **Completed:** 2026-07-30T23:17:28Z
- **Tasks:** 3 / 3
- **Files modified:** 3（含新建基线文件）

## Accomplishments

- 在任何源码改动前采集三项基线并写入 `01-BASELINE.md`：解释器/依赖版本、pytest 177 passed、eval 退出码 0 且正确场景 ID 全集（S0–S9）
- Task 2 供应链闸门：`python-dotenv` 与 `openai` 经人工在 pypi.org 核验后回复 `approved` 放行（`gate=blocking-human`，不可自动批准）
- 两处必需依赖清单一致声明；`realllm` 标记注册且 `addopts` 含 `-m 'not realllm'`；`.venv` 内 `import dotenv, openai` 成功；全量 pytest 仍 177 passed；`make test-fast` 通过

## 基线三项数值（供 Plan 08）

| 键 | 值 |
|---|---|
| `baseline_pytest_passed` | 177 |
| `baseline_eval_exit_code` | 0 |
| `baseline_eval_correct_case_ids` | S0_HEALTHY … S9_TIME_DRIFT（10 个） |

## 解释器约定（后续 Plan 全部沿用）

```bash
make install-dev                                    # 建 .venv + 可编辑安装
PYTHON=.venv/bin/python3 make <target>              # 所有 make 目标
PYTHONPATH=src VELA_CONFIG_DIR=config \
  .venv/bin/python3 -m pytest ...                   # 直接调 pytest
```

本机实测：`.venv/bin/python3` → Python 3.12.13；安装后 `python-dotenv==1.2.2`、`openai==2.51.0`。

## Task Commits

Each task was committed atomically:

1. **Task 1: 采集改动前的 mock 回归基线** - `18618c0` (chore)
2. **Task 2: 新增 pip 包合法性人工核验** - 无代码提交（checkpoint:human-verify）；用户回复 `approved` 放行
3. **Task 3: 写入必需依赖并建立 realllm 标记默认排除** - `447f055` (chore)

**Plan metadata:** 见文末最终提交（docs: complete plan）

## Files Created/Modified

- `.planning/phases/01-llm/01-BASELINE.md` - 改动前 mock/eval 基线（含 front-matter 四键，无凭证）
- `requirements.txt` - 追加 `python-dotenv>=1.0`、`openai>=1.40`（行尾中文注释说明为何必需）
- `pyproject.toml` - `[project] dependencies` 同步追加；`markers` 注册 `realllm`；`addopts` 改为含 `-m 'not realllm'`

## Decisions Made

- 后续 Plan 一律用 `PYTHON=.venv/bin/python3`，避免系统 python3 缺 duckdb/pyarrow
- D-03：两包为必需依赖，禁止 try-import 降级，禁止写入 optional
- D-19：默认排除 realllm；命令行显式 `-m realllm` 覆盖 addopts（pytest 单值 `-m` 语义）
- ENV-01/ENV-02 不在本 plan 勾选完成（与 01-02 决策一致）

## Auth Gates / Human Checkpoints

| Task | Type | Outcome |
|------|------|---------|
| Task 2 | checkpoint:human-verify（gate=blocking-human） | 用户 `approved`：python-dotenv（theskumar）与 openai（OpenAI 官方）合法性放行 |

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None

## User Setup Required

None - 依赖已写入清单并在 `.venv` 安装；真实 LLM 密钥配置属后续 Plan（ENV / doctor）。

## Next Phase Readiness

- Plan 03 可安全 `import dotenv` 实现 `.env` 加载
- Plan 04 可安全 `import openai` 重写 provider
- Plan 07 可按 `realllm` 标记编写付费用例且默认不被 `make test` 收集
- Plan 08 可用 `01-BASELINE.md` 的正确场景 ID 集合判定回归数

## Self-Check: PASSED

- FOUND: `.planning/phases/01-llm/01-BASELINE.md`
- FOUND: `requirements.txt` / `pyproject.toml` 含 python-dotenv 与 openai
- FOUND: commit `18618c0`（Task 1）
- FOUND: commit `447f055`（Task 3）
- VERIFIED: `make test-fast` exit 0；全量 pytest 177 passed

---
*Phase: 01-llm*
*Completed: 2026-07-31*
