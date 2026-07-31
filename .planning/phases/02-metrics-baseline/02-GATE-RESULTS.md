# Phase 2 回归门结果（02-GATE-RESULTS）

collected_at: 2026-08-01T00:30:00Z
interpreter: .venv/bin/python3

## make test

```text
PYTHON=.venv/bin/python3 make test
```

- failed: 0
- collected: 234（默认排除 3 个 realllm）
- exit_code: 0

## make eval（mock）— 权威记录

```text
PYTHONPATH=src VELA_CONFIG_DIR=config VELA_LLM_PROVIDER=mock \
  .venv/bin/python3 -m vela.cli eval run \
  --dataset ./data/dataset --workspace ./workspace/eval \
  --out ./workspace/eval/report --provider mock --reuse-workspace
```

- eval_exit_code: 0
- top1_root_cause_accuracy: 1.0
- false_positive_rate: 0.0
- dangling_citation_rate: 0.0
- illegal_skill_reselect_total: 0

### baseline_eval_correct_case_ids（本次）

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

对比 `.planning/phases/01-llm/01-BASELINE.md`：

- regression_count: 0
- lost_ids: []

> 注：曾有并行会话在干净 workspace 上记录过 regression_count=5；以本文件本次复跑（exit=0、10/10 top1）为准。

## 付费基线（Task 3）

```text
VELA_LLM_PROVIDER=volcengine ... eval run --no-cache --repeat 3 --reuse-workspace \
  --out .planning/phases/02-metrics-baseline/baseline
```

- METR-09: **done**
- PERF-01: **done**（`result.json` meta.perf：diagnose P50/P95）
- N: 3；provider: volcengine；no_cache: true
- top1 mean ≈ 0.5185；95% CI ≈ [0.20, 0.84]
- NR-1：`baseline/report.md` 已声明禁止再引用 44.4%
- 产物：`baseline/report.md`、`baseline/result.json`、`baseline/doctor.json`
- 无 API key 明文
