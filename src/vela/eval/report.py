"""评测报告渲染（Markdown）。"""
from __future__ import annotations

from vela.eval.runner import EvalResult

_TARGETS = {
    "top1_root_cause_accuracy": (0.80, ">="),
    "healthy_specificity": (1.00, ">="),
    "false_positive_rate": (0.00, "<="),
    "dangling_citation_rate": (0.015, "<="),
    "citation_coverage": (0.9, ">="),
    "illegal_skill_reselect_total": (0, "<="),
    "evidence_pack_verify_pass": (1.00, ">="),
}


def render_markdown(result: EvalResult) -> str:
    m = result.metrics()
    L = ["# VELA 黄金评测报告", "",
         f"- profile: `{m['profile']}`  provider: `{m['provider']}`",
         f"- 用例总数: **{m['cases_total']}**（故障 {m['cases_faulty']} / 健康 {m['cases_healthy']}）",
         f"- 总耗时: {m['total_elapsed_s']} s", "",
         "## 核心指标与达标情况", "",
         "| 指标 | 实测 | 目标 | 结论 |", "|---|---|---|---|"]
    for k, (target, op) in _TARGETS.items():
        v = m.get(k, 0)
        if v is None:
            ok = False
            display = "None（无引用可测）"
        else:
            ok = (v >= target) if op == ">=" else (v <= target)
            display = v
        L.append(f"| {k} | {display} | {op} {target} | {'✅ 达标' if ok else '❌ 未达标'} |")
    L += ["", "## 其它指标", "", "| 指标 | 值 |", "|---|---|"]
    for k in ("fail_phase_accuracy", "culprit_component_hit", "skill_selection_hit",
              "avg_compression_ratio", "avg_rounds", "avg_llm_tokens",
              "zero_citation_cases", "citation_gate_pass_rate",
              "diagnose_p50_s", "diagnose_p95_s"):
        L.append(f"| {k} | {m.get(k)} |")
    L += ["", "## 逐用例明细", "",
          "| 用例 | 期望根因 | 判定根因 | Top1 | 阶段 | 模块 | 技能 | 轮次 | 压缩比 | 悬空率 | 证据包 | 诊断秒 |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in result.cases:
        tick = lambda b: "✅" if b else "—"     # noqa: E731
        pack = {True: "✅", False: "❌", None: "—"}[c.evidence_pack_ok]
        L.append(f"| {c.case_id} | {c.expected_label or '（健康）'} | {c.predicted_label or '—'} | "
                 f"{tick(c.top1_hit) if not c.healthy else ('✅' if c.predicted_label in (None, '', 'undetermined', 'no_fault_found') else '❌')} | "
                 f"{tick(c.phase_hit)} | {tick(c.component_hit)} | {tick(c.skill_hit)} | "
                 f"{c.rounds} | {c.compression_ratio} | {c.dangling_rate} | {pack} | "
                 f"{round(c.diagnose_seconds,1)} |")
    notes = [(c.case_id, n) for c in result.cases for n in c.notes]
    if notes:
        L += ["", "## 备注", ""]
        L += [f"- **{cid}**: {n}" for cid, n in notes]
    return "\n".join(L) + "\n"
