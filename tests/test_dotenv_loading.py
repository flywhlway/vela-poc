""".env 五层优先级链、项目根锚点定位、加载静默性与测试作用域锁定的回归护栏。"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


def test_existing_process_env_wins_over_dotenv(tmp_path, monkeypatch):
    monkeypatch.setenv("VELA_TEST_TOKEN", "from-process")
    (tmp_path / ".env").write_text("VELA_TEST_TOKEN=DUMMY-from-dotenv\n", encoding="utf-8")
    from vela.config import _apply_dotenv

    result = _apply_dotenv(tmp_path)
    assert os.environ["VELA_TEST_TOKEN"] == "from-process"
    assert "VELA_TEST_TOKEN" in result["shadowed"]


def test_dotenv_fills_absent_variable(tmp_path, monkeypatch):
    monkeypatch.delenv("VELA_TEST_ONLY", raising=False)
    (tmp_path / ".env").write_text("VELA_TEST_ONLY=DUMMY-filled\n", encoding="utf-8")
    from vela.config import _apply_dotenv

    result = _apply_dotenv(tmp_path)
    assert os.environ["VELA_TEST_ONLY"] == "DUMMY-filled"
    assert "VELA_TEST_ONLY" in result["keys"]
    monkeypatch.delenv("VELA_TEST_ONLY", raising=False)


def test_shadowed_keys_are_reported(tmp_path, monkeypatch):
    monkeypatch.setenv("VELA_TEST_TOKEN", "from-process")
    (tmp_path / ".env").write_text(
        "VELA_TEST_TOKEN=DUMMY-from-dotenv\nVELA_TEST_OTHER=DUMMY-other\n",
        encoding="utf-8",
    )
    from vela.config import _apply_dotenv

    result = _apply_dotenv(tmp_path)
    assert "VELA_TEST_TOKEN" in result["shadowed"]
    assert set(result["keys"]) == {"VELA_TEST_OTHER", "VELA_TEST_TOKEN"}
    monkeypatch.delenv("VELA_TEST_OTHER", raising=False)


def test_find_project_root_hits_pyproject_anchor(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='t'\n", encoding="utf-8")
    nested = tmp_path / "src" / "vela"
    nested.mkdir(parents=True)
    from vela.config import _find_project_root

    assert _find_project_root(nested) == tmp_path.resolve()


def test_find_project_root_returns_none_without_anchor(tmp_path):
    nested = tmp_path / "site-packages" / "vela"
    nested.mkdir(parents=True)
    from vela.config import _find_project_root

    assert _find_project_root(nested) is None


def test_apply_dotenv_is_silent(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("VELA_TEST_SILENT", raising=False)
    (tmp_path / ".env").write_text("VELA_TEST_SILENT=DUMMY-quiet\n", encoding="utf-8")
    from vela.config import _apply_dotenv

    _apply_dotenv(tmp_path)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
    monkeypatch.delenv("VELA_TEST_SILENT", raising=False)


def test_apply_dotenv_noop_when_root_is_none():
    from vela.config import _apply_dotenv

    result = _apply_dotenv(None)
    assert result["loaded"] is False
    assert result["path"] is None
    assert result["keys"] == []
    assert result["shadowed"] == []


def test_conftest_locks_provider_to_mock():
    """回归用例：.env 在 pytest 收集期就会灌进 os.environ；若 conftest 用
    setdefault，177 个既有用例会全部改打真实付费 API 且 determinism 用例大面积失败。
    这是任何单个业务单元测试都抓不到的结构性漏洞——只有本断言能钉死
    VELA_LLM_PROVIDER 在测试会话中恒为 mock。"""
    assert os.environ["VELA_LLM_PROVIDER"] == "mock"


def test_dotenv_report_does_not_leak_values():
    from vela.config import dotenv_report

    report = dotenv_report()
    assert set(report) <= {"path", "loaded", "keys", "shadowed"}


def test_dotenv_report_returns_shallow_copy():
    from vela.config import dotenv_report

    report = dotenv_report()
    report["keys"] = ["MUTATED"]
    again = dotenv_report()
    assert again.get("keys") != ["MUTATED"]
