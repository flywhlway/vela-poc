"""评估平面：黄金用例装载 + 逐用例评测 + 指标计算 + 报告渲染。真值绝不进模型上下文。"""
from __future__ import annotations

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
