---
baseline_interpreter: "/Users/flywhl/dev/work/vela-poc/.venv/bin/python3 (Python 3.12.13)"
baseline_pytest_passed: 177
baseline_pytest_failed: 0
baseline_pytest_skipped: 0
baseline_pytest_exit_code: 0
baseline_eval_exit_code: 0
baseline_eval_correct_case_ids:
  - S0_HEALTHY
  - S1_DOWNLOAD_TIMEOUT
  - S2_SIGNATURE_FAIL
  - S3_UDS_NRC72
  - S4_POWER_DROP
  - S5_STORAGE_FULL
  - S6_ECU_SILENT
  - S7_DEP_MISMATCH
  - S8_ACTIVATE_ROLLBACK
  - S9_TIME_DRIFT
collected_at: "2026-07-30T18:13Z"
collector: "gsd-executor (01-01 Task 1)"
---

# Phase 1 改动前 mock 回归基线（01-BASELINE）

本文件采集于 **Phase 1 任何源码改动之前**（01-02 仅改写规划/约定文档，未触碰 `src/`、`tests/`、`config/`），
是 ROADMAP Phase 1 回归门「177 测试全过 + 仿真基准已通过用例回归数 = 0」的事实依据。
Plan 08 只判断相对本基线是否**劣化**，不要求绝对指标改善。

⚠️ 本文件只记录命令、数量与场景 ID，**不含任何环境变量值或凭证**。

## 1. baseline_interpreter —— 解释器与依赖版本

| 项 | 值 |
|---|---|
| 解释器 | `/Users/flywhl/dev/work/vela-poc/.venv/bin/python3`（pyenv 实体：`3.12.13`） |
| `python3 --version` | Python 3.12.13 |
| duckdb | 1.5.5 |
| pyarrow | 25.0.0 |
| PyYAML | 6.0.3 |
| pytz | 2026.3.post1 |
| pytest | 9.1.1 |

建立方式：`make install-dev`（建 `.venv` + `requirements.txt` + `requirements-optional.txt` + `pip install -e .`）。

**调用约定（后续所有 Plan 沿用）**：本仓库 `Makefile` 的 `PYTHON ?= python3` 默认指向系统解释器，
缺少 duckdb/pyarrow。因此——

- make 目标一律 `PYTHON=.venv/bin/python3 make <target>`；
- 直接调 pytest 一律 `PYTHONPATH=src VELA_CONFIG_DIR=config .venv/bin/python3 -m pytest ...`。

## 2. baseline_pytest —— 全量测试基线

命令：`PYTHON=.venv/bin/python3 make test`
（等价 `PYTHONPATH=src VELA_CONFIG_DIR=config .venv/bin/python3 -m pytest tests/ -q`）

| 项 | 值 |
|---|---|
| 收集用例数 | 177 |
| **passed** | **177** |
| failed | 0 |
| skipped | 0 |
| 退出码 | 0 |

与 ROADMAP 记载的期望值「177 全过」一致。

## 3. baseline_eval —— 黄金评测基线（provider = mock）

命令：`PYTHON=.venv/bin/python3 make eval`（先跑 `make sim` 生成 10 场景数据集，再 `eval run`）。
产物：`workspace/eval/report/eval_report.md` 与 `workspace/eval/report/eval_result.json`。

| 项 | 值 |
|---|---|
| **退出码** | **0**（四项门全过） |
| top1_root_cause_accuracy | 1.0（门：≥ 0.8 ✅） |
| false_positive_rate | 0.0（门：≤ 0.0 ✅） |
| dangling_citation_rate | 0.0（门：≤ 0.015 ✅） |
| illegal_skill_reselect_total | 0（门：≤ 0 ✅） |
| healthy_specificity | 1.0 |
| evidence_pack_verify_pass | 1.0 |
| fail_phase_accuracy | 0.8889（S1 阶段未命中；非回归门指标，仅如实记录） |
| 用例总数 | 10（故障 9 / 健康 1） |

### baseline_eval_correct_case_ids（「仿真基准已通过用例」集合）

判定口径（Plan 08 复算时必须使用同一口径，与 `eval/report.py` 逐用例明细表一致）：

- 故障用例（`healthy == false`）：`top1_hit == true`
- 健康用例（`healthy == true`）：`predicted_label ∈ {null, "", "undetermined", "no_fault_found"}`

数据源：`eval_result.json` 的 `cases[*].top1_hit / .healthy / .predicted_label` 字段。

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

共 **10** 条（当前全部用例均通过，回归数 = 集合差「基线通过而当前不通过」的条目数，一票否决阈值为 0）。

## 备注

- `make eval` 总耗时约 18.4 s（mock provider，单机）。
- 本基线由仿真数据集产出，只有回归价值、无真实能力度量价值（ADR-3：仿真 = 回归门，真实 = 能力门）。
