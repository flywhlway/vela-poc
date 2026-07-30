"""证据平面：解包安全、发现、解析、时间归一、模板、建库、QA。"""
from __future__ import annotations

import zipfile

import pytest

from vela.evidence.discover import detect_encoding
from vela.evidence.models import LOG_LINES_SCHEMA, empty_row
from vela.evidence.parsers import ParserRegistry
from vela.evidence.template import MiniDrain
from vela.evidence.timeline import TS_MONO, TS_WALL, compute_ts_confidence
from vela.evidence.unpack import UnsafeArchiveError, extract


def test_zip_slip_is_rejected(tmp_path):
    z = tmp_path / "evil.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("../../etc/passwd", "x")
    with pytest.raises(UnsafeArchiveError):
        extract(z, tmp_path / "out")


def test_normal_archive_unpacks(tmp_path):
    z = tmp_path / "ok.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("logs/a.log", "hello\n")
    r = extract(z, tmp_path / "out")
    assert r.archive_sha256 and (tmp_path / "out" / "logs" / "a.log").exists()


def test_detect_encoding_prefers_utf8_then_gb18030(tmp_path):
    p = tmp_path / "cn.log"
    p.write_bytes("存储空间不足\n".encode("gb18030"))
    enc, conf, is_bin = detect_encoding(p, ["utf-8", "gb18030", "latin-1"])
    assert enc == "gb18030" and not is_bin
    p2 = tmp_path / "u.log"
    p2.write_text("空间不足\n", encoding="utf-8")
    enc2, _, _ = detect_encoding(p2, ["utf-8", "gb18030", "latin-1"])
    assert enc2 == "utf-8"


def test_empty_row_matches_schema_exactly():
    assert set(empty_row()) == {f.name for f in LOG_LINES_SCHEMA}


def test_schema_has_row_hash_and_byte_anchors():
    names = {f.name for f in LOG_LINES_SCHEMA}
    for col in ("row_hash", "raw_hash", "norm_hash", "byte_offset", "byte_len",
                "ts_confidence", "ts_kind", "ota_phase", "template_id"):
        assert col in names


@pytest.mark.parametrize("line,parser", [
    ("2026-07-20 19:33:38.970 [ota_master] ERROR campaign aborted", "iso_bracket_comp"),
    ("07-20 19:33:38.970  1420  1451 E OtaDl: download failed", "logcat_threadtime"),
    ("[   12.345678] EXT4-fs (mmcblk0p12): no space left", "dmesg_monotonic"),
])
def test_parser_registry_picks_expected_parser(line, parser):
    reg = ParserRegistry()
    res = reg.parse(line)
    assert res.parser_name == parser, f"{line!r} -> {res.parser_name}"


def test_parser_falls_back_without_crashing():
    res = ParserRegistry().parse("!!! not a log line at all !!!")
    assert res.parser_name and res.message


def test_minidrain_clusters_same_shape_lines():
    d = MiniDrain(sim_threshold=0.4, max_depth=4, max_children=100, max_clusters=100)
    a = d.add("download chunk 12 failed after 3 retries")
    b = d.add("download chunk 88 failed after 9 retries")
    c = d.add("signature verification failed for package")
    assert a == b and a != c


def test_minidrain_summary_is_sorted_by_id():
    d = MiniDrain(sim_threshold=0.4, max_depth=4, max_children=100, max_clusters=100)
    for i in range(20):
        d.add(f"line variant {i} of some template")
        d.add(f"other kind of message {i}")
    ids = [c["template_id"] for c in d.summary()]
    assert ids == sorted(ids)


def test_minidrain_marks_error_like_templates():
    d = MiniDrain()
    d.add("erase sector failed at block N hal_status=-5")
    d.add("heartbeat ok interval=30s")
    flags = {c["template_text"]: c["is_error_like"] for c in d.summary()}
    assert any(v for k, v in flags.items() if "failed" in k)
    assert not any(v for k, v in flags.items() if "heartbeat" in k)


def test_ts_confidence_ranks_wall_above_monotonic():
    hi = compute_ts_confidence(kind=TS_WALL, has_tz=True, has_year=True, precision_digits=3)
    lo = compute_ts_confidence(kind=TS_MONO, has_tz=False, has_year=False, precision_digits=6)
    assert 0 < lo < hi <= 1.0


def test_ts_confidence_penalises_missing_tz_and_year():
    full = compute_ts_confidence(kind=TS_WALL, has_tz=True, has_year=True, precision_digits=3)
    partial = compute_ts_confidence(kind=TS_WALL, has_tz=False, has_year=False, precision_digits=3)
    assert partial < full


def test_ts_confidence_penalises_broken_monotonic_ordering():
    ok = compute_ts_confidence(kind=TS_MONO, has_tz=False, has_year=False,
                               precision_digits=6, monotonic_ok=True)
    broken = compute_ts_confidence(kind=TS_MONO, has_tz=False, has_year=False,
                                   precision_digits=6, monotonic_ok=False)
    assert broken < ok


def test_ts_confidence_scales_with_anchor_confidence():
    strong = compute_ts_confidence(kind=TS_MONO, has_tz=False, has_year=False,
                                   precision_digits=6, anchor_conf=1.0)
    weak = compute_ts_confidence(kind=TS_MONO, has_tz=False, has_year=False,
                                 precision_digits=6, anchor_conf=0.5)
    assert weak < strong


def test_build_produces_all_layers(built):
    r = built["result"]
    assert r.total_records > 0
    assert (built["ws"] / "bronze").exists() and (built["ws"] / "silver").exists()
    assert built["db"].exists()
    assert r.total_files >= 5


def test_unparsed_ratio_is_tiny(built):
    r = built["result"]
    assert r.unparsed_records / max(1, r.total_records) < 0.05


def test_qa_report_all_checks_pass(built):
    import json
    qa = json.loads((built["ws"] / "qa" / "qa_report.json").read_text(encoding="utf-8"))
    failed = [c["name"] for c in qa["checks"] if not c["ok"]]
    assert not failed, f"QA 未通过: {failed}"
    assert len(qa["checks"]) >= 7


def test_line_id_is_dense_and_unique(api):
    row = api._q("SELECT count(*) n, count(DISTINCT line_id) d, min(line_id) lo, "
                 "max(line_id) hi FROM log_lines")[0]
    assert row["n"] == row["d"]
    assert row["hi"] - row["lo"] + 1 == row["n"]   # 稠密：无空洞（起始基准由 writer 决定）


def test_every_row_has_row_hash(api):
    assert api._q("SELECT count(*) n FROM log_lines WHERE row_hash IS NULL")[0]["n"] == 0


def test_ota_phase_is_forward_filled(api):
    n = api._q("SELECT count(*) n FROM log_lines WHERE ota_phase IS NOT NULL")[0]["n"]
    assert n > 0


def test_multiple_parsers_actually_used(api):
    rows = api._q("SELECT parser_name, count(*) n FROM log_lines GROUP BY 1")
    assert len(rows) >= 5


def test_gb18030_content_decoded_correctly(api):
    n = api._q("SELECT count(*) n FROM log_lines WHERE raw_line LIKE '%文件系统%' "
               "OR raw_line LIKE '%空间%'")[0]["n"]
    assert n > 0
