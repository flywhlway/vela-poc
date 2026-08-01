"""评估平面：黄金用例装载 + 逐用例评测 + 指标计算 + 报告渲染。真值绝不进模型上下文。"""
from __future__ import annotations

import pytest

from vela.eval.golden import load_golden
from vela.eval.report import render_markdown
from vela.eval.runner import EvalResult, EvalRunner, CaseResult, _no_fault


def test_load_golden_reads_truth_sidecars(dataset):
    cases = load_golden(dataset["dir"])
    assert len(cases) == 3
    by_id = {c.case_id: c for c in cases}
    assert by_id["S3_UDS_NRC72"].expected_label == "uds_nrc_programming_failure"
    assert by_id["S0_HEALTHY"].healthy is True
    assert by_id["S3_UDS_NRC72"].healthy is False


def test_golden_case_exposes_expected_fields(dataset):
    cases = {c.case_id: c for c in load_golden(dataset["dir"])}
    s3 = cases["S3_UDS_NRC72"]
    assert s3.expected_phase == "FLASH"
    assert "uds_stack" in s3.culprit_components
    assert "SK-UDS-NRC" in s3.expected_skills


def test_no_fault_helper_accepts_all_negative_labels():
    for lbl in (None, "", "undetermined", "no_fault_found"):
        assert _no_fault(lbl)
    assert not _no_fault("uds_nrc_programming_failure")


def test_runner_end_to_end_on_small_golden_set(dataset, tmp_path):
    runner = EvalRunner(dataset["dir"], tmp_path / "eval_ws", provider="mock", profile="poc")
    cases = load_golden(dataset["dir"])
    result = runner.run(cases=cases)
    assert len(result.cases) == 3
    by_id = {c.case_id: c for c in result.cases}
    assert by_id["S3_UDS_NRC72"].top1_hit is True
    assert by_id["S3_UDS_NRC72"].evidence_pack_ok is True
    assert _no_fault(by_id["S0_HEALTHY"].predicted_label)


def test_metrics_healthy_specificity_and_false_positive_are_complementary():
    result = EvalResult(cases=[
        CaseResult(case_id="H1", archive="a", expected_label=None,
                  predicted_label=None, healthy=True),
        CaseResult(case_id="H2", archive="b", expected_label=None,
                  predicted_label="some_fault", healthy=True),
    ], profile="poc", provider="mock")
    m = result.metrics()
    assert m["healthy_specificity"] == 0.5
    assert m["false_positive_rate"] == 0.5


def test_metrics_top1_accuracy_only_over_faulty_cases():
    result = EvalResult(cases=[
        CaseResult(case_id="F1", archive="a", expected_label="x", predicted_label="x",
                  healthy=False, top1_hit=True),
        CaseResult(case_id="F2", archive="b", expected_label="y", predicted_label="z",
                  healthy=False, top1_hit=False),
        CaseResult(case_id="H1", archive="c", expected_label=None, predicted_label=None,
                  healthy=True),
    ], profile="poc", provider="mock")
    m = result.metrics()
    assert m["cases_faulty"] == 2 and m["cases_healthy"] == 1
    assert m["top1_root_cause_accuracy"] == 0.5


def test_render_markdown_includes_targets_and_case_table():
    result = EvalResult(cases=[
        CaseResult(case_id="F1", archive="a", expected_label="uds_nrc_programming_failure",
                  predicted_label="uds_nrc_programming_failure", healthy=False, top1_hit=True,
                  evidence_pack_ok=True),
    ], profile="poc", provider="mock")
    md = render_markdown(result)
    assert "top1_root_cause_accuracy" in md
    assert "F1" in md and "uds_nrc_programming_failure" in md


def test_render_markdown_includes_notes_section_when_present():
    result = EvalResult(cases=[
        CaseResult(case_id="F1", archive="a", expected_label="x", predicted_label=None,
                  healthy=False, notes=["BUILD_FAILED: boom"]),
    ], profile="poc", provider="mock")
    md = render_markdown(result)
    assert "备注" in md and "BUILD_FAILED" in md


