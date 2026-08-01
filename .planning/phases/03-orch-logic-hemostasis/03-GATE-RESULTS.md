---
phase: 03-orch-logic-hemostasis
plan: 07
collected_at: "2026-08-01T06:21:00Z"
pytest_failed: 0
pytest_passed: 247
pytest_deselected: 3
eval_exit_code: 0
regression_count: 0
gate_status: PASSED
provider: mock
---

# Phase 3 回归门结果（03-GATE-RESULTS）

⚠️ 本文件只记录命令、数量与场景 ID，**不含任何环境变量值或凭证**。

过程指标对照 Phase 2 基线方法论（真实事件优先聚合）；**不**以历史百分比作为本阶段效果锚。

## 1. `make test`

```bash
PYTHON=.venv/bin/python3 make test
```

| 项 | 值 |
|---|---|
| exit | **0** |
| failed | **0** |
| passed | **247**（默认 `not realllm`，deselected=3） |
| wall-clock | ~4.4–6.5 s（本机） |

## 2. Dataset

`data/dataset` 已存在；`make eval` 依赖的 `sim` 目标重新生成 10 场景（226,905 行）。

## 3. `make eval`（mock 回归门）

```bash
rm -rf workspace/eval
PYTHONHASHSEED=0 PYTHON=.venv/bin/python3 make eval
```

| 项 | 值 |
|---|---|
| exit | **0** |
| provider | mock |
| cases_total | 10 |
| top1_root_cause_accuracy | 1.0 |
| healthy_specificity | 1.0 |
| false_positive_rate | 0.0 |
| dangling_citation_rate | 0.0 |
| illegal_skill_reselect_total | 0 |
| premature_stop_rate | 0.0 |
| llm_parse_failure_rate | 0.0 |
| llm_truncation_rate | 0.0 |
| verdict_supported_ratio | 1.0 |
| **regression_count** | **0**（已通过用例回归数 = 0，一票否决项通过） |
| wall-clock | ~19.9 s（real） |

### 正确场景集合（与 Phase 1/2 mock 基线一致，无回归）

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

判定口径：故障例 `top1_hit=true`；健康例 `predicted_label=no_fault_found` 且 `healthy_specificity=1.0`。相对既有已通过全集差集为空 → **regression = 0**。

报告路径（本地产物，不入仓）：`workspace/eval/report/eval_report.md`、`eval_result.json`。

## 4. Gate 合计耗时（Nyquist）

| 步骤 | wall-clock |
|---|---|
| `make test` | ≤7 s |
| `make eval`（含 sim regenerate） | ≈20 s |
| **合计** | **≈25–30 s**（>30s 阈值边缘；全量门仍强制执行） |

波次内日常反馈继续用 `-k` 单测 + `make test-fast`（≤120s）。

## 5. 可选真实 LLM 抽检

未执行（非阻断；需付费凭证）。失败不否决 mock 合入。

## 6. 结论（Task 1）

**gate_status: PASSED** — `make test` 全绿 + mock `make eval` regression = 0 → 允许进入 Task 2 勾选 ORCH-01..ORCH-10。
