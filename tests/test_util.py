"""工具层：哈希、ID、文本规范化、时间、JSONL。"""
from __future__ import annotations

import pytest

from vela.util.hashing import (fingerprint_algos, merkle_root, norm_hash, raw_hash,
                               row_hash, sha256_bytes)
from vela.util.ids import new_run_id, new_session_id, stable_id
from vela.util.jsonl import append_jsonl, canonical_json, read_json, read_jsonl, write_json
from vela.util.textutil import canonicalize, estimate_tokens, mask_secret, mask_vin, truncate
from vela.util.timeutil import bucket_seconds, floor_to_bucket, iso, parse_iso


def test_raw_hash_is_byte_exact():
    assert raw_hash(b"abc") == raw_hash(b"abc")
    assert raw_hash(b"abc") != raw_hash(b"abc ")
    assert len(raw_hash(b"abc")) == 32          # 128 bit -> 32 hex


def test_row_hash_binds_path_and_line():
    a = row_hash("same text", "/a/x.log", 10)
    b = row_hash("same text", "/a/x.log", 11)
    c = row_hash("same text", "/b/x.log", 10)
    assert a != b and a != c
    assert a == row_hash("same text", "/a/x.log", 10)
    assert len(a) == 16


def test_norm_hash_ignores_volatile_params():
    h1 = norm_hash(canonicalize("connect to 10.0.0.1:8080 took 231ms"))
    h2 = norm_hash(canonicalize("connect to 10.0.0.9:8080 took 998ms"))
    assert h1 == h2


def test_canonicalize_is_idempotent():
    s = canonicalize("id=0xDEADBEEF t=2026-07-20T11:00:00Z n=42")
    assert canonicalize(s) == s


def test_merkle_root_order_independent_but_salt_sensitive():
    d = ["a", "b", "c"]
    assert merkle_root(d, salt="s") == merkle_root(list(reversed(d)), salt="s")
    assert merkle_root(d, salt="s") != merkle_root(d, salt="t")


def test_merkle_root_detects_tamper():
    assert merkle_root(["a", "b"], salt="s") != merkle_root(["a", "B"], salt="s")


def test_sha256_bytes_known_vector():
    assert sha256_bytes(b"") == ("e3b0c44298fc1c149afbf4c8996fb924"
                                 "27ae41e4649b934ca495991b7852b855")


def test_fingerprint_algos_reported():
    algos = fingerprint_algos()
    assert set(algos) == {"raw_hash", "norm_hash", "row_hash"}


def test_ids_are_deterministic_with_seed():
    assert new_run_id("seed-a") == new_run_id("seed-a")
    assert new_run_id("seed-a") != new_run_id("seed-b")
    assert stable_id("EV", "x", "y") == stable_id("EV", "x", "y")


def test_session_id_is_unique():
    assert new_session_id() != new_session_id()


def test_estimate_tokens_cjk_costs_more_per_char():
    assert estimate_tokens("车" * 40) > estimate_tokens("a" * 40)
    assert estimate_tokens("") == 0


def test_mask_vin_keeps_last4_and_hides_rest():
    vin = "LSVM3HNR4SC988574"
    m = mask_vin(vin)
    assert m.endswith("8574") and vin not in m


def test_mask_secret_empty_returns_empty():
    assert mask_secret("") == ""


def test_mask_secret_short_fully_masked():
    assert mask_secret("short") == "****"


def test_mask_secret_prefix_suffix_and_fixed_stars():
    sample = "DUMMY-KEY-0123456789ABCD"
    m = mask_secret(sample)
    assert m == "DUMM****ABCD"
    assert m.count("*") == 4
    assert "0123456789" not in m


def test_mask_secret_keep_overrides_threshold():
    sample = "DUMMY-ABCDEFGHIJKLMNOP"
    # keep=6 → 阈值 16；长度 20 ≥ 16 → 前 6 + **** + 后 6
    assert mask_secret(sample, keep=6) == "DUMMY-****KLMNOP"
    assert mask_secret("DUMMY-SHORT", keep=6) == "****"  # len 11 < 16


def test_truncate_reports_whether_it_cut():
    assert truncate("abcdef", 4) == ("abcd", True)
    assert truncate("abc", 10) == ("abc", False)


def test_iso_and_parse_roundtrip():
    dt = parse_iso("2026-07-20T11:00:00Z")
    assert dt is not None
    assert iso(dt).startswith("2026-07-20T11:00:00")


def test_parse_iso_rejects_garbage():
    assert parse_iso("not-a-time") is None


@pytest.mark.parametrize("spec,sec", [("1s", 1), ("10s", 10), ("30s", 30),
                                     ("1m", 60), ("5m", 300), ("1h", 3600)])
def test_bucket_seconds(spec, sec):
    assert bucket_seconds(spec) == sec


def test_floor_to_bucket_is_monotone():
    a = parse_iso("2026-07-20T11:00:59Z")
    b = parse_iso("2026-07-20T11:01:01Z")
    assert floor_to_bucket(a, "1m") < floor_to_bucket(b, "1m")


def test_canonical_json_is_stable_across_key_order():
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})


def test_jsonl_roundtrip(tmp_path):
    p = tmp_path / "x.jsonl"
    append_jsonl(p, {"a": 1})
    append_jsonl(p, {"a": 2})
    assert [r["a"] for r in read_jsonl(p)] == [1, 2]


def test_write_json_is_atomic_and_readable(tmp_path):
    p = tmp_path / "d" / "x.json"
    write_json(p, {"k": "值"})
    assert read_json(p)["k"] == "值"
    assert not list(p.parent.glob("*.tmp"))