def test_metrics_none_safe_dangling_and_citation_coverage():
    """零引用 dangling_rate=None 不参与均值；coverage / gate 键可聚合。"""
    result = EvalResult(cases=[
        CaseResult(case_id="Z", archive="a", expected_label="x", predicted_label="x",
                   healthy=False, top1_hit=True, dangling_rate=None,
                   has_citations=False, citation_ok=False, citation_coverage=0.0),
        CaseResult(case_id="C", archive="b", expected_label="y", predicted_label="y",
                   healthy=False, top1_hit=True, dangling_rate=0.0,
                   has_citations=True, citation_ok=True, citation_coverage=1.0),
    ], profile="poc", provider="mock")
    m = result.metrics()
    assert m["dangling_citation_rate"] == 0.0
    assert m["zero_citation_cases"] == 1
    assert m["citation_gate_pass_rate"] == 0.5
    assert m["citation_coverage"] == 0.5
    md = render_markdown(result)
    assert "citation_coverage" in md


def test_metrics_all_zero_citation_dangling_is_none():
    result = EvalResult(cases=[
        CaseResult(case_id="Z1", archive="a", expected_label=None, predicted_label=None,
                   healthy=True, dangling_rate=None, has_citations=False),
    ], profile="poc", provider="mock")
    assert result.metrics()["dangling_citation_rate"] is None


def test_truth_narrative_never_reaches_agent_context(built):
    """机制校验：sidecar 真值中的 narrative/root_cause_label 绝不应出现在诊断报告正文中，
    否则就是评测意义上的答案泄漏（agent 只能通过工具查询列式库，不能读取 truth.json）。"""
    from vela.agent.graph import AgentGraph
    g = AgentGraph(built["db"], workspace=built["ws"] / "leak_check")
    try:
        res = g.run()
    finally:
        g.close()
    truth = built["truth"]
    assert truth["narrative"] not in res.state.report_md


def test_mean_std_ci95_matches_scipy():
    pytest.importorskip("scipy")
    from vela.eval.stats import mean_std_ci

    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    out = mean_std_ci(vals)
    assert out["n"] == 5
    assert abs(out["mean"] - 3.0) < 1e-9
    assert abs(out["std"] - 1.5811388300841898) < 1e-9
    assert out["ci95"] is not None
    lo, hi = out["ci95"]
    assert abs(lo - 1.0367568385224428) < 1e-9
    assert abs(hi - 4.963243161477557) < 1e-9
    assert mean_std_ci([42.0])["ci95"] is None


def test_aggregate_metrics_skips_none_and_non_numeric():
    pytest.importorskip("scipy")
    from vela.eval.stats import aggregate_metrics

    runs = [
        {"top1_root_cause_accuracy": 0.8, "dangling_citation_rate": None, "profile": "poc"},
        {"top1_root_cause_accuracy": 1.0, "dangling_citation_rate": 0.01, "profile": "poc"},
    ]
    agg = aggregate_metrics(runs, keys=["top1_root_cause_accuracy", "dangling_citation_rate"])
    assert "top1_root_cause_accuracy" in agg
    assert abs(agg["top1_root_cause_accuracy"]["mean"] - 0.9) < 1e-9
    assert agg["dangling_citation_rate"]["n"] == 1


def test_workspace_reusable_requires_three_conditions(tmp_path):
    from vela.eval.runner import EvalRunner
    from vela.util.jsonl import write_json

    ws = tmp_path / "case"
    assert EvalRunner.workspace_reusable(ws) is False
    (ws / "gold").mkdir(parents=True)
    (ws / "gold" / "analysis.duckdb").write_bytes(b"x")
    assert EvalRunner.workspace_reusable(ws) is False
    write_json(ws / "manifest.json", {"ok": True})
    assert EvalRunner.workspace_reusable(ws) is False
    (ws / "qa").mkdir()
    write_json(ws / "qa" / "qa_report.json", {"checks_passed": False})
    assert EvalRunner.workspace_reusable(ws) is False
    write_json(ws / "qa" / "qa_report.json", {"checks_passed": True})
    assert EvalRunner.workspace_reusable(ws) is True


