"""CLI 子命令 + 本地服务路由（不依赖 FastAPI 是否安装，走内部 _handle 分发）。"""
from __future__ import annotations

import json

from vela.cli import build_parser, main


def test_cli_doctor_runs_and_reports_ok(capsys):
    rc = main(["doctor"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "config_hash" in out


def test_cli_sim_list_prints_all_scenarios(capsys):
    rc = main(["sim", "generate", "--list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "S3_UDS_NRC72" in out and "S0_HEALTHY" in out


def test_cli_query_list_prints_tool_catalog(capsys):
    rc = main(["query", "--list"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "describe_dataset" in out and "run_sql" in out


def test_cli_build_command_produces_parseable_qa_json(dataset, tmp_path, capsys):
    """回归用例：build_report() 曾经把 Markdown 路径错当 JSON 路径返回，
    导致 `vela build` 在真实 CLI 路径上对每一次建库都必然抛出 JSONDecodeError。
    build()/BuildResult 的 Python 单元测试从未触发这条路径（它们直接构造对象，
    不经过 CLI 的 json.loads(r.qa_report) 调用），只有端到端调用 cli.main(["build",...])
    才能捕获此类"字段名对但指向错误产物"的问题。"""
    archive = dataset["dir"] / dataset["truths"]["S5_STORAGE_FULL"]["archive"]
    rc = main(["build", str(archive), str(tmp_path / "cli_build_ws")])
    out = capsys.readouterr().out
    assert rc == 0
    assert "全部通过" in out or "未通过" in out
    assert (tmp_path / "cli_build_ws" / "qa" / "qa_report.json").exists()
    assert (tmp_path / "cli_build_ws" / "qa" / "qa_report.md").exists()


def test_cli_build_and_query_roundtrip(built, capsys):
    rc = main(["query", "--db", str(built["db"]), "--tool", "describe_dataset"])
    out = capsys.readouterr().out
    assert rc == 0
    data = json.loads(out)
    assert data["ok"] and data["summary"]["total_records"] > 0


def test_cli_query_unknown_tool_returns_nonzero(capsys):
    rc = main(["query", "--db", "x", "--tool", "nope"])
    assert rc == 2


def test_cli_agent_diagnose_end_to_end(built, tmp_path, capsys):
    rc = main(["agent", "diagnose", "--db", str(built["db"]),
              "--workspace", str(tmp_path / "cli_agent_ws"),
              "--session-id", "CLI-TEST"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "uds_nrc_programming_failure" in out


def test_cli_evidence_verify_roundtrip(built, tmp_path, capsys):
    main(["agent", "diagnose", "--db", str(built["db"]),
         "--workspace", str(tmp_path / "cli_agent_ws2"), "--session-id", "CLI-EV"])
    capsys.readouterr()
    import glob
    # 证据包与被引用的字节偏移/文件路径强绑定，因此落盘位置跟随数据库自身的
    # 构建工作区（db 路径的上上级目录），而不是本次诊断会话传入的 --workspace。
    packs = glob.glob(str(built["ws"] / "evidence" / "*.json"))
    assert packs
    rc = main(["evidence", "verify", "--pack", packs[0],
              "--db", str(built["db"]), "--archive", str(built["archive"])])
    out = capsys.readouterr().out
    assert rc == 0
    assert "通过" in out


def test_build_parser_exposes_all_subcommands():
    ap = build_parser()
    sub_dest = {a.dest: a for a in ap._subparsers._group_actions}
    choices = sub_dest["cmd"].choices
    for cmd in ("sim", "build", "query", "agent", "eval", "evidence", "serve", "doctor"):
        assert cmd in choices


# --------------------------------------------------------------- server
def test_server_handle_health_and_tools(built):
    from vela.server.app import _handle, _STATE
    _STATE["db"] = str(built["db"])
    _STATE["ws"] = str(built["ws"])
    code, data = _handle("/health", {})
    assert code == 200 and data["ok"]
    code, data = _handle("/tools", {})
    assert code == 200 and len(data["tools"]) == 12


def test_server_handle_call_describe_dataset(built):
    from vela.server.app import _handle, _STATE
    _STATE["db"] = str(built["db"])
    _STATE["ws"] = str(built["ws"])
    code, data = _handle("/call", {"tool": "describe_dataset", "args": {}})
    assert code == 200 and data["ok"]


def test_server_handle_call_unknown_tool_returns_400(built):
    from vela.server.app import _handle, _STATE
    _STATE["db"] = str(built["db"])
    code, data = _handle("/call", {"tool": "nope"})
    assert code == 400


def test_server_handle_unknown_path_returns_404():
    from vela.server.app import _handle
    code, data = _handle("/nope", {})
    assert code == 404


def test_build_app_returns_none_or_fastapi_instance(built):
    from vela.server.app import build_app
    app = build_app(str(built["db"]), str(built["ws"]))
    assert app is None or hasattr(app, "routes")
