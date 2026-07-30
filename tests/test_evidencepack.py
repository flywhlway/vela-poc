"""证据链平面：Merkle 构建、三级验证（L0/L1/L2）、快照双源解析。"""
from __future__ import annotations

from vela.evidencepack.builder import EvidenceBuilder, item_digest
from vela.evidencepack.snapshot import SnapshotStore, resolve_citation
from vela.evidencepack.verifier import verify_all, verify_l0, verify_l1, verify_l2


def _build_pack(api):
    s = api.call("search_logs", query="NRC", mode="substring", min_level="ERROR", limit=4)
    items = [{"line_id": r["line_id"], "role": "TRIGGER" if i == 0 else "CAUSE"}
             for i, r in enumerate(s.rows)]
    return EvidenceBuilder(api).build(claim="测试用证据包", items=items, include_context=3)


def test_item_digest_is_stable_and_ignores_raw_line():
    a = {"row_hash": "h1", "raw_hash_b3_128": "r1", "seq": 1, "raw_line": "text A"}
    b = {"row_hash": "h1", "raw_hash_b3_128": "r1", "seq": 1, "raw_line": "text B (different!)"}
    assert item_digest(a) == item_digest(b)


def test_item_digest_changes_with_row_hash():
    a = {"row_hash": "h1", "raw_hash_b3_128": "r1", "seq": 1}
    b = {"row_hash": "h2", "raw_hash_b3_128": "r1", "seq": 1}
    assert item_digest(a) != item_digest(b)


def test_build_evidence_produces_valid_pack(api):
    pack = _build_pack(api)
    assert pack["merkle_root"] and pack["evidence_id"]
    assert pack["items"] and all(i["role"] in ("TRIGGER", "CAUSE") for i in pack["items"])
    assert pack["run"]["config_hash"].startswith("sha256:")


def test_evidence_pack_written_to_disk(api):
    pack = _build_pack(api)
    from pathlib import Path
    assert Path(pack["_path"]).exists()


def test_l0_self_consistency_passes_on_untampered_pack(api):
    pack = _build_pack(api)
    r = verify_l0(pack)
    assert r["ok"] and r["level"] == "L0"


def test_l0_detects_tampered_pack(api):
    pack = _build_pack(api)
    pack["items"][0]["raw_line"] = "被篡改的内容 tampered content injected"
    pack["items"][0]["row_hash"] = "0000000000000000"     # 篡改引用锚点本身
    r = verify_l0(pack)
    assert not r["ok"]


def test_l1_passes_against_live_db(api):
    pack = _build_pack(api)
    r = verify_l1(pack, api.con)
    assert r["ok"] and not r["failures"]


def test_l1_detects_dangling_row_hash(api):
    pack = _build_pack(api)
    pack["items"][0]["row_hash"] = "ffffffffffffffff"
    r = verify_l1(pack, api.con)
    assert not r["ok"]
    assert r["failures"][0]["reason"] == "ROW_HASH_NOT_FOUND_IN_DB"


def test_l2_verifies_against_original_archive(api, built):
    pack = _build_pack(api)
    r = verify_l2(pack, built["archive"])
    assert r["ok"] and r["checked"] == len(pack["items"])


def test_l2_detects_hash_mismatch_against_archive(api, built):
    pack = _build_pack(api)
    pack["items"][0]["raw_hash_b3_128"] = "0" * 32
    r = verify_l2(pack, built["archive"])
    assert not r["ok"]
    assert r["failures"][0]["reason"] == "HASH_MISMATCH"


def test_verify_all_runs_all_three_levels(api, built):
    pack = _build_pack(api)
    r = verify_all(pack, con=api.con, archive_path=built["archive"])
    assert r["ok"]
    assert {lv["level"] for lv in r["levels"]} == {"L0", "L1", "L2"}


# --------------------------------------------------------------- snapshot
def test_snapshot_freeze_and_load_roundtrip(api, tmp_path):
    s = api.call("search_logs", query="NRC", mode="substring", limit=3)
    hashes = [r["row_hash"] for r in s.rows]
    store = SnapshotStore(tmp_path / "snap")
    doc = store.freeze("REPORT-1", api, hashes, context_k=2)
    assert doc["count"] == len(hashes)
    loaded = store.load("REPORT-1")
    assert loaded and loaded["count"] == len(hashes)


def test_resolve_citation_prefers_live_source(api):
    s = api.call("search_logs", query="NRC", mode="substring", limit=1)
    h = s.rows[0]["row_hash"]
    r = resolve_citation(h, api=api)
    assert r["source"] == "live" and r["resolvable"]


def test_resolve_citation_falls_back_to_snapshot_when_live_unavailable(api, tmp_path):
    s = api.call("search_logs", query="NRC", mode="substring", limit=1)
    h = s.rows[0]["row_hash"]
    store = SnapshotStore(tmp_path / "snap2")
    snap = store.freeze("REPORT-2", api, [h], context_k=1)
    r = resolve_citation(h, api=None, snapshot=snap)      # 模拟原库已不可用
    assert r["source"] == "snapshot" and r["resolvable"]
    assert "过期" in r["note"] or "删除" in r["note"]


def test_resolve_citation_reports_unresolvable_when_nothing_available():
    r = resolve_citation("deadbeef00000000", api=None, snapshot=None)
    assert not r["resolvable"] and r["source"] == "none"


def test_snapshot_records_unresolvable_hash(api, tmp_path):
    store = SnapshotStore(tmp_path / "snap3")
    doc = store.freeze("REPORT-3", api, ["0000000000000000"])
    assert doc["snapshots"]["0000000000000000"]["resolvable"] is False
