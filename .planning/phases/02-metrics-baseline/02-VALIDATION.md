---
phase: 02
slug: metrics-baseline
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-07-31
---

# Phase 02 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `02-RESEARCH.md` § Validation Architecture.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ≥8.0 |
| **Config file** | `pyproject.toml` → `[tool.pytest.ini_options]`（`addopts = "-q --strict-markers -m 'not realllm'"`） |
| **Quick run command** | `make test-fast` |
| **Full suite command** | `make test` |
| **Estimated runtime** | ~30s fast / ~3–8min full（视建库 fixture） |

---

## Sampling Rate

- **After every task commit:** `make test-fast` + 相关单文件 pytest
- **After every plan wave:** `make test`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 120 seconds（fast 路径）

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 02-01-* | 01 | 1 | METR-01/02 | — | 零引用 ok=False；None-safe | unit | `pytest tests/test_agent.py tests/test_eval.py -k 'citation or dangling or coverage or zero' -q` | ❌ W0 | ⬜ pending |
| 02-02-* | 02 | 1 | METR-03 | NR-6 | hash 扩展；env_checks 排除 | unit | `pytest tests/test_obs_and_config.py -k config_hash -q` | ⚠️ | ⬜ pending |
| 02-03-* | 03 | 1 | METR-06/PERF-02 | T-cache/T-cost | 缓存仅 redact 后；ALERT≠切断 | unit | `pytest tests/test_gateway.py -k 'cache or ledger_cost' -q` | ❌ W0 | ⬜ pending |
| 02-04-* | 04 | 2 | METR-04/07 | — | repeat CI；reuse 完好库 | unit/int | `pytest tests/test_eval.py -k 'repeat or reuse' -q` | ❌ W0 | ⬜ pending |
| 02-05-* | 05 | 3 | METR-05/08 | — | 过程键+消融代理；不改 YAML | unit/int | `pytest tests/test_eval.py -k 'process_metric or ablation' -q` | ❌ W0 | ⬜ pending |
| 02-06-* | 06 | 4 | METR-09/PERF-01 | Spoofing | 基线标注非 G4；无密钥 | realllm+file | `pytest -m realllm`（显式）+ `baseline/` schema | ❌ W0 | ⬜ pending |
| gate | — | — | D-25 | — | 回归门 | suite | `make test` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_agent.py` — 零引用 `ok is False`、`dangling_rate is None`、`has_citations`（METR-01/02）
- [ ] `tests/test_obs_and_config.py` — skills/budget/llm/prompts 变异改 hash；env_checks 不变（METR-03）
- [ ] `tests/test_eval.py` — repeat 聚合、process metrics、coverage、reuse-workspace、ablation 代理（METR-04/05/07/08）
- [ ] `tests/test_gateway.py` — 磁盘缓存命中/旁路、TokenLedger 成本与 ALERT（METR-06/PERF-02）
- [ ] `docs/CONFIG_HASH_HISTORY.md` — NR-6 断代映射（随 Plan 02）
- [ ] `.venv` 安装 `scipy`（dev 依赖，METR-04）
- [ ] （可选）bench 聚合 dry-run mock 测（PERF-01）

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 volcengine 方差基线 N≥3 `--no-cache` | METR-09 | 付费 API；默认 exclude realllm | 凭证就绪后显式 `VELA_LLM_PROVIDER=volcengine pytest -m realllm` 或 Plan 06 人工门；确认 `baseline/` md+json |
| 端到端 P95 + token 成本基线写入 | PERF-01 | 与 METR-09 同次付费采集 | 跑扩展后 `scripts/bench.py`；产物入 `baseline/`；无 API key 落盘 |
| 仿真已通过用例回归数 = 0 | D-25 / 回归门 | 需完整 eval 数据集 | `make eval`（mock）对比基线场景集 |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s（fast）
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
