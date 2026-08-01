---
phase: 02-metrics-baseline
collected_at: "2026-08-01T05:30:00Z"
pytest_failed: 0
pytest_passed: 234
eval_exit_code: 0
regression_count: 0
gate_status: PASSED
provider: mock
root_cause_note: "先前 FAILED 实为 make eval 未钉死 --provider mock，误用 .env 的 volcengine"
METR-09: pending
PERF-01: pending
---

# Phase 2 回归门结果（02-GATE-RESULTS）

⚠️ 本文件只记录命令、数量与场景 ID，**不含任何环境变量值或凭证**。

## 0. 根因备忘（先前假失败）

| 项 | 说明 |
|---|---|
| 现象 | 干净 `make eval` 耗时 ~9min、top1≈0.44、回归 5 例；诊断秒级 20–100s |
| 根因 | `Makefile` 的 `eval` 目标未传 `--provider mock`；`.env` 中 `VELA_LLM_PROVIDER=volcengine` 被 `config.py` 导入加载 → `build_gateway(None)` 走真实 API |
| 对照 | 显式 `provider=mock` 时 10/10、诊断 ~0.1s、`regression_count=0` |
| 修复 | `make eval` 增加 `--provider mock`（与 `eval-repeat` 对齐）；付费路径仍仅 `make baseline` / `bench-volc` |

## 1. `make test`

```bash
PYTHON=.venv/bin/python3 make test
```

| 项 | 值 |
|---|---|
| exit | 0 |
| failed | **0** |
| passed | 234（默认 `not realllm`） |

## 2. `make eval`（mock 回归门，修复后）

```bash
rm -rf workspace/eval
PYTHONHASHSEED=0 PYTHON=.venv/bin/python3 make eval
```

| 项 | 值 |
|---|---|
| exit | **0** |
| provider | mock |
| top1_root_cause_accuracy | 1.0 |
| false_positive_rate | 0.0 |
| dangling_citation_rate | 0.0 |
| illegal_skill_reselect_total | 0 |
| regression_count | **0** |

### 正确场景集合（与 `01-BASELINE.md` 一致）

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

## 3. 待执行的付费基线命令（Task 3）

回归门已通过。凭据可用时可执行：

```bash
PYTHON=.venv/bin/python3 make doctor
PYTHON=.venv/bin/python3 make baseline
# 可选：make bench-volc
```

**METR-09 / PERF-01**：待 `baseline/report.md` + `result.json` 落盘后勾选 done；禁止伪造数字。
