---
phase: 3
slug: orch-logic-hemostasis
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-08-01
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest ≥8.0 |
| **Config file** | `pyproject.toml` → `[tool.pytest.ini_options]` |
| **Quick run command** | `make test-fast` |
| **Full suite command** | `make test` |
| **Estimated runtime** | fast ≤120s；full suite 视机器而定 |

---

## Sampling Rate

- **After every task commit:** Run `make test-fast` + 相关 `-k` 单测
- **After every plan wave:** Run `make test`
- **Before `/gsd-verify-work`:** Full suite must be green；mock `make eval` 仿真回归数 = 0
- **Max feedback latency:** 120 seconds（fast / `-k`）；Phase gate（`make test` + `make eval`）可 &gt;30s，属可接受全量门，不降低 gate 范围

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-01-01 | 01 | 0 | ORCH-01..10 | T-03-00 | Wave 0 骨架可收集 | unit stubs | `pytest tests/test_agent.py tests/test_gateway.py -q --collect-only` | ❌→Plan01 | ⬜ pending |
| 03-01-02 | 01 | 0 | process | — | 真实事件优先骨架 | unit stubs | `pytest tests/test_eval.py -k 'process_metrics_prefer or ablation_excludes_insufficient' -q` | ❌→Plan01 | ⬜ pending |
| 03-02-01 | 02 | 1 | ORCH-03 | T-03-02 | 解析失败重试+ALERT；禁跨段假成功 | unit | `pytest tests/test_agent.py -k parse_json -q` | ❌ W0 | ⬜ pending |
| 03-02-02 | 02 | 1 | ORCH-04 | T-03-02 | max_tokens=2048；length→truncation | unit | `pytest tests/test_gateway.py tests/test_agent.py -k 'max_tokens or truncation' -q` | ❌ W0 | ⬜ pending |
| 03-03-01 | 03 | 2 | ORCH-07 | T-03-01a | unproductive-only + probe dedup | unit | `pytest tests/test_agent.py -k 'excluded_skills or probe_dedup' -q` | ⚠️ rewrite | ⬜ pending |
| 03-03-02 | 03 | 2 | ORCH-10 | T-03-10 | A1：全零分 AND ERROR → 注入 GENERIC | unit | `pytest tests/test_agent.py -k 'generic_fallback or skill_registry' -q` | ❌ W0 | ⬜ pending |
| 03-04-01 | 04 | 3 | ORCH-02 | T-03-01b | PLANNER_SYSTEM 禁止无证据 stop | unit | `pytest tests/test_gateway.py -k planner_system -q` | ❌ W0 | ⬜ pending |
| 03-04-02 | 04 | 3 | ORCH-01 | T-03-01 | 首轮 stop 程序化驳回 | unit | `pytest tests/test_agent.py -k stop_rejected -q` | ❌ W0 | ⬜ pending |
| 03-05-01 | 05 | 4 | ORCH-06 | T-03-03b | claim=根因假设非 raw_line 自证 | unit | `pytest tests/test_agent.py -k verify_claim_hypothesis -q` | ❌ W0 | ⬜ pending |
| 03-05-02 | 05 | 4 | ORCH-05 | T-03-03 | verdict 归一化；partial 可推进 | unit | `pytest tests/test_agent.py -k verdict_norm -q` | ❌ W0 | ⬜ pending |
| 03-06-01 | 06 | 5 | ORCH-08 | T-03-04 | 引用不足重试→insufficient_citation | unit | `pytest tests/test_agent.py -k insufficient_citation -q` | ❌ W0 | ⬜ pending |
| 03-06-02 | 06 | 5 | ORCH-09 | T-03-05 | 未解释 ERROR→insufficient_coverage + samples 非空 | unit | `pytest tests/test_agent.py tests/test_eval.py -k 'unexplained_sweep or process_metrics_prefer or ablation_excludes_insufficient' -q` | ❌ W0 | ⬜ pending |
| 03-07-01 | 07 | 6 | 回归门 | T-03-07 | 全量绿；仿真回归 0（可 &gt;30s；波次内用 test-fast） | suite | `test -d data/dataset \|\| make sim; make test && make eval` | ✅ | ⬜ pending |
| 03-07-02 | 07 | 6 | ORCH-01..10 | T-03-07 | REQUIREMENTS 勾选闭环 | docs | `rg '\[ \] \*\*ORCH-' .planning/REQUIREMENTS.md` 无命中 | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_agent.py` — stubs：stop_rejected / parse_json / verdict_norm / claim_hypothesis / excluded 改写 / probe_dedup / citation_ratio / unexplained_sweep / generic_fallback（Plan 03-01）
- [ ] `tests/test_gateway.py` — max_tokens 配置断言 / truncation 计数 / planner_system（Plan 03-01）
- [ ] `tests/test_eval.py` — 过程指标消费真实事件（Plan 03-01 骨架 → Plan 03-06 转绿）
- [ ] （可选）最小 fixture DB：含 ERROR 行但 evidence_pool 为空，供 ORCH-09

*Existing pytest 基础设施可跑；ORCH 专用用例大多缺失 → Wave 0 必做。*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| 真实 LLM 过程指标抽检（可选） | ORCH-01..05,09 | 付费 + 非阻断 | `VELA_LLM_PROVIDER=volcengine` 下对仿真集抽检；对照 ROADMAP 阈值；不阻断 mock 合入 |

*其余行为均有自动化验证路径。*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
