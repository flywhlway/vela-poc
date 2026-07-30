---
phase: 01-llm
plan: 07
subsystem: testing-docs
tags: [realllm, ENV-02, D-19, pytest, LLM_PRODUCTION, doctor, citations]

requires:
  - phase: 01-llm/01-04
    provides: openai SDK 化后的 volcengine 传输层与 CITE_RX 权威引用格式
  - phase: 01-llm/01-06
    provides: doctor --json 顶层键与退出码分层语义
provides:
  - tests/test_realllm.py（ENV-02 可复现验收；默认排除）
  - docs/LLM_PRODUCTION.md 与 .env 自动加载 / SDK 化 / doctor 对齐
affects: [01-llm/01-08, Phase 2 真实环境冒烟入口]

tech-stack:
  added: []
  patterns:
    - "realllm 用例 monkeypatch.setenv 回 volcengine（D-11 逃生）"
    - "缺凭证 pytest.skip；断言只覆盖链路通/报告非空/CITE_RX"
    - "报告文本取自 workspace/sessions/<id>.state.json 的 report_md"

key-files:
  created:
    - tests/test_realllm.py
  modified:
    - docs/LLM_PRODUCTION.md

key-decisions:
  - "rc∈{0,3} 均视为链路走完；不把 rc==0 作硬断言（D-19）"
  - "可选 doctor 连通性用例一并固化，供 ENV-03 真实验收复用"
  - "文档 retry_backoff_s 仅保留「已删除」语境一行"

patterns-established:
  - "Pattern: 付费用例模块级 pytestmark=realllm + autouse 凭证守卫"
  - "Pattern: 报告落盘路径以 CheckpointStore(ws/sessions) 为准，capsys 仅兜底"

requirements-completed: [ENV-02]

duration: 3min
completed: 2026-07-30
---

# Phase 1 Plan 7: realllm 验收用例与生产文档对齐 Summary

**新增 `pytest.mark.realllm` 端到端用例固化 ENV-02（默认排除、缺凭证 skip、断言链路通+报告非空+`CITE_RX`），并同步 `docs/LLM_PRODUCTION.md` 去掉 `source .env` / 死键口径、补齐 doctor 与 realllm 两节。**

## Performance

- **Duration:** 3min
- **Started:** 2026-07-30T23:38:30Z
- **Completed:** 2026-07-30T23:41:11Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- `tests/test_realllm.py`：diagnose 端到端 + 可选 doctor `--json` 连通性用例
- 默认 pytest：`211 passed, 2 deselected`；`-m realllm` 可收集 2 条；无凭证 → 2 skipped
- `docs/LLM_PRODUCTION.md`：自动加载 / SDK 映射 / doctor 退出码 / `pytest -m realllm` 命令齐全

## Task Commits

1. **Task 1: 新建 tests/test_realllm.py 端到端验收用例** - `5b73d6e` (test)
2. **Task 2: 对齐 docs/LLM_PRODUCTION.md** - `85b9b31` (docs)

**Plan metadata:** （本提交）

## 供 Plan 08 实测 checkpoint：完整运行命令

```bash
PYTHONPATH=src VELA_CONFIG_DIR=config \
  VELA_LLM_PROVIDER=volcengine \
  .venv/bin/python3 -m pytest -m realllm -q
```

前置：项目根 `.env` 已配置非空的 `VELA_ARK_API_KEY` 与 `VELA_ARK_MODEL`（由 `config.py` 自动加载，无需 `source`）。会产生真实付费 API 调用。

收集确认（不执行）：

```bash
PYTHONPATH=src VELA_CONFIG_DIR=config \
  .venv/bin/python3 -m pytest -m realllm --collect-only -q
```

## Files Created/Modified

- `tests/test_realllm.py` — ENV-02 realllm 用例（77 行）；复用 `CITE_RX`；报告读 `sessions/*.state.json`
- `docs/LLM_PRODUCTION.md` — 删除 `source .env`；SDK/doctor/realllm 三节对齐

## Decisions Made

- 诊断返回码接受 `0`（answered）或 `3`（未作答但链路走完），符合 D-19「不因环境问题中途报错」
- 报告优先读 CheckpointStore 落盘的 `report_md`，stdout 仅作空报告兜底；禁止把 capsys 写入持久化文件
- 文档中 `retry_backoff_s` 仅出现一次且为「已删除」说明，满足 acceptance `≤ 1`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] 验收命令重复 `-q` 导致 `-qq` 吞掉 deselected 摘要**
- **Found during:** Task 1 验收
- **Issue:** `addopts` 已含 `-q`，plan verify 再传 `-q` 变成 `-qq`，摘要行不打印 `deselected`，字面 `grep -q deselected` 失败
- **Fix:** 验收改用不重复 `-q` 的调用（`pytest tests/` 依赖 addopts 自带 `-q`）；测试本身无需改动
- **Files modified:** 无（仅执行侧）
- **Verification:** `pytest tests/` → `211 passed, 2 deselected`
- **Committed in:** N/A（无代码变更）

---

**Total deviations:** 1 auto-fixed（Rule 3）
**Impact on plan:** 不影响交付物；Plan 08 跑命令时注意勿叠两个 `-q`。

## TDD Gate Compliance

Task 1 标 `tdd="true"`，交付物即测试文件本身（无独立 production GREEN 代码）。采用单次 `test(01-07)` 提交；行为由「默认 deselected / 显式可收集 / 无凭证 skipped」三条自动化路径验证。无单独 RED 失败提交——既有 diagnose/doctor 路径已存在，用例是验收护栏而非新功能实现。

## Issues Encountered

None beyond the `-qq` verify quirk above.

## User Setup Required

真实付费跑通需 `.env` 中有效火山引擎凭证（Plan 08 人工验收）。本 plan 不提交 `.env`。

## Next Phase Readiness

- Plan 08 可直接复制上文「完整运行命令」做 checkpoint 实测
- ENV-02 用例与文档已就位；REQUIREMENTS 勾选随 roadmap/requirements 更新

## Self-Check: PASSED

- FOUND: `tests/test_realllm.py`
- FOUND: `docs/LLM_PRODUCTION.md`
- FOUND: commit `5b73d6e`
- FOUND: commit `85b9b31`

---
*Phase: 01-llm*
*Completed: 2026-07-30*
