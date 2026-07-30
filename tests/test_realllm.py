"""ENV-02 真实火山引擎方舟端到端验收。

会产生真实付费 API 调用；默认被 pyproject.toml 的
``addopts = "... -m 'not realllm'"`` 排除，只有显式
``VELA_LLM_PROVIDER=volcengine pytest -m realllm`` 才运行。

凭证来自 ``.env`` 自动加载（Plan 03 / D-06，``override=False``），
无需手工 ``export``——这正是 ENV-01 在测试侧成立的证明。
断言范围严格限定为 ROADMAP 成功判据 2：链路跑完 + 报告非空 +
至少一个 ``[[EV:row_hash]]`` 引用；**不断言诊断结论正确**。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from vela.agent.citations import CITE_RX
from vela.cli import main

pytestmark = pytest.mark.realllm

SESSION_ID = "REALLLM-ENV02"


@pytest.fixture(autouse=True)
def _require_real_ark_credentials():
    """缺凭证时 skip（非 fail），保证零网络调用。"""
    if not os.environ.get("VELA_ARK_API_KEY") or not os.environ.get("VELA_ARK_MODEL"):
        pytest.skip(
            "未配置真实火山引擎凭证（VELA_ARK_API_KEY / VELA_ARK_MODEL），"
            "跳过 ENV-02 实测"
        )


def test_real_llm_diagnose_produces_cited_report(built, tmp_path, monkeypatch, capsys):
    """真实 LLM 下 diagnose 链路通：rc∈{0,3}、报告非空、含引用。"""
    # conftest 无条件锁 VELA_LLM_PROVIDER=mock（D-11）；真实用例自行改回。
    monkeypatch.setenv("VELA_LLM_PROVIDER", "volcengine")
    ws = tmp_path / "realllm_ws"
    rc = main([
        "agent", "diagnose",
        "--db", str(built["db"]),
        "--workspace", str(ws),
        "--session-id", SESSION_ID,
    ])
    captured = capsys.readouterr()
    # D-19：只要求链路不因环境问题中途报错；answered→0，未作答但走完→3。
    assert rc in (0, 3), f"诊断异常终止 rc={rc}"

    # AgentGraph 经 CheckpointStore 落盘到 workspace/sessions/<id>.state.json
    state_path = Path(ws) / "sessions" / f"{SESSION_ID}.state.json"
    assert state_path.is_file(), f"会话检查点未落盘: {state_path}"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    report_text = (state.get("report_md") or "").strip()
    if not report_text:
        # cmd_agent 同步 print(st.report_md)；不把 capsys 写入任何持久化文件
        report_text = captured.out.strip()

    assert len(report_text) > 0, "诊断报告为空"
    assert CITE_RX.search(report_text) is not None, (
        "报告缺少至少一个 [[EV:row_hash]] 引用"
    )


def test_real_llm_doctor_connectivity_all_green(monkeypatch, capsys):
    """真实凭证下 doctor --json：local_ok、provider=volcengine、已探测。"""
    monkeypatch.setenv("VELA_LLM_PROVIDER", "volcengine")
    rc = main(["doctor", "--json"])
    out = capsys.readouterr().out
    assert rc in (0, 1), f"doctor 异常终止 rc={rc}"
    data = json.loads(out)
    assert data["local_ok"] is True
    assert data["provider"] == "volcengine"
    assert data["probed"] is True
