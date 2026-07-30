"""OpenAI 兼容供应商适配器（stdlib urllib 实现，零第三方依赖）。

覆盖：火山引擎方舟(Ark) / vLLM / One-API / 自建网关 / OpenAI 本体。
差异点全部由 config/llm.yaml 的 provider 段描述，代码不含任何厂商硬编码。
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from vela.gateway.base import LLMError, LLMRequest, LLMResponse, Provider


class OpenAICompatProvider(Provider):
    def __init__(self, cfg: dict, name: str = "openai_compat"):
        self.name = name
        self.cfg = cfg or {}
        self.base_url = (os.environ.get(self.cfg.get("base_url_env", ""), "")
                         or self.cfg.get("base_url_default", "")).rstrip("/")
        self.api_key = os.environ.get(self.cfg.get("api_key_env", ""), "")
        self.chat_path = self.cfg.get("chat_path", "/chat/completions")
        self.embed_path = self.cfg.get("embed_path", "/embeddings")
        self.timeout_s = float(self.cfg.get("timeout_s", 120))
        self.max_retries = int(self.cfg.get("max_retries", 2))
        self.backoff = float(self.cfg.get("retry_backoff_s", 1.5))

    # ------------------------------------------------------------------ #
    def models_for(self, logical_model: str) -> list[str]:
        """物理模型解析顺序：逻辑模型专属环境变量 → 通用 model_env → 降级链。

        火山引擎方舟填的是"推理接入点 ID"（ep-xxxxxxxx），也可直接填模型名。
        例：VELA_ARK_MODEL_PLANNER=ep-2024xxxx-planner
            VELA_ARK_MODEL=ep-2024xxxx-default
        """
        out: list[str] = []
        base_env = self.cfg.get("model_env", "")
        if base_env:
            v = os.environ.get(f"{base_env}_{logical_model.upper()}")
            if v:
                out.append(v)
            v = os.environ.get(base_env)
            if v:
                out.append(v)
        d = self.cfg.get("model_default") or ""
        if d:
            out.append(d)
        for env in self.cfg.get("fallback_chain", []) or []:
            v = os.environ.get(env)
            if v:
                out.append(v)
        seen, uniq = set(), []
        for m in out:
            if m not in seen:
                seen.add(m)
                uniq.append(m)
        return uniq

    def _post(self, path: str, payload: dict) -> dict:
        if not self.base_url:
            raise LLMError(f"provider={self.name} 未配置 base_url"
                           f"（环境变量 {self.cfg.get('base_url_env')}）")
        if not self.api_key:
            raise LLMError(f"provider={self.name} 未配置 API Key"
                           f"（环境变量 {self.cfg.get('api_key_env')}）")
        url = self.base_url + path
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(url, data=data, method="POST", headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
                "User-Agent": "vela-poc/1.0",
            })
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "replace")[:500]
                last = LLMError(f"HTTP {e.code}: {body}")
                if e.code in (400, 401, 403, 404):      # 不可重试
                    raise last
            except Exception as e:                       # 网络类错误可重试
                last = e
            if attempt < self.max_retries:
                time.sleep(self.backoff * (attempt + 1))
        raise LLMError(f"调用 {url} 失败：{last}")

    def complete(self, req: LLMRequest, physical_model: str, params: dict) -> LLMResponse:
        payload = {
            "model": physical_model,
            "messages": req.as_messages(),
            "temperature": float(params.get("temperature", 0.2)),
            "max_tokens": int(params.get("max_tokens", 1024)),
            "stream": False,
        }
        if params.get("json_mode"):
            payload["response_format"] = {"type": "json_object"}
        t0 = time.time()
        data = self._post(self.chat_path, payload)
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"响应缺少 choices：{str(data)[:300]}")
        msg = choices[0].get("message") or {}
        usage = data.get("usage") or {}
        return LLMResponse(
            text=msg.get("content") or "",
            logical_model=req.logical_model, physical_model=physical_model, provider=self.name,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            latency_ms=(time.time() - t0) * 1000,
            finish_reason=choices[0].get("finish_reason", "stop"),
            raw={"id": data.get("id"), "model": data.get("model")})

    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        env = self.cfg.get("embed_model_env", "")
        m = model or (os.environ.get(env) if env else None)
        if not m:
            raise LLMError(f"未配置向量模型（环境变量 {env}）")
        data = self._post(self.embed_path, {"model": m, "input": texts})
        return [d["embedding"] for d in sorted(data.get("data", []),
                                               key=lambda x: x.get("index", 0))]
