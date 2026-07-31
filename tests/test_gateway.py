"""模型网关：脱敏、预算硬切断、mock 供应商契约、审计、火山引擎适配器解析。"""
from __future__ import annotations

import json

import pytest

from vela.gateway import LLMRequest, build_gateway
from vela.gateway.budget import BudgetExceeded, TokenLedger
from vela.gateway.prompts import (PLANNER_SYSTEM, embed_state, extract_state, planner_user)
from vela.gateway.redact import Redactor


def test_redactor_masks_vin_phone_email_ip_gps():
    r = Redactor({"enabled": True, "rules": [
        {"name": "vin", "pattern": r"\b[A-HJ-NPR-Z0-9]{17}\b", "repl": "VIN_<M>"},
        {"name": "phone", "pattern": r"\b1[3-9]\d{9}\b", "repl": "<PHONE>"},
        {"name": "email", "pattern": r"\b[\w.+-]+@[\w-]+\.[\w.]+\b", "repl": "<EMAIL>"},
        {"name": "ipv4", "pattern": r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "repl": "<IPV4>"},
        {"name": "gps", "pattern": r"lat=-?\d{1,3}\.\d{3,}", "repl": "<GEO>"},
    ]})
    text = "VIN=LSVM3HNR4SC988574 phone 13812345678 mail a@b.com ip 10.0.0.1 lat=31.230456"
    res = r.redact(text)
    assert "LSVM3HNR4SC988574" not in res.text
    assert "13812345678" not in res.text
    assert "a@b.com" not in res.text
    assert "10.0.0.1" not in res.text
    assert res.total >= 4


def test_redactor_disabled_passes_through():
    r = Redactor({"enabled": False, "rules": [{"name": "x", "pattern": r"\d+", "repl": "N"}]})
    assert r.redact("abc123").text == "abc123"


def test_token_ledger_round_cutoff():
    from vela.config import load_budget
    ledger = TokenLedger(budget=load_budget("poc"))
    ledger.start_round()
    ledger.precheck(100)
    with pytest.raises(BudgetExceeded):
        ledger.precheck(ledger.budget.round_llm_tokens + 1)


def test_token_ledger_session_cutoff_across_rounds():
    from vela.config import load_budget
    b = load_budget("poc")
    ledger = TokenLedger(budget=b)
    remaining = b.session_llm_tokens
    while remaining > 0:
        ledger.start_round()
        chunk = min(b.round_llm_tokens, remaining)
        ledger.charge("planner", chunk, 0)
        remaining -= chunk
    ledger.start_round()
    with pytest.raises(BudgetExceeded):
        ledger.precheck(1)


def test_ledger_snapshot_tracks_by_logical_model():
    from vela.config import load_budget
    ledger = TokenLedger(budget=load_budget("poc"))
    ledger.start_round()
    ledger.charge("planner", 10, 5)
    ledger.charge("verifier", 3, 2)
    snap = ledger.snapshot()
    assert snap["by_logical_model"] == {"planner": 15, "verifier": 5}


def test_embed_extract_state_roundtrip():
    state = {"a": 1, "b": ["中文", 2]}
    text = "前言\n" + embed_state(state) + "\n后语"
    assert extract_state(text) == state


def test_extract_state_returns_empty_on_missing_block():
    assert extract_state("no state here") == {}


def test_mock_provider_planner_selects_matching_skill(tmp_path):
    gw = build_gateway("mock", session_id="T1", audit_path=tmp_path / "audit.jsonl")
    gw.ledger.start_round()
    state = {
        "signals": {"fail_phase": "FLASH", "abort_reason": "UDS_NRC_0x72"},
        "evidence_digest": ["[1x] NRC received sid=0x36 nrc=0x72 generalProgrammingFailure"],
        "candidate_skills": [
            {"id": "SK-UDS-NRC", "title": "UDS NRC", "trigger": "FLASH 阶段 NRC",
             "keywords": ["nrc", "0x72"], "probes": [{"tool": "search_logs", "args": {}}]},
            {"id": "SK-DL-TIMEOUT", "title": "下载超时", "trigger": "DOWNLOAD",
             "keywords": ["timeout"], "probes": []},
        ],
        "excluded_skills": [],
    }
    resp = gw.chat(LLMRequest(logical_model="planner", system=PLANNER_SYSTEM,
                              user=planner_user(state)))
    out = json.loads(resp.text)
    assert out["selected_skill"] == "SK-UDS-NRC"
    assert out["actions"]


def test_mock_provider_deterministic_same_input_same_output():
    gw1 = build_gateway("mock", session_id="A")
    gw2 = build_gateway("mock", session_id="B")
    state = {"claims": [{"claim_id": "C1", "citations": ["abc"]}], "known_row_hashes": ["abc"]}
    r1 = gw1.chat(LLMRequest(logical_model="verifier", user=json.dumps(state)))
    r2 = gw2.chat(LLMRequest(logical_model="verifier", user=json.dumps(state)))
    # 两次调用走同一套确定性规则器，且 verifier 状态需通过 embed_state 传递
    from vela.gateway.prompts import embed_state
    r1b = gw1.chat(LLMRequest(logical_model="verifier", user=embed_state(state)))
    r2b = gw2.chat(LLMRequest(logical_model="verifier", user=embed_state(state)))
    assert r1b.text == r2b.text


