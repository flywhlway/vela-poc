# Phase 2 回归门结果（02-GATE-RESULTS）

collected_at: 2026-07-31T16:00:00Z
interpreter: .venv/bin/python3

## make test

```text
PYTHON=.venv/bin/python3 make test
# 234 passed / 3 deselected (realllm) / failed: 0
```

- failed: 0
- collected: 234（默认排除 realllm）
- exit_code: 0

## make eval（mock）

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

## 付费基线命令块（Task 3）

```bash
# 指纹
PYTHONPATH=src VELA_CONFIG_DIR=config VELA_LLM_PROVIDER=volcengine \
  .venv/bin/python3 -m vela.cli doctor --json \
  > .planning/phases/02-metrics-baseline/baseline/doctor.json

# METR-09：无缓存 + N≥3
PYTHON=.venv/bin/python3 make baseline
# 等价：
# PYTHONPATH=src VELA_CONFIG_DIR=config VELA_LLM_PROVIDER=volcengine \
#   .venv/bin/python3 -m vela.cli eval run \
#   --dataset ./data/dataset --workspace ./workspace/baseline-eval \
#   --out .planning/phases/02-metrics-baseline/baseline \
#   --provider volcengine --no-cache --repeat 3 --reuse-workspace

# PERF-01（可选）
PYTHON=.venv/bin/python3 make bench-volc
```

## METR-09 / PERF-01 状态

- 凭证：`.env` 中 volcengine / ARK key / model 已配置（本文件不写值）
- 执行状态：见 Task 3 / SUMMARY（有凭证则跑盘；禁止伪造数字）
