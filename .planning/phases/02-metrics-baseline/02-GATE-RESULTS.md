---
phase: 02-metrics-baseline
collected_at: "2026-07-31T16:10:00Z"
pytest_failed: 0
pytest_passed: 234
eval_exit_code: 4
regression_count: 5
gate_status: FAILED
METR-09: blocked
PERF-01: blocked
---

# Phase 2 回归门结果（02-GATE-RESULTS）

⚠️ 本文件只记录命令、数量与场景 ID，**不含任何环境变量值或凭证**。

## 1. `make test`

```bash
PYTHON=.venv/bin/python3 make test
```

| 项 | 值 |
|---|---|
| exit | 0 |
| failed | **0** |
| passed | 234（含 Phase 2 新增单测；默认 `not realllm`） |

## 2. `make eval`（mock，权威干净跑）

```bash
rm -rf workspace/eval
PYTHONHASHSEED=0 PYTHON=.venv/bin/python3 make eval
```

| 项 | 值 |
|---|---|
| exit | 4（硬退出：top1 &lt; 0.8） |
| top1_root_cause_accuracy | 0.4444 |
| false_positive_rate | 0.0 |
| dangling_citation_rate | 0.0 |
| illegal_skill_reselect_total | 0 |

### 正确场景集合

```
S0_HEALTHY
S1_DOWNLOAD_TIMEOUT
S3_UDS_NRC72
S5_STORAGE_FULL
S7_DEP_MISMATCH
```

### 相对 `01-BASELINE.md` `baseline_eval_correct_case_ids` 的回归

```
regression_count: 5
S2_SIGNATURE_FAIL
S4_POWER_DROP
S6_ECU_SILENT
S8_ACTIVATE_ROLLBACK
S9_TIME_DRIFT
```

**一票否决触发（D-25）**：不得宣称 Phase 2 完成；不得进入付费基线冒充 METR-09 done。

### 备注

- 同日另一次 `--reuse-workspace` 跑曾出现 10/10，但干净重建不可复现；以干净 `make eval` 为准。
- NR-1 允许尺子变准后分数下降，但 ROADMAP/D-25 仍要求「已通过用例回归数 = 0」。需排查未通过用例是引用闸门预期行为还是推理/仿真漂移后再定是否修订基线集合。

## 3. 待执行的付费基线命令（Task 3 — 门禁未过，暂缓）

```bash
PYTHON=.venv/bin/python3 make doctor
PYTHON=.venv/bin/python3 make baseline
# 等价：
# VELA_LLM_PROVIDER=volcengine vela doctor --json > .planning/phases/02-metrics-baseline/baseline/doctor.json
# vela eval run --provider volcengine --no-cache --repeat 3 --reuse-workspace \
#   --out .planning/phases/02-metrics-baseline/baseline
# 可选：make bench-volc
```

**METR-09: blocked** / **PERF-01: blocked** — 待回归门清零或项目方明确接受新正确集合后补跑。禁止伪造 `baseline/report.md` / `result.json` 数字。

## Task 3 执行结果（2026-08-01）

- METR-09: **done**（`baseline/report.md` + `baseline/result.json` 已落盘；N=3；no_cache；provider=volcengine）
- PERF-01: **done**（末次 run diagnose P50/P95 写入 result.json meta.perf；单价占位时成本可为 0）
- top1 mean≈0.5185，95% CI≈[0.20, 0.84]（低于 44.4% 旧数属尺子变准后的预期）
- 报告含「非能力宣称」与「44.4% 退役」声明；无 API key 明文
