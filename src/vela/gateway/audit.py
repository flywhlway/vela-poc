"""模型调用审计：全量落 JSONL，默认只落 prompt 哈希不落明文。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from vela.config import load_yaml
from vela.util.jsonl import append_jsonl
from vela.util.timeutil import iso

UTC = timezone.utc


class Auditor:
    def __init__(self, path: str | Path | None = None, cfg: dict | None = None):
        cfg = cfg if cfg is not None else load_yaml("llm.yaml").get("audit", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.log_prompt = bool(cfg.get("log_prompt", False))
        self.log_prompt_hash = bool(cfg.get("log_prompt_hash", True))
        self.path = Path(path) if path else None

    def record(self, *, session_id: str, round_no: int, logical_model: str,
               physical_model: str, provider: str, prompt: str, completion: str,
               prompt_tokens: int, completion_tokens: int, latency_ms: float,
               redaction_hits: dict, ok: bool, error: str | None = None,
               fallback_from: str | None = None,
               finish_reason: str | None = None,
               cache_hit: bool = False) -> dict:
        rec = {
            "ts_utc": iso(datetime.now(UTC)),
            "session_id": session_id, "round_no": round_no,
            "logical_model": logical_model, "physical_model": physical_model,
            "provider": provider, "ok": ok, "error": error,
            "fallback_from": fallback_from,
            "prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens,
            "latency_ms": round(latency_ms, 2),
            "redaction_hits": redaction_hits,
            "completion_chars": len(completion or ""),
            "finish_reason": finish_reason,
            "cache_hit": bool(cache_hit),
        }
        if self.log_prompt_hash:
            rec["prompt_sha256"] = hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()
        if self.log_prompt:
            rec["prompt"] = prompt
            rec["completion"] = completion
        if self.enabled and self.path:
            append_jsonl(self.path, rec)
        return rec