def test_cli_eval_flags_and_repeat_lt2(tmp_path):
    from vela.cli import build_parser, cmd_eval, main

    p = build_parser()
    ns = p.parse_args(["eval", "run"])
    assert hasattr(ns, "repeat") and hasattr(ns, "reuse_workspace") and hasattr(ns, "no_cache")
    a = p.parse_args(["eval", "run", "--repeat", "1",
                      "--dataset", str(tmp_path), "--workspace", str(tmp_path / "ws"),
                      "--out", str(tmp_path / "out")])
    assert cmd_eval(a) == 2
    assert main(["eval", "run", "--repeat", "1",
                 "--dataset", str(tmp_path), "--workspace", str(tmp_path / "ws"),
                 "--out", str(tmp_path / "out")]) == 2


def test_no_cache_sets_env_and_runner_flag(monkeypatch, tmp_path):
    from vela.cli import build_parser

    monkeypatch.delenv("VELA_LLM_CACHE", raising=False)
    a = build_parser().parse_args([
        "eval", "run", "--no-cache",
        "--dataset", str(tmp_path), "--workspace", str(tmp_path / "ws"),
        "--out", str(tmp_path / "out"),
    ])
    assert a.no_cache is True
    from vela.eval.runner import EvalRunner
    r = EvalRunner(tmp_path, tmp_path / "ws", cache_enabled=False)
    assert r.cache_enabled is False


def test_process_metrics_keys_and_trace():
    from vela.eval.process import aggregate_process_metrics, decision_trace, PROXY_FOOTNOTE
    cases = [{
        "case_id": "C1",
        "healthy": False,
        "events": [
            {"kind": "plan.done", "round_no": 1, "payload": {"skill": "SK-A", "stop": True, "actions": []}},
            {"kind": "verify.done", "round_no": 1, "payload": {"supported": 1, "claims": 2}},
        ],
        "rounds": [{"round_no": 1, "selected_skill": "SK-A", "actions": [], "productive": False}],
        "audit": [{"finish_reason": "stop"}, {"finish_reason": "length"}],
        "report_md": "事实 [[EV:aaaa1111bbbb2222]]。",
        "citation_coverage": 1.0,
        "unexplained_error_rate": 0.25,
    }]
    m = aggregate_process_metrics(cases)
    for k in ("premature_stop_rate", "llm_parse_failure_rate", "llm_truncation_rate",
              "verdict_supported_ratio", "skill_switch_per_session",
              "unexplained_error_rate", "citation_coverage"):
        assert k in m
    assert m["premature_stop_rate"] == 1.0
    assert m["llm_truncation_rate"] == 0.5
    assert "代理口径" in PROXY_FOOTNOTE or "Phase 5" in PROXY_FOOTNOTE
    tr = decision_trace(cases)
    assert tr and tr[0]["case_id"] == "C1" and tr[0]["round_no"] == 1


def test_ablation_mask_skills_does_not_touch_yaml():
    from pathlib import Path
    from vela.config import load_skills
    from vela.eval.process import mask_skills, aggregate_ablation_metrics
    src = Path("config/skills/builtin.yaml").read_text(encoding="utf-8")
    all_sk = load_skills()
    ids = {s["id"] for s in all_sk}
    assert "SK-UDS-NRC" in ids
    masked = mask_skills(all_sk, ["SK-UDS-NRC"])
    assert "SK-UDS-NRC" not in {s["id"] for s in masked}
    assert Path("config/skills/builtin.yaml").read_text(encoding="utf-8") == src
    abl = aggregate_ablation_metrics([
        {"healthy": False, "status": "answered", "predicted_label": "wrong",
         "expected_label": "right", "top1_hit": False},
        {"healthy": False, "status": "unanswerable", "predicted_label": None,
         "expected_label": "right", "top1_hit": False},
    ])
    assert "misdiagnosis_rate_under_ablation" in abl
    assert "novel_detection_recall" in abl
    assert "confidence_calibration_error" in abl


