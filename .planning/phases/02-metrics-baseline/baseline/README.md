# Phase 2 真实方差基线（METR-09 / PERF-01）

**仿真回归门基线，非能力宣称；G4 真实标注集本期未测。**

## 强制条件

- `VELA_LLM_PROVIDER=volcengine`
- **必须** `--no-cache`（禁止磁盘缓存污染方差）
- `--repeat N` 且 **N≥3**
- 产物：本目录 `report.md`（人读）+ `result.json`（机读）

## 运行

```bash
PYTHON=.venv/bin/python3 make baseline
# 或
PYTHONPATH=src VELA_CONFIG_DIR=config .venv/bin/python3 -m vela.cli eval run \
  --dataset ./data/dataset --workspace ./workspace/baseline-eval \
  --out .planning/phases/02-metrics-baseline/baseline \
  --provider volcengine --no-cache --repeat 3 --reuse-workspace
```

可选 PERF：`make bench-volc`（同 provider / no-cache）。

## NR-1

自本目录验收完成起，**禁止再引用 44.4%** 作为后续对比基线。Phase 3~6 一律以本目录数字为准。
分数可能因引用闸门变准而低于旧数——属预期，不是回归。

## 待补跑

若无火山引擎凭据，勿伪造 `report.md`/`result.json` 数字；在 GATE-RESULTS 标记 `METR-09: blocked`。