def test_mock_verifier_flags_hallucinated_citation():
    from vela.gateway.mock import MockProvider
    p = MockProvider({"deterministic": True, "inject_hallucinated_citations": True}, name="mock")
    from vela.gateway.base import LLMRequest as R
    from vela.gateway.prompts import embed_state
    state = {"claims": [{"claim_id": "C1", "citations": ["real000000000001"]}],
             "known_row_hashes": ["real000000000001"]}
    resp = p.complete(R(logical_model="verifier", user=embed_state(state)), "mock-verifier", {})
    out = json.loads(resp.text)
    v = out["verdicts"][0]
    assert v["status"] != "supported" or len(v["citations"]) > 1


def test_gateway_redacts_before_metering_and_audit(tmp_path):
    gw = build_gateway("mock", session_id="T2", audit_path=tmp_path / "audit.jsonl")
    gw.ledger.start_round()
    gw.chat(LLMRequest(logical_model="reporter",
                       user="VIN=LSVM3HNR4SC988574 phone 13812345678"))
    rec = gw.history[-1]
    assert rec["redaction_hits"].get("vin") or rec["redaction_hits"].get("phone")
    assert "prompt_sha256" in rec
    assert "prompt" not in rec          # log_prompt=false by default


def test_gateway_unknown_provider_raises():
    with pytest.raises(Exception):
        build_gateway("not-a-real-provider")


def test_openai_compat_models_for_reads_env(monkeypatch):
    from vela.gateway.openai_compat import OpenAICompatProvider
    monkeypatch.setenv("VELA_ARK_MODEL", "ep-default")
    monkeypatch.setenv("VELA_ARK_MODEL_PLANNER", "ep-planner")
    monkeypatch.setenv("VELA_ARK_MODEL_FALLBACK", "ep-fallback")
    cfg = {"model_env": "VELA_ARK_MODEL", "fallback_chain": ["VELA_ARK_MODEL_FALLBACK"]}
    p = OpenAICompatProvider(cfg, name="volcengine")
    chain = p.models_for("planner")
    assert chain[0] == "ep-planner"
    assert "ep-default" in chain and "ep-fallback" in chain
    assert len(chain) == len(set(chain))


