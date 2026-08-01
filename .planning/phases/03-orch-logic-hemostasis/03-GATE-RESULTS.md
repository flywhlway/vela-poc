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

## 7. ORCH-01..10 核对表（Task 2，回归门通过后）

REQUIREMENTS.md 中 ORCH-01..ORCH-10 在本 gate 实测通过后确认为全部 `[x]`（先落盘本文件再勾选/核对，禁止预勾）。

| ORCH | `-k` 覆盖（无 xfail） | 关键事件 / 路径 |
|------|----------------------|----------------|
| ORCH-01 | `stop_rejected` | `plan.stop_rejected` → `graph.py` |
| ORCH-02 | `planner_system` | `PLANNER_SYSTEM` 提示词（gateway/prompts） |
| ORCH-03 | `parse_json` | `llm.parse_failure` → `graph.py` / `process.py` |
| ORCH-04 | `max_tokens` / `truncation` | `llm.truncation` → `graph.py` / `process.py` |
| ORCH-05 | `verdict_norm` | verifier 枚举归一化 |
| ORCH-06 | `verify_claim_hypothesis` | claim=根因假设 |
| ORCH-07 | `excluded_skills` / `probe_dedup` | unproductive-only + 探针去重 |
| ORCH-08 | `insufficient_citation` | `min_citation_ratio` 闸门 |
| ORCH-09 | `unexplained_sweep` / process metrics | `coverage.unexplained_errors` → `graph.py` |
| ORCH-10 | `generic_fallback` / `skill_registry` | `SK-GENERIC-EVIDENCE-FIRST` A1 注入 |

校验：

```bash
rg -n '\[ \] \*\*ORCH-' .planning/REQUIREMENTS.md   # 命中 0
rg -n '\[x\] \*\*ORCH-' .planning/REQUIREMENTS.md   # 命中 10
rg -n 'xfail.*ORCH|ORCH pending' tests/test_agent.py tests/test_gateway.py tests/test_eval.py  # 命中 0
```

实测：未勾选 ORCH = 0；已勾选 ORCH = 10；无残留 `xfail.*ORCH` / `ORCH pending`（仅历史注释标题「Wave 0 skeletons (xfail)」，无 `@pytest.mark.xfail`）。
