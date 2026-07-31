"""METR-09 基线产物 schema 检查（付费路径；默认 addopts 排除）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.realllm

BASE = Path(".planning/phases/02-metrics-baseline/baseline")


def test_baseline_result_schema_if_present():
    p = BASE / "result.json"
    if not p.is_file():
        pytest.skip("baseline/result.json 尚未生成（待 make baseline）")
    data = json.loads(p.read_text(encoding="utf-8"))
    meta = data.get("meta") or data
    assert "config_hash" in meta or "config_hash" in data
    n = meta.get("n") or meta.get("repeat") or data.get("n")
    assert n is None or int(n) >= 3
    assert (BASE / "report.md").is_file()
