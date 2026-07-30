---
phase: 01-llm
plan: 08
task: 1
recorded_at: "2026-07-30T23:50:00Z"
provider_override: mock
interpreter: .venv/bin/python3
status: PASSED
---

# 01-08 Task 1：一票否决回归门实测记录

> 本文件为 Task 1 可追溯凭据；完整 SUMMARY 待 Task 2 人工 `approved` 后写入。
> 全程 `VELA_LLM_PROVIDER=mock` shell 前置覆盖，未修改 `.env`。

## 基线对照（来自 01-BASELINE.md）

| 项 | 基线值 |
|---|---|
| baseline_pytest_passed | 177 |
| baseline_eval_exit_code | 0 |
| baseline_eval_correct_case_ids | S0..S9 共 10 条（全集） |

## 六项结果

### 1. 语法门 — PASS

- 命令：`PYTHON=.venv/bin/python3 make lint`
- 退出码：`0`
- 输出：`OK: 全部源文件语法通过`

### 2. 快速门 — PASS

- 命令：`VELA_LLM_PROVIDER=mock PYTHON=.venv/bin/python3 make test-fast`
- 退出码：`0`
- 输出：全部 `.` 通过（`tests/test_util.py` / `test_sim.py` / `test_gateway.py` / `test_obs_and_config.py`）

### 3. 全量测试门 — PASS

- 命令：`VELA_LLM_PROVIDER=mock PYTHON=.venv/bin/python3 make test`
- 退出码：`0`
- 实测：`211 passed, 2 deselected in 3.79s`
- 判定：`failed=0`；`passed=211 ≥ baseline 177`（严格大于，含 dotenv/envcheck/doctor/gateway/realllm 新增）；`deselected=2` 证明 `realllm` 默认排除、零付费调用

### 4. 仿真基准回归门 — PASS

- 命令：`VELA_LLM_PROVIDER=mock PYTHON=.venv/bin/python3 make eval`
- 退出码：`0`（与 baseline_eval_exit_code 一致）
- 核心指标：top1=1.0 / FPR=0.0 / dangling=0.0 / illegal_skill_reselect=0 / evidence_pack_verify=1.0
- 本次正确场景集合（口径同 BASELINE：故障 top1_hit；健康 pred∈{null,"","undetermined","no_fault_found"}）：

```
S0_HEALTHY
S1_DOWNLOAD_TIMEOUT
S2_SIGNATURE_FAIL
S3_UDS_NRC72
S4_POWER_DROP
S5_STORAGE_FULL
S6_ECU_SILENT
S7_DEP_MISMATCH
S8_ACTIVATE_ROLLBACK
S9_TIME_DRIFT
```

- **回归数 = |基线 − 本次| = 0**（本次 = 基线全集，无劣化）

### 5. 演示链路门 — PASS

- `VELA_LLM_PROVIDER=mock ./run_all.sh --skip-eval --skip-tests` → 退出码 `0`
  - 第 1 步 doctor 在 `set -euo pipefail` 下未中断；后续 build + diagnose 完成
- `VELA_LLM_PROVIDER=mock PYTHON=.venv/bin/python3 make demo` → 退出码 `0`
  - 仿真→建库→诊断→L0/L1/L2 全过；根因 `uds_nrc_programming_failure`

### 6. 凭证卫生门 — PASS

- `git ls-files | grep -c '^\.env$'` → `0`
- `git status --porcelain .env` → 空
- `.env` 被 `.gitignore` 忽略（本地存在但不入库）
- 对本阶段改动文件（不含 `.planning/` 计划原文）跑 `grep -nE 'sk-[A-Za-z0-9]{8}|ep-2[0-9]{7}'` → 无命中
  - 曾命中 `docs/LLM_PRODUCTION.md` 占位示例 `ep-20260101000000-xxxxx`（非真实凭证）；已改为 `ep-xxxx` 以与扫描模式区分

## 执行期偏差（Rule 3）

1. **`run_all.sh` 硬编码系统 `python3`**：doctor 报 duckdb/pyarrow「必需，缺失」并以退出码 1 中断链路。修复：优先 `PYTHON=` / `.venv/bin/python3` / `python3`。
2. **bash `set -u` + 全角逗号**：`$DATASET_DIR，` 被误解析为变量名。修复：改为 `${DATASET_DIR}`。
3. **文档占位符触发凭证扫描**：见上，改为 `ep-xxxx`。

## Task 2 状态

待人工按 `01-08-PLAN.md` `<how-to-verify>` 五步在真实火山引擎凭证下验收；**不可自动批准 / 不可由 agent 代跑付费 API**。
