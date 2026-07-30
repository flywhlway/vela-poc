"""推理平面：技能召回、压缩痕迹、引用校验、七节点图端到端。"""
from __future__ import annotations

from vela.agent.citations import extract_citations, strip_dangling, verify_citations
from vela.agent.compress import EvidenceCompressor
from vela.agent.graph import AgentGraph
from vela.agent.skills import SkillRegistry
from vela.agent.state import SessionState
from vela.config import load_budget


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