def test_render_includes_process_footnote_when_present():
    result = EvalResult(cases=[
        CaseResult(case_id="F1", archive="a", expected_label="x", predicted_label="x",
                   healthy=False, top1_hit=True, evidence_pack_ok=True,
                   process_bundle={
                       "events": [{"kind": "plan.done", "round_no": 1,
                                   "payload": {"skill": "S", "stop": False, "actions": ["t"]}}],
                       "rounds": [{"round_no": 1, "selected_skill": "S", "actions": [{}],
                                   "productive": True}],
                       "audit": [],
                       "report_md": "ok",
                   }),
    ], profile="poc", provider="mock")
    md = render_markdown(result)
    assert "premature_stop_rate" in md
    assert "决策轨迹" in md
    assert "代理口径" in md or "Phase 5" in md


# --------------------------------------------------------------------- ORCH Wave 0 skeletons (xfail)
def test_process_metrics_prefer_real_parse_and_truncation_events():
    """过程指标优先计真实 llm.parse_failure / llm.truncation；脚注不再含 Phase 3 前偏高。"""
    from vela.eval.process import PROXY_FOOTNOTE, aggregate_process_metrics

    cases = [{
        "case_id": "C-REAL",
        "healthy": False,
        "events": [
            # 代理可触发的空 plan.done
            {"kind": "plan.done", "round_no": 1,
             "payload": {"skill": None, "stop": False, "actions": []}},
            {"kind": "llm.parse_failure", "round_no": 1, "payload": {"retries": 2}},
            {"kind": "llm.truncation", "round_no": 1, "payload": {"logical": "planner"}},
        ],
        "rounds": [{"round_no": 1, "selected_skill": None, "actions": [], "productive": False}],
        # audit 无 length —— 截断率应仍由真实事件贡献
        "audit": [{"finish_reason": "stop"}],
        "report_md": "x",
        "citation_coverage": 1.0,
        "unexplained_error_rate": 0.0,
    }]
    m = aggregate_process_metrics(cases)
    assert m["llm_parse_failure_rate"] == 1.0
    assert m["llm_truncation_rate"] == 1.0
    assert "Phase 3 前允许偏高" not in PROXY_FOOTNOTE
    assert "Phase 3 前允许偏高" not in str(m.get("_footnote") or "")


def test_ablation_excludes_insufficient_statuses_from_misdiagnosis():
    """insufficient_citation / insufficient_coverage 不计入 misdiagnosis 分子。"""
    from vela.eval import process as proc
    from vela.eval.process import aggregate_ablation_metrics

    excluded = set(getattr(proc, "MISDIAGNOSIS_EXCLUDED_STATUSES", ()))
    assert {"insufficient_citation", "insufficient_coverage"} <= excluded

    abl = aggregate_ablation_metrics([
        {"healthy": False, "status": "insufficient_citation", "predicted_label": "wrong",
         "expected_label": "right", "top1_hit": False},
        {"healthy": False, "status": "insufficient_coverage", "predicted_label": "wrong",
         "expected_label": "right", "top1_hit": False},
        {"healthy": False, "status": "answered", "predicted_label": "wrong",
         "expected_label": "right", "top1_hit": False},
    ])
    # 分子仅含 answered 误诊；insufficient_* 已由 MISDIAGNOSIS_EXCLUDED_STATUSES 声明排除
    assert abl["misdiagnosis_rate_under_ablation"] == pytest.approx(1 / 3, abs=1e-4)
