"""vela doctor 四项自检、双通道渲染、退出码分层与掩码一致性的回归护栏。"""
from __future__ import annotations

import json

from vela.cli import main

_DUMMY_KEY = "DUMMY-ARKKEY-0123456789ABCD"
_DUMMY_MODEL = "DUMMY-MODEL-001"
_GOOD_BASE = "https://ark.cn-beijing.volces.com/api/v3"
_BAD_BASE = "https://ark.cn-beijing.volces.com/api/plan/v3"


def _volcengine_env(monkeypatch, *, base_url: str = _GOOD_BASE,
                    api_key: str = _DUMMY_KEY, model: str = _DUMMY_MODEL) -> None:
    monkeypatch.setenv("VELA_LLM_PROVIDER", "volcengine")
    monkeypatch.setenv("VELA_ARK_BASE_URL", base_url)
    monkeypatch.setenv("VELA_ARK_API_KEY", api_key)
    monkeypatch.setenv("VELA_ARK_MODEL", model)


def test_doctor_default_mock_skips_network_and_exits_zero(capsys):
    rc = main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "已跳过网络探测" in out


def test_doctor_json_stdout_is_pure_json(capsys):
    rc = main(["doctor", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    for key in ("checks", "checks_passed", "local_ok", "provider",
                "config_hash", "dotenv"):
        assert key in data


def test_doctor_reports_four_logical_models(capsys):
    rc = main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    for name in ("planner", "verifier", "reporter", "distiller"):
        assert name in out


def test_doctor_offline_and_online_conflict_returns_two(capsys):
    rc = main(["doctor", "--offline", "--online"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "不能同时" in err


def test_doctor_masks_api_key_in_both_channels(monkeypatch, capsys):
    """人读与 --json 共用同一套已掩码 checks（D-18 / T-06-01）。"""
    _volcengine_env(monkeypatch)
    rc_h = main(["doctor", "--offline"])
    human = capsys.readouterr().out
    rc_j = main(["doctor", "--offline", "--json"])
    raw_json = capsys.readouterr().out
    assert rc_h == 0 and rc_j == 0
    for blob in (human, raw_json):
        assert _DUMMY_KEY not in blob
        assert "DUMM****ABCD" in blob


def test_doctor_bad_base_url_path_is_local_error_and_exits_one(monkeypatch, capsys):
    _volcengine_env(monkeypatch, base_url=_BAD_BASE)
    rc = main(["doctor", "--offline"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "/api/v3" in out


def test_doctor_connectivity_failure_does_not_change_exit_code(monkeypatch, capsys):
    """D-14 退出码分层是对本项目「失败即非零」主流惯例的有意偏离。

    消费方是 run_all.sh 的 set -euo pipefail：连通性失败必须返 0（仅标 ❌），
    否则一次限流/断网会中断整条演示链路。没有本断言，后续任何人「顺手改回
    非零」都不会被发现（对照 tests/test_cli_and_server.py:30-35 的注释惯例）。
    """
    _volcengine_env(monkeypatch)

    def _fail_probe(self, physical_model: str) -> dict:
        return {
            "reachable": False,
            "authenticated": False,
            "model_ok": False,
            "error_kind": "APIConnectionError",
            "detail": "端点不可达：stub",
        }

    monkeypatch.setattr(
        "vela.gateway.openai_compat.OpenAICompatProvider.probe", _fail_probe)
    rc = main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "❌" in out


def test_doctor_dotenv_report_shows_no_values(capsys):
    rc = main(["doctor", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    dotenv = data["dotenv"]
    assert set(dotenv) == {"path", "loaded", "keys", "shadowed"}
    # keys / shadowed 只含键名；整段 dotenv 序列化不得夹带进程中的密钥值
    dumped = json.dumps(dotenv, ensure_ascii=False)
    import os
    secret = os.environ.get("VELA_ARK_API_KEY", "")
    if secret and len(secret) >= 8:
        assert secret not in dumped
    for lst_key in ("keys", "shadowed"):
        assert isinstance(dotenv[lst_key], list)
        for name in dotenv[lst_key]:
            assert isinstance(name, str)
            assert "=" not in name
