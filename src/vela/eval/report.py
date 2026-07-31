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
    # 消融/泛化（展示目标；本阶段不要求达标，不进 cmd_eval 硬退出）
    "misdiagnosis_rate_under_ablation": (0.50, "<="),
    "novel_detection_recall": (0.50, ">="),
    "unexplained_error_rate": (0.50, "<="),
    "confidence_calibration_error": (0.50, "<="),
}


def render_markdown(result: EvalResult, *,
                    runs: list[dict] | None = None,
                    aggregate: dict | None = None) -> str:
    m = result.metrics()
    L = ["# VELA 黄金评测报告", "",
         f"- profile: `{m['profile']}`  provider: `{m['provider']}`",
         f"- 用例总数: **{m['cases_total']}**（故障 {m['cases_faulty']} / 健康 {m['cases_healthy']}）",
         f"- 总耗时: {m['total_elapsed_s']} s", "",
         "## 核心指标与达标情况", "",
         "| 指标 | 实测 | 目标 | 结论 |", "|---|---|---|---|"]
    for k, (target, op) in _TARGETS.items():
        if k not in m and k in ("misdiagnosis_rate_under_ablation", "novel_detection_recall",
                                "confidence_calibration_error"):
            continue
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
              "premature_stop_rate", "llm_parse_failure_rate", "llm_truncation_rate",
              "verdict_supported_ratio", "skill_switch_per_session",
              "diagnose_p50_s", "diagnose_p95_s"):
        L.append(f"| {k} | {m.get(k)} |")
    if m.get("process_footnote") or m.get("ablation_footnote"):
        L += ["", f"> {m.get('ablation_footnote') or m.get('process_footnote')}", ""]
    trace = m.get("decision_trace") or []
    if trace:
        L += ["", "## 每轮决策轨迹", "",
              "| case_id | round_no | selected_skill | stop | actions |",
              "|---|---|---|---|---|"]
        for row in trace[:200]:
            L.append(f"| {row.get('case_id')} | {row.get('round_no')} | "
                     f"{row.get('selected_skill') or '—'} | {row.get('stop')} | "
                     f"{row.get('actions')} |")
    if aggregate:
        L += ["", "## 重复评测聚合（均值 ± 标准差 / 95% CI）", "",
              "| 指标 | mean | std | ci95 | n |", "|---|---|---|---|---|"]
        for k, st in sorted(aggregate.items()):
            ci = st.get("ci95")
            ci_s = f"[{ci[0]:.4f}, {ci[1]:.4f}]" if ci else "—"
            L.append(f"| {k} | {st.get('mean')} | {st.get('std')} | {ci_s} | {st.get('n')} |")
    if runs:
        L += ["", "## 逐次 run 明细", ""]
        for i, rm in enumerate(runs, 1):
            L.append(f"- run {i}: top1={rm.get('top1_root_cause_accuracy')} "
                     f"fp={rm.get('false_positive_rate')} "
                     f"dangling={rm.get('dangling_citation_rate')}")
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
