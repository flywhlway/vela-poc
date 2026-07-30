"""LLMGateway：统一出口 + 逻辑模型映射 + 脱敏 + 计量 + 审计 + 降级链。"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from vela.config import load_yaml
from vela.gateway.audit import Auditor
from vela.gateway.budget import BudgetExceeded, TokenLedger
from vela.gateway.redact import Redactor
from vela.util.textutil import estimate_tokens


class LLMError(RuntimeError):
    pass


@dataclass
class LLMRequest:
    logical_model: str
    system: str = ""
    user: str = ""
    messages: list[dict] | None = None
    json_mode: bool | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    meta: dict = field(default_factory=dict)

    def as_messages(self) -> list[dict]:
        if self.messages:
            return list(self.messages)
        msgs = []
        if self.system:
            msgs.append({"role": "system", "content": self.system})
        msgs.append({"role": "user", "content": self.user})
        return msgs

    def flat_text(self) -> str:
        return "\n".join(m.get("content", "") for m in self.as_messages())


@dataclass
class LLMResponse:
    text: str
    logical_model: str
    physical_model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    finish_reason: str = "stop"
    fallback_from: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class Provider:
    """供应商适配器接口。新增供应商只需实现 complete()。"""
    name = "base"

    def models_for(self, logical_model: str) -> list[str]:
        raise NotImplementedError

    def complete(self, req: LLMRequest, physical_model: str, params: dict) -> LLMResponse:
        raise NotImplementedError


class LLMGateway:
    def __init__(self, provider: Provider, cfg: dict | None = None,
                 ledger: TokenLedger | None = None, audit_path: str | Path | None = None,
                 session_id: str = "-"):
        self.cfg = cfg if cfg is not None else load_yaml("llm.yaml")
        self.provider = provider
        self.ledger = ledger or TokenLedger()
        self.redactor = Redactor(self.cfg.get("redaction"))
        self.auditor = Auditor(audit_path, self.cfg.get("audit"))
        self.session_id = session_id
        self.logical = self.cfg.get("logical_models", {})
        self.history: list[dict] = []

    # ------------------------------------------------------------------ #
    def chat(self, req: LLMRequest) -> LLMResponse:
        params = dict(self.logical.get(req.logical_model, {}))
        if req.temperature is not None:
            params["temperature"] = req.temperature
        if req.max_tokens is not None:
            params["max_tokens"] = req.max_tokens
        if req.json_mode is not None:
            params["json_mode"] = req.json_mode

        # 1) 出站脱敏（在计量与发送之前）
        red_hits: dict[str, int] = {}
        msgs = []
        for m in req.as_messages():
            r = self.redactor.redact(m.get("content", ""))
            for k, v in r.hits.items():
                red_hits[k] = red_hits.get(k, 0) + v
            msgs.append({**m, "content": r.text})
        safe = LLMRequest(logical_model=req.logical_model, messages=msgs,
                          json_mode=params.get("json_mode"),
                          temperature=params.get("temperature"),
                          max_tokens=params.get("max_tokens"), meta=req.meta)

        # 2) 预算预检（估算 prompt + 预留 completion）
        planned = estimate_tokens(safe.flat_text()) + int(params.get("max_tokens", 1024))
        self.ledger.precheck(planned)

        # 3) 降级链
        chain = self.provider.models_for(req.logical_model)
        if not chain:
            raise LLMError(f"provider={self.provider.name} 未配置任何可用物理模型："
                           f"请设置对应环境变量（见 .env.example）")
        last_err: Exception | None = None
        for idx, phys in enumerate(chain):
            t0 = time.time()
            try:
                resp = self.provider.complete(safe, phys, params)
            except Exception as e:                             # 降级到下一个接入点
                last_err = e
                self.auditor.record(session_id=self.session_id, round_no=self.ledger.round_no,
                                    logical_model=req.logical_model, physical_model=phys,
                                    provider=self.provider.name, prompt=safe.flat_text(),
                                    completion="", prompt_tokens=0, completion_tokens=0,
                                    latency_ms=(time.time() - t0) * 1000,
                                    redaction_hits=red_hits, ok=False, error=f"{type(e).__name__}: {e}")
                continue
            resp.fallback_from = chain[0] if idx > 0 else None
            resp.logical_model = req.logical_model
            if not resp.prompt_tokens:
                resp.prompt_tokens = estimate_tokens(safe.flat_text())
            if not resp.completion_tokens:
                resp.completion_tokens = estimate_tokens(resp.text)
            self.ledger.charge(req.logical_model, resp.prompt_tokens, resp.completion_tokens)
            rec = self.auditor.record(
                session_id=self.session_id, round_no=self.ledger.round_no,
                logical_model=req.logical_model, physical_model=phys,
                provider=self.provider.name, prompt=safe.flat_text(), completion=resp.text,
                prompt_tokens=resp.prompt_tokens, completion_tokens=resp.completion_tokens,
                latency_ms=resp.latency_ms, redaction_hits=red_hits, ok=True,
                fallback_from=resp.fallback_from)
            self.history.append(rec)
            return resp
        raise LLMError(f"全部 {len(chain)} 个接入点均失败，最后错误：{last_err}")

    def stats(self) -> dict:
        return {"provider": self.provider.name, "session_id": self.session_id,
                **self.ledger.snapshot()}


def build_gateway(provider_name: str | None = None, *, session_id: str = "-",
                  audit_path: str | Path | None = None,
                  ledger: TokenLedger | None = None, cfg: dict | None = None) -> LLMGateway:
    """按配置/环境变量构造网关。生产切换只改 VELA_LLM_PROVIDER。"""
    cfg = cfg if cfg is not None else load_yaml("llm.yaml")
    name = provider_name or os.environ.get("VELA_LLM_PROVIDER") or cfg.get("active", "mock")
    pcfg = (cfg.get("providers") or {}).get(name)
    if pcfg is None:
        raise LLMError(f"未知 provider: {name}，可选: {sorted((cfg.get('providers') or {}))}")
    kind = pcfg.get("kind", "mock")
    if kind == "mock":
        from vela.gateway.mock import MockProvider
        provider: Provider = MockProvider(pcfg, name=name)
    elif kind == "openai_compatible":
        from vela.gateway.openai_compat import OpenAICompatProvider
        provider = OpenAICompatProvider(pcfg, name=name)
    else:
        raise LLMError(f"不支持的 provider kind: {kind}")
    return LLMGateway(provider, cfg=cfg, ledger=ledger, audit_path=audit_path,
                      session_id=session_id)
