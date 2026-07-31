---
phase: 02-metrics-baseline
status: passed
updated: 2026-08-01
---

# Phase 02 Verification

## Goal

修正评测尺子并在真实火山引擎上建立带 CI 的准确率/成本/延迟基线（METR-01..09、PERF-01/02），不改 AgentGraph 推理控制流（ADR-2 / D-24）。

## Requirement coverage

| ID | Status | Evidence |
|----|--------|----------|
| METR-01 | pass | `CitationReport.ok` 零引用 False；test_zero_citation |
| METR-02 | pass | dangling_rate=None；has_citations；None-safe eval |
| METR-03 | pass | config_hash 扩 skills/budget/llm/prompts；HISTORY.md |
| METR-04 | pass | `--repeat` + scipy t-CI；aggregate in report |
| METR-05 | pass | process.py 7 键 + 决策轨迹 |
| METR-06 | pass | LLMDiskCache；--no-cache |
| METR-07 | pass | --reuse-workspace 三条件 |
| METR-08 | pass | --ablation mask；四代理指标入 _TARGETS |
| METR-09 | pass | baseline/report.md+result.json N=3 volcengine no-cache |
| PERF-01 | pass | meta.perf P50/P95；bench --no-cache |
| PERF-02 | pass | TokenLedger estimated_cost + cost.alert |

## Must-haves spot-check

- [x] 零引用闸门失败（02-01）
- [x] config_hash 扰动 + env_checks 负例（02-02）
- [x] 缓存命中仍 charge；finish_reason 入审计（02-03）
- [x] repeat/reuse/no-cache CLI（02-04）
- [x] process + ablation 可测；未改 CONF-03（02-05）
- [x] GATE failed=0 regression=0；baseline 落盘；44.4% 退役声明（02-06）
- [x] `git diff`/审查：无 node_report 重试/status 机改动（仅 None-safe 计量与 enable_cache 传参）

## Gates

- `make test`：failed=0（234 collected，3 realllm deselected）
- mock eval：correct IDs = Phase1 baseline 全集；regression_count=0
- 付费基线：top1 mean≈0.5185，CI≈[0.20,0.84]

## Human verification

无待人工项（METR-09 已在有凭证路径下跑完）。

## Gaps

无阻塞缺口。

## status: passed
