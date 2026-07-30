"""共享夹具：整个测试会话只建一次小数据集与列式库。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("VELA_CONFIG_DIR", str(ROOT / "config"))
os.environ.setdefault("VELA_LLM_PROVIDER", "mock")
os.environ.setdefault("VELA_PROFILE", "poc")
os.environ.setdefault("PYTHONHASHSEED", "0")

SMALL = dict(density=2, chunks=140, blocks=60)   # 小数据集：单用例秒级完成


@pytest.fixture(scope="session")
def tmp_root(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("vela")


@pytest.fixture(scope="session")
def dataset(tmp_root) -> dict:
    """生成三个场景（含健康负样本）的小数据集。"""
    from vela.sim.generate import generate_dataset
    out = tmp_root / "dataset"
    truths = generate_dataset(out, scenarios=["S0_HEALTHY", "S3_UDS_NRC72", "S5_STORAGE_FULL"],
                              **SMALL)
    return {"dir": out, "truths": {t["scenario_id"]: t for t in truths}}


@pytest.fixture(scope="session")
def built(dataset, tmp_root) -> dict:
    """把 S3（UDS NRC 故障）建成列式库，供查询/Agent/证据链用例复用。"""
    from vela.evidence.pipeline import build
    t = dataset["truths"]["S3_UDS_NRC72"]
    archive = dataset["dir"] / t["archive"]
    ws = tmp_root / "ws_s3"
    res = build(archive, ws, progress=False)
    return {"result": res, "ws": ws, "archive": archive, "db": ws / "gold" / "analysis.duckdb",
            "truth": t}


@pytest.fixture(scope="session")
def built_healthy(dataset, tmp_root) -> dict:
    from vela.evidence.pipeline import build
    t = dataset["truths"]["S0_HEALTHY"]
    archive = dataset["dir"] / t["archive"]
    ws = tmp_root / "ws_s0"
    res = build(archive, ws, progress=False)
    return {"result": res, "ws": ws, "archive": archive, "db": ws / "gold" / "analysis.duckdb",
            "truth": t}


@pytest.fixture
def api(built):
    from vela.query.api import LogQueryAPI
    a = LogQueryAPI(built["db"])
    yield a
    a.close()
