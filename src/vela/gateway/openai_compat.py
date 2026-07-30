"""基于 openai 官方 SDK 实现的 OpenAI 兼容供应商适配器。

覆盖：火山引擎方舟(Ark) / vLLM / One-API / 自建网关 / OpenAI 本体。
差异点全部由 config/llm.yaml 的 provider 段描述，代码不含任何厂商硬编码。
"""
from __future__ import annotations

import os
import time

import openai
from openai import OpenAI

from vela.gateway.base import LLMError, LLMRequest, LLMResponse, Provider


class OpenAICompatProvider(Provider):
    def __init__(self, cfg: dict, name: str = "openai_compat"):
        self.name = name
        self.cfg = cfg or {}
        self.base_url = (os.environ.get(self.cfg.get("base_url_env", ""), "")
                         or self.cfg.get("base_url_default", "")).rstrip("/")
        self.api_key = os.environ.get(self.cfg.get("api_key_env", ""), "")
        self.timeout_s = float(self.cfg.get("timeout_s", 120))
        self.max_retries = int(self.cfg.get("max_retries", 2))
        self._sdk: OpenAI | None = None

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

    def ensure_credentials(self) -> None:
        """本地凭证前置校验：缺 base_url / api_key 时抛指名环境变量的 LLMError。

        公开方法供 doctor（Plan 06）与测试承接原 `_post` 的断言意图；不发网络请求。
        """
        if not self.base_url:
            raise LLMError(f"provider={self.name} 未配置 base_url"
                           f"（环境变量 {self.cfg.get('base_url_env')}）")
        if not self.api_key:
            raise LLMError(f"provider={self.name} 未配置 API Key"
                           f"（环境变量 {self.cfg.get('api_key_env')}）")

    def _client(self) -> OpenAI:
        """惰性构造并复用 OpenAI 客户端。

        本项目单线程单进程同步模型，复用同一客户端以共享连接池；
        构造期不发起网络请求，不违反导入静默纪律。
        """
        self.ensure_credentials()
        if self._sdk is None:
            self._sdk = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout_s,
                max_retries=self.max_retries,
            )
        return self._sdk

    def _scrub(self, text: str) -> str:
        """掩码异常消息中可能回显的 API key。"""
        if self.api_key and self.api_key in text:
            return text.replace(self.api_key, "***")
        return text

    def complete(self, req: LLMRequest, physical_model: str, params: dict) -> LLMResponse:
        kwargs: dict = {
            "model": physical_model,
            "messages": req.as_messages(),
            "temperature": float(params.get("temperature", 0.2)),
            "max_tokens": int(params.get("max_tokens", 1024)),
        }
        if params.get("json_mode"):
            kwargs["response_format"] = {"type": "json_object"}
        t0 = time.time()
        try:
            resp = self._client().chat.completions.create(**kwargs)
        except openai.OpenAIError as e:
            # 不区分「不可重试」异常： (a) gateway/base.py 只读不改，中断语义只能改在那里；
            # (b) 既有测试依赖「任何异常都 fallback」；(c) 降级链可能跨供应商环境变量，
            # 鉴权失败换下一个接入点在本项目配置形态下仍有意义。
            raise LLMError(f"{type(e).__name__}: {self._scrub(str(e))}") from e
        choices = resp.choices or []
        if not choices:
            raise LLMError(f"响应缺少 choices：{self._scrub(str(resp))[:300]}")
        usage = resp.usage
        return LLMResponse(
            text=(choices[0].message.content or ""),
            logical_model=req.logical_model, physical_model=physical_model, provider=self.name,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            latency_ms=(time.time() - t0) * 1000,
            finish_reason=choices[0].finish_reason or "stop",
            raw={"id": resp.id, "model": resp.model})

    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        env = self.cfg.get("embed_model_env", "")
        m = model or (os.environ.get(env) if env else None)
        if not m:
            raise LLMError(f"未配置向量模型（环境变量 {env}）")
        try:
            data = self._client().embeddings.create(model=m, input=texts)
        except openai.OpenAIError as e:
            raise LLMError(f"{type(e).__name__}: {self._scrub(str(e))}") from e
        return [d.embedding for d in sorted(data.data, key=lambda x: x.index)]

    def probe(self, physical_model: str) -> dict:
        """最小 chat 探测：按 SDK 异常类型归因端点可达 / 鉴权有效 / 模型可用。

        不属于 Provider 抽象契约；doctor（Plan 06）用 hasattr(provider, "probe") 判定。

        安全约束：本方法不经 LLMGateway.chat()，因此不经 gateway/redact.py 脱敏。
        可接受的前提是 prompt 为硬编码常量 ping，不含用户数据、日志或证据文本。
        任何后续改动都不得把可变内容传进 probe 的 messages。
        """
        try:
            self.ensure_credentials()
        except LLMError as e:
            return {
                "reachable": False,
                "authenticated": False,
                "model_ok": False,
                "error_kind": "MissingCredentials",
                "detail": str(e),
            }

        try:
            # 禁令：messages 内容必须保持硬编码常量，禁止参数化或拼接外部文本。
            self._client().chat.completions.create(
                model=physical_model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                temperature=0,
            )
            return {
                "reachable": True,
                "authenticated": True,
                "model_ok": True,
                "error_kind": "",
                "detail": "",
            }
        except openai.APITimeoutError as e:
            return self._probe_result(False, False, False, e, "端点超时")
        except openai.APIConnectionError as e:
            return self._probe_result(False, False, False, e, "端点不可达")
        except openai.AuthenticationError as e:
            return self._probe_result(True, False, False, e, "鉴权失败")
        except openai.PermissionDeniedError as e:
            return self._probe_result(True, False, False, e, "鉴权失败")
        except openai.NotFoundError as e:
            return self._probe_result(True, True, False, e, "模型不可用")
        except openai.BadRequestError as e:
            # BadRequestError：方舟对无效接入点 ID 常返 400 而非 404
            return self._probe_result(True, True, False, e, "模型不可用")
        except openai.RateLimitError as e:
            # 限流意味着端点可达、鉴权通过、模型存在，只是配额受限
            return self._probe_result(
                True, True, True, e, "限流，未能完成最小调用")
        except openai.InternalServerError as e:
            return self._probe_result(True, True, False, e, "服务端错误")
        except openai.OpenAIError as e:
            return self._probe_result(True, False, False, e, "未分类 SDK 错误")

    def _probe_result(
        self,
        reachable: bool,
        authenticated: bool,
        model_ok: bool,
        exc: BaseException,
        summary: str,
    ) -> dict:
        raw = self._scrub(str(exc))[:300]
        return {
            "reachable": reachable,
            "authenticated": authenticated,
            "model_ok": model_ok,
            "error_kind": type(exc).__name__,
            "detail": f"{summary}：{raw}" if raw else summary,
        }
