"""共享夹具：整个测试会话只建一次小数据集与列式库。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
# 因果链：本文件在 pytest 加载 conftest 时执行，早于任何测试模块 import vela.*；
# 随后首次 import vela.config 触发 _load_dotenv_once()，因 override=False，.env
# 无法覆盖此处已写入的值——先无条件写死、再让 .env 以 override=False 加载，
# 既满足 ENV-01「测试也能读到凭证」，又杜绝付费真实 API 调用。
# 钉死仓库内 config/：.env 若指向别处，全部用例的配置基准（含 config_hash）漂移。
os.environ["VELA_CONFIG_DIR"] = str(ROOT / "config")
# 若保持 setdefault，用户 .env 中的 volcengine 会让全部既有用例打真实付费 API
# 且 determinism 类断言大面积失败。需要真实 LLM 的用例自行 monkeypatch.setenv
# 回 volcengine（Plan 07 的 realllm 用例即如此）。
os.environ["VELA_LLM_PROVIDER"] = "mock"
# .env.example 含 VELA_PROFILE=poc；用户若改为 production，预算断言基准即变化。
os.environ["VELA_PROFILE"] = "poc"
# 唯一保留 setdefault：PYTHONHASHSEED 必须在解释器启动前生效，运行期赋值对
# 哈希随机化无任何作用（真正生效点是 run_all.sh 的 export）；改成无条件赋值
# 会制造「运行期设它有用」的错觉。
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
