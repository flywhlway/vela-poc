"""过程指标与决策轨迹聚合（METR-05）；消融代理指标（METR-08）。

全部在 eval 侧事后聚合，不改 AgentGraph 控制流。
报表须标注「代理口径，Phase 5 后替换」/「聚合自 events，Phase 3 前允许偏高」。
"""
from __future__ import annotations

from typing import Any

from vela.agent.citations import citation_coverage as _citation_coverage

PROCESS_METRIC_KEYS = (
    "premature_stop_rate",
    "llm_parse_failure_rate",
    "llm_truncation_rate",
    "verdict_supported_ratio",
    "skill_switch_per_session",
    "unexplained_error_rate",
    "citation_coverage",
)

ABLATION_METRIC_KEYS = (
    "misdiagnosis_rate_under_ablation",
    "novel_detection_recall",
    "unexplained_error_rate",
    "confidence_calibration_error",
)

PROXY_FOOTNOTE = (
    "注：过程/消融指标为代理口径（聚合自 SessionState/events/audit），"
    "Phase 3 前允许偏高；依赖六级置信度或 novel: 的字段 Phase 5 后替换。"
)


def _events(case: dict) -> list[dict]:
    return list(case.get("events") or [])


def _payload(ev: dict) -> dict:
    return ev.get("payload") or {}


def decision_trace(cases: list[dict]) -> list[dict]:
    """每轮决策轨迹行：case_id, round_no, selected_skill, stop, notes。"""
    rows: list[dict] = []
    for c in cases:
        cid = c.get("case_id", "")
        for rr in c.get("rounds") or []:
            rows.append({
                "case_id": cid,
                "round_no": rr.get("round_no"),
                "selected_skill": rr.get("selected_skill"),
                "stop": None,
                "actions": len(rr.get("actions") or []),
                "productive": rr.get("productive"),
            })
        for ev in _events(c):
            if ev.get("kind") != "plan.done":
                continue
            p = _payload(ev)
            # 回填同轮 stop
            for row in rows:
                if row["case_id"] == cid and row["round_no"] == ev.get("round_no"):
                    row["stop"] = bool(p.get("stop"))
                    if row["selected_skill"] is None:
                        row["selected_skill"] = p.get("skill")
    return rows


def _r(x: float) -> float:
    return round(float(x), 4)


def aggregate_process_metrics(cases: list[dict]) -> dict[str, Any]:
    """从用例夹具（含 events/rounds/audit/report_md）聚合 7 项过程指标。"""
    n = len(cases) or 1
    premature = 0
    parse_fail = 0
    trunc_num = trunc_den = 0
    supported = claims = 0
    switches: list[int] = []
    unexplained_vals: list[float] = []
    coverages: list[float] = []

    for c in cases:
        evs = _events(c)
        plan_dones = [e for e in evs if e.get("kind") == "plan.done"]
        # premature：首轮 stop=True
        first = next((e for e in plan_dones if e.get("round_no") == 1), None)
        if first and _payload(first).get("stop"):
            premature += 1
        # parse failure 代理：plan.done 且 skill is None 且 stop=False 且无 actions
        for e in plan_dones:
            p = _payload(e)
            acts = p.get("actions") or []
            if p.get("skill") is None and not p.get("stop") and not acts:
                parse_fail += 1
                break
        # truncation：audit finish_reason==length
        for a in c.get("audit") or []:
            trunc_den += 1
            if a.get("finish_reason") == "length":
                trunc_num += 1
        # verdict supported
        for e in evs:
            if e.get("kind") == "verify.done":
                p = _payload(e)
                supported += int(p.get("supported") or 0)
                claims += int(p.get("claims") or 0)
        # skill switches
        skills = [rr.get("selected_skill") for rr in (c.get("rounds") or [])]
        sw = 0
        for i in range(1, len(skills)):
            if skills[i] and skills[i - 1] and skills[i] != skills[i - 1]:
                sw += 1
        switches.append(sw)
        # unexplained：用例级预计算或 None
        u = c.get("unexplained_error_rate")
        if u is not None:
            unexplained_vals.append(float(u))
        coverages.append(float(c.get("citation_coverage",
                                     _citation_coverage(c.get("report_md") or ""))))

    return {
        "premature_stop_rate": _r(premature / n),
        "llm_parse_failure_rate": _r(parse_fail / n),
        "llm_truncation_rate": _r(trunc_num / trunc_den) if trunc_den else 0.0,
        "verdict_supported_ratio": _r(supported / claims) if claims else 0.0,
        "skill_switch_per_session": _r(sum(switches) / len(switches)) if switches else 0.0,
        "unexplained_error_rate": (
            _r(sum(unexplained_vals) / len(unexplained_vals)) if unexplained_vals else None
        ),
        "citation_coverage": _r(sum(coverages) / len(coverages)) if coverages else 1.0,
        "_footnote": PROXY_FOOTNOTE,
    }


def aggregate_ablation_metrics(cases: list[dict]) -> dict[str, Any]:
    """消融集四指标（代理口径）。分母=非健康用例。"""
    faulty = [c for c in cases if not c.get("healthy")]
    if not faulty:
        return {k: 0.0 for k in ABLATION_METRIC_KEYS} | {"_footnote": PROXY_FOOTNOTE}

    def _no_fault(label) -> bool:
        return label in (None, "", "undetermined", "no_fault_found")

    mis = 0
    novel = 0
    cal_err = 0.0
    for c in faulty:
        status = c.get("status") or ""
        pred = c.get("predicted_label")
        expected = c.get("expected_label")
        answered = status == "answered"
        if answered and pred and expected and pred != expected:
            mis += 1
        if status in ("unanswerable", "human_gate") or _no_fault(pred):
            novel += 1
        conf = 1.0 if answered else 0.0
        hit = 1.0 if c.get("top1_hit") else 0.0
        cal_err += abs(conf - hit)

    unexplained = aggregate_process_metrics(cases).get("unexplained_error_rate")
    n = len(faulty)
    return {
        "misdiagnosis_rate_under_ablation": _r(mis / n),
        "novel_detection_recall": _r(novel / n),
        "unexplained_error_rate": unexplained,
        "confidence_calibration_error": _r(cal_err / n),
        "_footnote": PROXY_FOOTNOTE,
    }


def mask_skills(all_skills: list[dict], exclude_ids: list[str] | set[str]) -> list[dict]:
    """运行时 mask：剔除 expected_skills，不改源 YAML。"""
    ex = set(exclude_ids)
    return [s for s in all_skills if s.get("id") not in ex]