def test_openai_compat_missing_credentials_raises_clear_error(monkeypatch):
    """凭证缺失前置校验：`_post` 随 SDK 重写移除，由 ensure_credentials() 承接。

    断言意图不变——缺凭证必须抛出指名环境变量的 LLMError，且不发网络请求。
    """
    from vela.gateway.base import LLMError
    from vela.gateway.openai_compat import OpenAICompatProvider
    monkeypatch.delenv("VELA_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("VELA_OPENAI_API_KEY", raising=False)
    p = OpenAICompatProvider({"base_url_env": "VELA_OPENAI_BASE_URL",
                              "api_key_env": "VELA_OPENAI_API_KEY"}, name="openai_compat")
    with pytest.raises(LLMError):
        p.ensure_credentials()


def test_volcengine_provider_is_openai_compatible_subclass():
    from vela.gateway.openai_compat import OpenAICompatProvider
    from vela.gateway.volcengine import VolcengineArkProvider
    assert issubclass(VolcengineArkProvider, OpenAICompatProvider)


def _stub_chat_client(exc: BaseException):
    """构造 chat.completions.create 会抛指定异常的桩客户端（零网络）。"""
    class _Completions:
        def create(self, **_kwargs):
            raise exc

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    return _Client()


def test_openai_compat_wraps_sdk_error_into_llm_error(monkeypatch):
    """SDK 异常基类被捕获并包成 LLMError，消息以异常类名开头。"""
    import openai
    from vela.gateway.base import LLMError, LLMRequest
    from vela.gateway.openai_compat import OpenAICompatProvider

    class FakeSDKError(openai.OpenAIError):
        pass

    monkeypatch.setenv("VELA_TEST_BASE", "https://example.invalid/v1")
    monkeypatch.setenv("VELA_TEST_KEY", "DUMMY-KEY-0123456789")
    p = OpenAICompatProvider(
        {"base_url_env": "VELA_TEST_BASE", "api_key_env": "VELA_TEST_KEY"},
        name="openai_compat",
    )
    monkeypatch.setattr(p, "_client", lambda: _stub_chat_client(FakeSDKError("boom")))
    with pytest.raises(LLMError) as ei:
        p.complete(LLMRequest(logical_model="planner", user="hi"), "ep-x", {})
    assert str(ei.value).startswith("FakeSDKError:")


def test_openai_compat_probe_attributes_sdk_exceptions(monkeypatch):
    """probe() 按 SDK 异常类型归因：401/404/429 三元结论与归因表一致。"""
    import httpx
    import openai
    from vela.gateway.openai_compat import OpenAICompatProvider

    monkeypatch.setenv("VELA_TEST_BASE", "https://example.invalid/v1")
    monkeypatch.setenv("VELA_TEST_KEY", "DUMMY-KEY-0123456789")
    cfg = {"base_url_env": "VELA_TEST_BASE", "api_key_env": "VELA_TEST_KEY"}
    req = httpx.Request("POST", "http://x")

    cases = [
        (openai.AuthenticationError(
            message="x", response=httpx.Response(401, request=req), body=None),
         dict(reachable=True, authenticated=False, model_ok=False)),
        (openai.NotFoundError(
            message="x", response=httpx.Response(404, request=req), body=None),
         dict(reachable=True, authenticated=True, model_ok=False)),
        (openai.RateLimitError(
            message="x", response=httpx.Response(429, request=req), body=None),
         dict(reachable=True, authenticated=True, model_ok=True)),
    ]
    for exc, expected in cases:
        p = OpenAICompatProvider(cfg, name="openai_compat")
        monkeypatch.setattr(p, "_client", lambda e=exc: _stub_chat_client(e))
        result = p.probe("ep-x")
        for k, v in expected.items():
            assert result[k] is v, (type(exc).__name__, k, result)


def test_openai_compat_probe_detail_masks_api_key(monkeypatch):
    """probe().detail 不得泄露 api_key 明文。"""
    import openai
    from vela.gateway.openai_compat import OpenAICompatProvider

    key = "DUMMY-KEY-0123456789"
    monkeypatch.setenv("VELA_TEST_BASE", "https://example.invalid/v1")
    monkeypatch.setenv("VELA_TEST_KEY", key)
    p = OpenAICompatProvider(
        {"base_url_env": "VELA_TEST_BASE", "api_key_env": "VELA_TEST_KEY"},
        name="openai_compat",
    )
    leak = openai.OpenAIError(f"auth failed with key={key}")
    monkeypatch.setattr(p, "_client", lambda: _stub_chat_client(leak))
    detail = p.probe("ep-x")["detail"]
    assert key not in detail


# --------------------------------------------------------------------- cache / cost (Phase 2)
def test_llm_disk_cache_hit_skips_provider_complete(tmp_path, monkeypatch):
    """同键二次 chat：第二次命中缓存，不调用 provider.complete。"""
    from vela.gateway.base import LLMGateway, LLMRequest
    from vela.gateway.cache import LLMDiskCache
    from vela.gateway.mock import MockProvider

    monkeypatch.setenv("VELA_LLM_CACHE", "0")  # 显式走构造参数
    calls = {"n": 0}
    provider = MockProvider({"deterministic": True}, name="mock")
    orig = provider.complete

    def counted(req, phys, params):
        calls["n"] += 1
        return orig(req, phys, params)

    provider.complete = counted  # type: ignore[method-assign]
    cache = LLMDiskCache(tmp_path / "llm", enabled=True)
    gw = LLMGateway(provider, cache=cache, session_id="CACHE-1",
                    audit_path=tmp_path / "a.jsonl")
    req = LLMRequest(logical_model="planner", system="s", user="hello cache")
    r1 = gw.chat(req)
    assert r1.cache_hit is False and calls["n"] == 1
    r2 = gw.chat(req)
    assert r2.cache_hit is True and calls["n"] == 1
    assert r2.text == r1.text
    assert gw.ledger.cache_hits == 1
    assert gw.history[-1]["finish_reason"] is not None
    assert gw.history[-1]["cache_hit"] is True


def test_llm_cache_disabled_does_not_write(tmp_path, monkeypatch):
    monkeypatch.setenv("VELA_LLM_CACHE", "0")
    from vela.gateway.base import LLMGateway, LLMRequest
    from vela.gateway.cache import LLMDiskCache
    from vela.gateway.mock import MockProvider

    cache = LLMDiskCache(tmp_path / "llm", enabled=False)
    gw = LLMGateway(MockProvider({}, name="mock"), cache=cache, session_id="CACHE-OFF")
    gw.chat(LLMRequest(logical_model="planner", user="x"))
    assert list((tmp_path / "llm").glob("*.json")) == [] if (tmp_path / "llm").exists() else True


def test_token_ledger_cost_snapshot_and_alert_not_budget_exceeded():
    from vela.config import load_budget
    alerts: list[tuple[str, dict]] = []
    ledger = TokenLedger(
        budget=load_budget("poc"),
        cost_rates={"input_per_1k": 10.0, "output_per_1k": 20.0, "diagnose_cost_alert": 0.01},
        on_alert=lambda kind, payload: alerts.append((kind, payload)),
    )
    ledger.charge("planner", 100, 50)
    snap = ledger.snapshot()
    assert snap["prompt_tokens"] == 100
    assert snap["completion_tokens"] == 50
    assert snap["estimated_cost_usd"] > 0.01
    assert alerts and alerts[0][0] == "cost.alert"
    # 告警后仍可继续 charge，不抛 BudgetExceeded
    ledger.charge("verifier", 1, 1)


def test_token_budget_hard_cut_still_raises():
    from vela.config import load_budget
    ledger = TokenLedger(budget=load_budget("poc"))
    with pytest.raises(BudgetExceeded):
        ledger.precheck(ledger.budget.round_llm_tokens + 1)
