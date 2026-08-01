"""推理平面：技能召回、压缩痕迹、引用校验、七节点图端到端。"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest

from vela.agent.citations import (
    CitationReport,
    citation_coverage,
    extract_citations,
    split_factual_sentences,
    strip_dangling,
    verify_citations,
)
from vela.agent.compress import EvidenceCompressor
from vela.agent.graph import AgentGraph
from vela.agent.skills import SkillRegistry
from vela.agent.state import SessionState
from vela.config import load_budget
from vela.gateway.prompts import extract_state


# --------------------------------------------------------------------- skills
def test_skill_registry_loads_all_12():
    reg = SkillRegistry()
    assert len(reg.skills) == 12
    assert reg.label_of("SK-UDS-NRC") == "uds_nrc_programming_failure"


def test_retrieve_prioritizes_lexical_match_for_rare_keyword():
    reg = SkillRegistry()
    # 生产路径（graph._retrieval_query）在调用 retrieve() 前会把信号中的下划线替换为空格
    # （分词器把下划线视为词内字符，"UDS_NRC_0x72" 整体成词，故调用方需先行拆分）。
    cands = reg.retrieve("UDS NRC 0x72 erase sector failed programming failure", top_n=8)
    assert "SK-UDS-NRC" in {c["id"] for c in cands}


def test_retrieve_excludes_given_skill_ids():
    reg = SkillRegistry()
    cands = reg.retrieve("NRC 0x72 刷写", top_n=12, exclude=["SK-UDS-NRC"])
    assert "SK-UDS-NRC" not in {c["id"] for c in cands}


def test_retrieve_is_deterministic():
    reg = SkillRegistry()
    a = [c["id"] for c in reg.retrieve("power voltage 电压", top_n=5)]
    b = [c["id"] for c in reg.retrieve("power voltage 电压", top_n=5)]
    assert a == b


# --------------------------------------------------------------------- state
def test_state_mark_seen_returns_only_new_hashes():
    st = SessionState(session_id="s1", db_path="x")
    new1 = st.mark_seen(["a", "b", "a"])
    assert new1 == ["a", "b"]
    new2 = st.mark_seen(["a", "c"])
    assert new2 == ["c"]
    assert st.seen == {"a", "b", "c"}


def test_excluded_skills_includes_used_and_unproductive():
    st = SessionState(session_id="s1", db_path="x")
    st.used_skills = ["SK-A"]
    st.unproductive_skills = ["SK-B"]
    assert st.excluded_skills() == ["SK-A", "SK-B"]


def test_state_roundtrip_to_from_dict():
    st = SessionState(session_id="s1", db_path="x")
    st.mark_seen(["h1"])
    st.round_no = 2
    d = st.to_dict()
    st2 = SessionState.from_dict(d)
    assert st2.seen_row_hashes == ["h1"] and st2.round_no == 2


# --------------------------------------------------------------------- compress
def test_compressor_whitelists_error_lines_fully_under_cap():
    b = load_budget("poc")
    rows = [{"line_id": i, "row_hash": f"h{i}", "ts_utc": f"t{i:03d}", "level_norm": "ERROR",
            "raw_line": f"failed at step {i}", "template_id": 1} for i in range(3)]
    cr = EvidenceCompressor(b, {1: 3}).compress(rows)
    assert len(cr.kept) == 3
    assert cr.trace["folded_total"] == 0


def test_compressor_caps_whitelist_beyond_limit_and_folds_middle():
    b = load_budget("poc")
    cap = b.whitelist_cap_per_template
    rows = [{"line_id": i, "row_hash": f"h{i}", "ts_utc": f"t{i:04d}", "level_norm": "ERROR",
            "raw_line": f"failed at step {i}", "template_id": 1} for i in range(cap + 10)]
    cr = EvidenceCompressor(b, {1: cap + 10}).compress(rows, token_budget=10**9)
    assert len(cr.kept) == cap
    assert cr.trace["folded_total"] == 10


def test_compressor_exempts_rare_templates_entirely():
    b = load_budget("poc")
    rows = [{"line_id": i, "row_hash": f"h{i}", "ts_utc": f"t{i}", "level_norm": "INFO",
            "raw_line": "rare startup event", "template_id": 9} for i in range(3)]
    cr = EvidenceCompressor(b, {9: 3}).compress(rows)
    assert len(cr.kept) == 3   # rare_template_max_count=5 -> 全部豁免


def test_compressor_quotas_frequent_non_whitelisted_template():
    b = load_budget("poc")
    n = b.rare_template_max_count + 20
    rows = [{"line_id": i, "row_hash": f"h{i}", "ts_utc": f"t{i:04d}", "level_norm": "INFO",
            "raw_line": "heartbeat tick", "template_id": 5} for i in range(n)]
    cr = EvidenceCompressor(b, {5: n}).compress(rows, token_budget=10**9)
    assert len(cr.kept) == b.template_quota_lines
    assert cr.trace["folded_total"] == n - b.template_quota_lines


def test_compression_trace_reports_ratio_and_policy():
    b = load_budget("poc")
    rows = [{"line_id": 1, "row_hash": "h1", "ts_utc": "t1", "level_norm": "ERROR",
            "raw_line": "x failed", "template_id": 1}]
    cr = EvidenceCompressor(b, {1: 1}).compress(rows)
    assert 0 < cr.ratio <= 1.0
    assert "N3_whitelist_cap_per_template" in cr.trace["tier_policy"]


def test_slide_window_kicks_in_when_budget_too_small():
    b = load_budget("poc")
    rows = [{"line_id": i, "row_hash": f"h{i}", "ts_utc": f"2026-07-20T11:0{i%6}:00Z",
            "level_norm": "ERROR", "raw_line": f"failed badly at very specific step {i} " * 3,
            "template_id": i} for i in range(30)]
    cr = EvidenceCompressor(b, {i: 1 for i in range(30)}).compress(rows, token_budget=50)
    assert cr.tokens_after <= 50 or cr.windows
    assert cr.trace["slide_window_applied"] or cr.tokens_after <= 50


# --------------------------------------------------------------------- citations
def test_extract_citations_from_inline_and_trailer():
    text = 'claim one [[EV:aaaa1111bbbb2222]] more text\n<!-- citations: ["cccc3333dddd4444"] -->'
    cites = extract_citations(text)
    assert cites == ["aaaa1111bbbb2222", "cccc3333dddd4444"]


def test_verify_citations_flags_hash_not_in_evidence_set():
    rep = verify_citations("[[EV:deadbeef00000000]]", evidence_hashes=["cafebabe00000000"])
    assert not rep.ok
    assert rep.dangling[0]["reason"] == "NOT_IN_EVIDENCE_SET"


def test_verify_citations_accepts_known_hash():
    rep = verify_citations("[[EV:cafebabe00000000]]", evidence_hashes=["cafebabe00000000"])
    assert rep.ok and rep.valid == ["cafebabe00000000"]


def test_verify_citations_reports_unused_evidence():
    rep = verify_citations("[[EV:1111111111111111]]",
                           evidence_hashes=["1111111111111111", "2222222222222222"])
    assert rep.unused_evidence == ["2222222222222222"]


def test_strip_dangling_annotates_without_deleting_the_hash():
    out = strip_dangling("see [[EV:deadbeef]]", [{"row_hash": "deadbeef", "reason": "X"}])
    assert "deadbeef" in out and "⚠" in out


def test_verify_citations_checks_db_when_api_given(api):
    real = api._q("SELECT row_hash FROM log_lines LIMIT 1")[0]["row_hash"]
    rep = verify_citations(f"[[EV:{real}]]", evidence_hashes=[real], api=api)
    assert rep.ok
    rep2 = verify_citations("[[EV:0000000000000000]]", evidence_hashes=["0000000000000000"], api=api)
    assert not rep2.ok
    assert rep2.dangling[0]["reason"] == "NOT_FOUND_IN_DB"


def test_zero_citation_report_fails_gate():
    """METR-01/D-01/D-02：零引用必须 ok=False，dangling_rate 为 None。"""
    rep = CitationReport(total=0)
    assert rep.dangling_rate is None
    assert rep.has_citations is False
    assert rep.ok is False
    d = rep.to_dict()
    assert d["has_citations"] is False
    assert d["dangling_rate"] is None
    assert d["ok"] is False


def test_citation_report_ok_with_valid_and_no_dangling():
    rep = verify_citations("[[EV:cafebabe00000000]]", evidence_hashes=["cafebabe00000000"])
    assert rep.has_citations is True
    assert rep.dangling_rate == 0.0
    assert rep.ok is True
    assert rep.to_dict()["has_citations"] is True


def test_citation_report_not_ok_when_dangling():
    rep = verify_citations("[[EV:deadbeef00000000]]", evidence_hashes=["cafebabe00000000"])
    assert rep.has_citations is True
    assert rep.ok is False
    assert rep.dangling_rate > 0


def test_citation_coverage_empty_and_headings():
    assert citation_coverage("") == 1.0
    assert citation_coverage("# 标题\n\n---\n") == 1.0
    assert split_factual_sentences("# 标题\n事实句。") == ["事实句"]


def test_citation_coverage_counts_cited_sentences():
    text = "无引用句。有引用 [[EV:aaaa1111bbbb2222]]。"
    assert citation_coverage(text) == 0.5
    assert citation_coverage("全覆盖 [[EV:aaaa1111bbbb2222]]。") == 1.0


# --------------------------------------------------------------------- graph e2e
def test_agent_diagnoses_uds_nrc_case_correctly(built, tmp_path):
    g = AgentGraph(built["db"], workspace=tmp_path / "agent_ws", session_id="TEST-S3")
    try:
        res = g.run()
    finally:
        g.close()
    st = res.state
    assert st.status == "answered"
    assert st.root_cause["label"] == "uds_nrc_programming_failure"
    assert st.citation_check["dangling_rate"] == 0.0
    assert st.evidence_pack.get("merkle_root")


def test_agent_does_not_fabricate_root_cause_on_healthy_session(built_healthy, tmp_path):
    g = AgentGraph(built_healthy["db"], workspace=tmp_path / "agent_ws_healthy",
                   session_id="TEST-S0")
    try:
        res = g.run()
    finally:
        g.close()
    st = res.state
    assert st.root_cause.get("label") in (None, "no_fault_found", "undetermined")


def test_agent_never_reselects_used_skill_within_session(built, tmp_path):
    g = AgentGraph(built["db"], workspace=tmp_path / "agent_ws2", session_id="TEST-S3-b")
    try:
        res = g.run()
    finally:
        g.close()
    used = [r.selected_skill for r in res.state.rounds if r.selected_skill]
    assert len(used) == len(set(used)), f"技能被重复选中: {used}"
    assert res.metrics["counters"].get("plan.illegal_skill", 0) == 0


def test_agent_checkpoint_is_saved_after_run(built, tmp_path):
    ws = tmp_path / "agent_ws3"
    g = AgentGraph(built["db"], workspace=ws, session_id="TEST-CKPT")
    try:
        g.run()
    finally:
        g.close()
    from vela.agent.checkpoint import CheckpointStore
    store = CheckpointStore(ws / "sessions")
    loaded = store.load("TEST-CKPT")
    assert loaded is not None and loaded.status == "answered"


# --------------------------------------------------------------------- ORCH Wave 0 skeletons (xfail)
@dataclass
class _FakeCompressResult:
    kept: list
    trace: dict = field(default_factory=dict)
    tokens_after: int = 0
    ratio: float = 1.0
    windows: list = field(default_factory=list)


@pytest.mark.xfail(strict=True, reason="ORCH pending plan 03-04")
def test_plan_stop_rejected_round1(built, tmp_path):
    """ORCH-01: round_no==1 且模型 stop=True → plan.stop_rejected，最终 stop=False。"""

    class ForceStopGraph(AgentGraph):
        def _llm(self, logical: str, system: str, user: str) -> str:
            if logical == "planner":
                return json.dumps({
                    "thought": "尚无明细证据",
                    "selected_skill": None,
                    "actions": [],
                    "stop": True,
                    "reason": "证据不足",
                })
            return "{}"

    g = ForceStopGraph(built["db"], workspace=tmp_path / "orch01", session_id="ORCH-01")
    try:
        st = g.state
        st.round_no = 1
        plan = g.node_plan(st)
        assert g.metrics.counters.get("plan.stop_rejected", 0) >= 1
        assert any(e.kind == "plan.stop_rejected" for e in g.bus.since(0))
        assert plan["stop"] is False
    finally:
        g.close()


@pytest.mark.xfail(strict=True, reason="ORCH pending plan 03-02")
def test_parse_json_no_cross_span_and_retry_alert(built, tmp_path):
    """ORCH-03: 禁跨段花括号假成功；围栏 JSON 成功；耗尽重试后 llm.parse_failure ALERT。"""
    from vela.agent.graph import _parse_json

    cross = 'prefix noise {"selected_skill": null, "stop": true, "actions": []} trailing'
    assert _parse_json(cross) == {}, "跨段花括号不得解析为非空 dict"

    fenced = '```json\n{"selected_skill": "SK-A", "stop": false, "actions": []}\n```'
    assert _parse_json(fenced).get("selected_skill") == "SK-A"

    class BadJsonGraph(AgentGraph):
        def _llm(self, logical: str, system: str, user: str) -> str:
            return "NOT JSON at all {{{"

    g = BadJsonGraph(built["db"], workspace=tmp_path / "orch03", session_id="ORCH-03")
    try:
        assert hasattr(g, "_llm_json"), "应提供 _llm_json 统一解析重试"
        out = g._llm_json("planner", "sys", "user", retries=2)
        assert out == {}
        assert g.metrics.counters.get("llm.parse_failure", 0) >= 1
        assert any(e.kind == "llm.parse_failure" for e in g.bus.since(0))
    finally:
        g.close()


@pytest.mark.xfail(strict=True, reason="ORCH pending plan 03-05")
def test_verdict_norm_partial_decisive(built, tmp_path):
    """ORCH-05: Supported 可 decisive；≥2 条 partial 才 decisive；单条 partial/unsupported 否。"""

    err = {"row_hash": "aabbccddeeff0011", "raw_line": "NRC 0x72 erase failed",
           "level_norm": "ERROR", "line_id": 1, "ts_utc": "t1", "component": "uds_stack"}
    cr = _FakeCompressResult(kept=[err], trace={"tier_policy": []})

    def _verify(verdicts: list[dict]) -> dict:
        class VerifyGraph(AgentGraph):
            def _llm(self, logical: str, system: str, user: str) -> str:
                if logical == "verifier":
                    return json.dumps({"verdicts": verdicts})
                return "{}"

        g = VerifyGraph(built["db"], workspace=tmp_path / "orch05", session_id="ORCH-05")
        try:
            return g.node_verify(g.state, cr, "SK-UDS-NRC")
        finally:
            g.close()

    supported = _verify([{"claim_id": "C1", "status": "Supported",
                          "citations": [err["row_hash"]]}])
    assert supported["decisive"] is True

    two_partial = _verify([
        {"claim_id": "C1", "status": "partially_supported", "citations": [err["row_hash"]]},
        {"claim_id": "C2", "status": "partially-supported", "citations": [err["row_hash"]]},
    ])
    assert two_partial["decisive"] is True

    one_partial = _verify([{"claim_id": "C1", "status": "partial",
                            "citations": [err["row_hash"]]}])
    assert one_partial["decisive"] is False

    unsupported = _verify([{"claim_id": "C1", "status": "unsupported",
                            "citations": [err["row_hash"]]}])
    assert unsupported["decisive"] is False


@pytest.mark.xfail(strict=True, reason="ORCH pending plan 03-05")
def test_verify_claim_hypothesis_not_raw_line_loop(built, tmp_path):
    """ORCH-06: claims[0].claim 不得等于证据 raw_line 自证循环；应含技能根因假设语义。"""
    raw = "NRC received sid=0x36 nrc=0x72 generalProgrammingFailure"
    err = {"row_hash": "1122334455667788", "raw_line": raw, "level_norm": "ERROR",
           "line_id": 2, "ts_utc": "t2", "component": "uds_stack"}
    cr = _FakeCompressResult(kept=[err], trace={})

    class CaptureVerifyGraph(AgentGraph):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._last_user = ""

        def _llm(self, logical: str, system: str, user: str) -> str:
            self._last_user = user
            if logical == "verifier":
                return json.dumps({"verdicts": [
                    {"claim_id": "C1", "status": "supported",
                     "citations": [err["row_hash"]]}]})
            return "{}"

    g = CaptureVerifyGraph(built["db"], workspace=tmp_path / "orch06", session_id="ORCH-06")
    try:
        g.node_verify(g.state, cr, "SK-UDS-NRC")
        claims = (extract_state(g._last_user) or {}).get("claims") or []
        assert claims, "verifier 载荷应含 claims"
        claim_text = str(claims[0].get("claim") or "")
        assert claim_text != raw, "claim 不得等于证据 raw_line 自身"
        label = g.skills.label_of("SK-UDS-NRC") or ""
        hay = claim_text.lower()
        assert (
            "根因" in claim_text
            or "假设" in claim_text
            or (label and label.lower().replace("_", " ")[:12] in hay.replace("_", " "))
            or "uds" in hay
            or "programming" in hay
        ), "claim 应含技能根因假设语义"
    finally:
        g.close()


@pytest.mark.xfail(strict=True, reason="ORCH pending plan 03-03")
def test_excluded_skills_unproductive_only():
    """ORCH-07: excluded_skills 仅含 unproductive，used 可复用。"""
    st = SessionState(session_id="s1", db_path="x")
    st.used_skills = ["SK-A"]
    st.unproductive_skills = ["SK-B"]
    assert st.excluded_skills() == ["SK-B"]


@pytest.mark.xfail(strict=True, reason="ORCH pending plan 03-03")
def test_probe_dedup_same_args_skipped(built, tmp_path):
    """ORCH-07: 相同 (skill_id, args_hash) 探针第二次应跳过。"""
    import hashlib

    from vela.util.jsonl import canonical_json

    class DedupGraph(AgentGraph):
        def _llm(self, logical: str, system: str, user: str) -> str:
            if logical == "planner":
                return json.dumps({
                    "thought": "retry same probe",
                    "selected_skill": "SK-UDS-NRC",
                    "actions": [{"tool": "search_logs",
                                 "args": {"query": "NRC", "mode": "substring"}}],
                    "stop": False,
                    "reason": "",
                })
            return "{}"

    g = DedupGraph(built["db"], workspace=tmp_path / "orch07", session_id="ORCH-07")
    try:
        st = g.state
        assert hasattr(st, "executed_probes"), "SessionState 应有 executed_probes"
        args = {"query": "NRC", "mode": "substring"}
        key = f"SK-UDS-NRC:{hashlib.blake2b(canonical_json(args).encode('utf-8'), digest_size=8).hexdigest()}"
        st.executed_probes = [key]
        st.round_no = 2
        plan = g.node_plan(st)
        tools = [a.get("tool") for a in (plan.get("actions") or [])]
        assert "search_logs" not in tools, "同 args 探针应被去重跳过"
    finally:
        g.close()


@pytest.mark.xfail(strict=True, reason="ORCH pending plan 03-06")
def test_insufficient_citation_retry_then_status(built, tmp_path):
    """ORCH-08: 引用数 < 0.5*chain_len → 重试一次 → 仍不足则 status==insufficient_citation。"""

    class SparseReportGraph(AgentGraph):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self._reporter_calls = 0

        def _llm(self, logical: str, system: str, user: str) -> str:
            if logical == "reporter":
                self._reporter_calls += 1
                return "证据不足的叙述，几乎无引用。"
            return "{}"

    g = SparseReportGraph(built["db"], workspace=tmp_path / "orch08", session_id="ORCH-08")
    try:
        st = g.state
        st.evidence_pool = [
            {"row_hash": f"{i:016x}", "line_id": i, "level_norm": "ERROR",
             "raw_line": f"error line {i}", "ts_utc": f"t{i:02d}", "component": "uds_stack"}
            for i in range(1, 9)
        ]
        st.used_skills = ["SK-UDS-NRC"]
        g.node_report(st, "SK-UDS-NRC")
        assert g._reporter_calls >= 2, "引用不足应触发一次修复重试"
        assert st.status == "insufficient_citation"
    finally:
        g.close()


@pytest.mark.xfail(strict=True, reason="ORCH pending plan 03-06")
def test_unexplained_sweep_blocks_no_fault_found(built, tmp_path):
    """ORCH-09: 库有 ERROR 且 evidence_pool 无对应 row_hash → 禁 no_fault_found；samples 非空。"""
    g = AgentGraph(built["db"], workspace=tmp_path / "orch09", session_id="ORCH-09")
    try:
        st = g.state
        st.evidence_pool = []
        assert hasattr(g, "_unexplained_error_sweep"), "应提供未解释错误扫描"
        sweep = g._unexplained_error_sweep(st)
        samples = sweep.get("samples") or []
        assert 1 <= len(samples) <= 10
        g.node_report(st, None)
        label = (st.root_cause or {}).get("label")
        assert label != "no_fault_found"
        assert st.status == "insufficient_coverage" or label == "insufficient_coverage"
        ev_kinds = [e.kind for e in g.bus.since(0)]
        assert "coverage.unexplained_errors" in ev_kinds or samples
        unexplained_ev = next(
            (e for e in g.bus.since(0) if e.kind == "coverage.unexplained_errors"), None)
        if unexplained_ev is not None:
            payload_samples = unexplained_ev.payload.get("samples") or []
            assert 1 <= len(payload_samples) <= 10
    finally:
        g.close()


@pytest.mark.xfail(strict=True, reason="ORCH pending plan 03-03")
def test_generic_fallback_zero_score_inject(built, built_healthy, tmp_path):
    """ORCH-10: fallback_only 不进常规 retrieve；全零分+ERROR 注入 GENERIC；健康无 ERROR 不注入。"""
    reg = SkillRegistry()
    generic = next((s for s in reg.skills if s["id"] == "SK-GENERIC-EVIDENCE-FIRST"), None)
    assert generic is not None
    assert generic.get("fallback_only") is True
    cands = reg.retrieve("zzzz_unrelated_token_qqqq", top_n=20)
    assert "SK-GENERIC-EVIDENCE-FIRST" not in {c["id"] for c in cands}

    class ZeroScoreGraph(AgentGraph):
        def _llm(self, logical: str, system: str, user: str) -> str:
            if logical == "planner":
                return json.dumps({
                    "thought": "no match",
                    "selected_skill": None,
                    "actions": [],
                    "stop": True,
                    "reason": "候选全零分",
                })
            return "{}"

    g_err = ZeroScoreGraph(built["db"], workspace=tmp_path / "orch10e", session_id="ORCH-10E")
    try:
        st = g_err.state
        st.round_no = 1
        st.signals = {"abort_reason": "UDS_NRC_0x72", "fail_phase": "FLASH"}
        plan = g_err.node_plan(st)
        actions = plan.get("actions") or []
        skill = plan.get("skill")
        generic_probes = {p.get("tool") for p in reg.probes_of("SK-GENERIC-EVIDENCE-FIRST")}
        injected = (
            skill == "SK-GENERIC-EVIDENCE-FIRST"
            or bool(generic_probes & {a.get("tool") for a in actions})
        )
        assert injected, "全零分且存在 ERROR 信号时应注入 SK-GENERIC-EVIDENCE-FIRST"
    finally:
        g_err.close()

    g_ok = ZeroScoreGraph(built_healthy["db"], workspace=tmp_path / "orch10h",
                          session_id="ORCH-10H")
    try:
        st = g_ok.state
        st.round_no = 1
        st.signals = {}
        plan = g_ok.node_plan(st)
        assert plan.get("skill") != "SK-GENERIC-EVIDENCE-FIRST"
    finally:
        g_ok.close()
