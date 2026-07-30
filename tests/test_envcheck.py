"""环境变量形态检查（EnvChecker）：规则注入、掩码与 provider 必填性护栏。"""
from __future__ import annotations

from vela.envcheck import EnvChecker

# 最小可注入规则表——与 config/env_checks.yaml schema 对齐，不读真实文件
_CFG = {
    "version": "1.0",
    "value_hygiene": [
        {
            "name": "inline_comment_residue",
            "pattern": r"\s+#",
            "hint": (
                "值内含疑似行尾注释残留；python-dotenv 只会剥离未加引号值的"
                "行尾注释，加引号的值不会被剥离——请把注释移到变量上一行"
            ),
        },
        {
            "name": "edge_whitespace",
            "pattern": r"^\s|\s$",
            "hint": "值首尾含空白——请去掉多余空格",
        },
        {
            "name": "wrapping_quotes",
            "pattern": r"^['\"].*['\"]$",
            "hint": "值被成对引号包裹，引号会成为值的一部分——请去掉外层引号",
        },
    ],
    "variables": [
        {
            "name": "VELA_LLM_PROVIDER",
            "display": "plain",
            "required_for_providers": [],
            "pattern": r"^(mock|volcengine|openai_compat)$",
            "hint": "须为 mock | volcengine | openai_compat 之一",
        },
        {
            "name": "VELA_ARK_BASE_URL",
            "display": "plain",
            "required_for_providers": ["volcengine"],
            "pattern": r".*/api/v3$",
            "hint": (
                "正确形式为 https://ark.cn-beijing.volces.com/api/v3；"
                "/api/plan/v3 是常见笔误"
            ),
        },
        {
            "name": "VELA_ARK_API_KEY",
            "display": "masked",
            "required_for_providers": ["volcengine"],
            "pattern": "",
            "hint": "请到火山方舟控制台 API Key 页创建并填入 VELA_ARK_API_KEY",
        },
        {
            "name": "VELA_ARK_MODEL",
            "display": "plain",
            "required_for_providers": ["volcengine"],
            "pattern": r"^(ep-[A-Za-z0-9]+|[A-Za-z0-9._/-]+)$",
            "hint": "请填推理接入点 ID（ep-xxxxxxxx）或模型名",
        },
    ],
}


def _by_name(results: list[dict], name: str) -> dict:
    matched = [r for r in results if r["name"] == name]
    assert matched, f"missing check for {name}: {results}"
    return matched[0]


def test_base_url_plan_v3_is_rejected():
    rs = EnvChecker(cfg=_CFG).run(
        "volcengine",
        {"VELA_ARK_BASE_URL": "https://ark.cn-beijing.volces.com/api/plan/v3"},
    )
    item = _by_name(rs, "VELA_ARK_BASE_URL")
    assert item["ok"] is False
    assert "/api/v3" in item["detail"]


def test_base_url_api_v3_is_ok():
    rs = EnvChecker(cfg=_CFG).run(
        "volcengine",
        {
            "VELA_ARK_BASE_URL": "https://ark.cn-beijing.volces.com/api/v3",
            "VELA_ARK_API_KEY": "DUMMY-KEY-0123456789ABCD",
            "VELA_ARK_MODEL": "ep-DUMMY0001",
            "VELA_LLM_PROVIDER": "volcengine",
        },
    )
    assert _by_name(rs, "VELA_ARK_BASE_URL")["ok"] is True


def test_inline_comment_residue_fails():
    rs = EnvChecker(cfg=_CFG).run(
        "mock",
        {"VELA_LLM_PROVIDER": "mock   # 注释"},
    )
    item = _by_name(rs, "VELA_LLM_PROVIDER")
    assert item["ok"] is False
    assert "注释" in item["detail"]


def test_masked_display_hides_secret():
    secret = "DUMMY-KEY-0123456789ABCD"
    rs = EnvChecker(cfg=_CFG).run(
        "volcengine",
        {
            "VELA_ARK_API_KEY": secret,
            "VELA_ARK_BASE_URL": "https://ark.cn-beijing.volces.com/api/v3",
            "VELA_ARK_MODEL": "ep-DUMMY0001",
        },
    )
    detail = _by_name(rs, "VELA_ARK_API_KEY")["detail"]
    assert secret not in detail
    assert "DUMM****ABCD" in detail


def test_mock_skips_volcengine_required():
    rs = EnvChecker(cfg=_CFG).run("mock", {"VELA_LLM_PROVIDER": "mock"})
    assert _by_name(rs, "VELA_ARK_API_KEY")["ok"] is True
    assert _by_name(rs, "VELA_ARK_BASE_URL")["ok"] is True


def test_volcengine_missing_api_key_fails():
    rs = EnvChecker(cfg=_CFG).run(
        "volcengine",
        {"VELA_ARK_BASE_URL": "https://ark.cn-beijing.volces.com/api/v3"},
    )
    item = _by_name(rs, "VELA_ARK_API_KEY")
    assert item["ok"] is False
    assert "方舟" in item["detail"] or "API Key" in item["detail"]


def test_all_compliant_all_ok():
    rs = EnvChecker(cfg=_CFG).run(
        "volcengine",
        {
            "VELA_LLM_PROVIDER": "volcengine",
            "VELA_ARK_BASE_URL": "https://ark.cn-beijing.volces.com/api/v3",
            "VELA_ARK_API_KEY": "DUMMY-KEY-0123456789ABCD",
            "VELA_ARK_MODEL": "ep-DUMMY0001",
        },
    )
    assert all(r["ok"] for r in rs)


def test_result_contract_keys():
    rs = EnvChecker(cfg=_CFG).run("mock", {})
    assert rs
    for item in rs:
        assert set(item) == {"name", "ok", "detail", "kind"}
        assert item["kind"] == "local"


def test_cfg_and_environ_injection_isolated():
    """单测不依赖真实 config/ 与真实 os.environ。"""
    checker = EnvChecker(cfg=_CFG)
    rs = checker.run("mock", environ={})
    names = {r["name"] for r in rs}
    assert names == {
        "VELA_LLM_PROVIDER",
        "VELA_ARK_BASE_URL",
        "VELA_ARK_API_KEY",
        "VELA_ARK_MODEL",
    }
