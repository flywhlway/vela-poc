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
- **Max feedback latency:** 120 seconds（fast）

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 03-W0-* | 00 | 0 | ORCH-01..10 | — | N/A | unit stubs | `pytest tests/test_agent.py -k 'stop_rejected or parse_json or verdict' -q` | ❌ W0 | ⬜ pending |
| 03-*-* | TBD | 1+ | ORCH-01 | T-3-01 | 首轮 stop 程序化驳回 | unit | `pytest tests/test_agent.py -k stop_rejected -q` | ❌ W0 | ⬜ pending |
| 03-*-* | TBD | 1+ | ORCH-02 | T-3-01 | PLANNER_SYSTEM 禁止无证据 stop | unit | `pytest tests/test_gateway.py -k planner_system -q` | ❌ W0 | ⬜ pending |
| 03-*-* | TBD | 1+ | ORCH-03 | T-3-02 | 解析失败重试+ALERT；禁跨段假成功 | unit | `pytest tests/test_agent.py -k parse_json -q` | ❌ W0 | ⬜ pending |
| 03-*-* | TBD | 1+ | ORCH-04 | T-3-02 | max_tokens=2048；length→truncation | unit | `pytest tests/test_gateway.py -k 'max_tokens or truncation' -q` | ❌ W0 | ⬜ pending |
| 03-*-* | TBD | 1+ | ORCH-05 | T-3-03 | verdict 归一化；partial 可推进 | unit | `pytest tests/test_agent.py -k verdict_norm -q` | ❌ W0 | ⬜ pending |
| 03-*-* | TBD | 1+ | ORCH-06 | T-3-03 | claim=根因假设非 raw_line 自证 | unit | `pytest tests/test_agent.py -k verify_claim_hypothesis -q` | ❌ W0 | ⬜ pending |
| 03-*-* | TBD | 1+ | ORCH-07 | T-3-01 | unproductive-only + probe dedup | unit | `pytest tests/test_agent.py -k 'excluded_skills or probe_dedup' -q` | ⚠️ rewrite | ⬜ pending |
| 03-*-* | TBD | 1+ | ORCH-08 | T-3-04 | 引用不足重试→insufficient_citation | unit | `pytest tests/test_agent.py -k insufficient_citation -q` | ❌ W0 | ⬜ pending |
| 03-*-* | TBD | 1+ | ORCH-09 | T-3-05 | 未解释 ERROR→禁 no_fault_found | unit/int | `pytest tests/test_agent.py -k unexplained_sweep -q` | ❌ W0 | ⬜ pending |
| 03-*-* | TBD | 1+ | ORCH-10 | — | 全零分注入 SK-GENERIC-EVIDENCE-FIRST | unit | `pytest tests/test_agent.py -k generic_fallback -q` | ❌ W0 | ⬜ pending |
| 03-*-* | TBD | last | 回归门 | — | 177+ 绿；仿真回归 0 | suite | `make test` + mock `make eval` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

*Plan/Task IDs 由 planner 落地后回填；上表 Requirement→Command 映射锁定。*

---

## Wave 0 Requirements

- [ ] `tests/test_agent.py` — stubs：stop_rejected / parse_json / verdict_norm / claim_hypothesis / excluded 改写 / probe_dedup / citation_ratio / unexplained_sweep / generic_fallback
- [ ] `tests/test_gateway.py` — max_tokens 配置断言 / truncation 计数
- [ ] `tests/test_eval.py` — 过程指标消费真实事件（`llm.parse_failure` 等）
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
