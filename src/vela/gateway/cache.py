"""LLM 响应磁盘缓存（METR-06）：键 = (provider, physical_model, prompt_sha256, params)。

仅缓存脱敏后流量；损坏 JSON 视为未命中。默认关闭（确定性 / 测试友好）。
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from vela.util.jsonl import canonical_json


def default_cache_root() -> Path:
    override = os.environ.get("VELA_LLM_CACHE_DIR", "").strip()
    if override:
        return Path(override).resolve()
    # 项目根：src/vela/gateway/cache.py → parents[3]
    root = Path(__file__).resolve().parents[3]
    return root / ".cache" / "vela" / "llm"


def cache_enabled_from_env(*, default: bool = False) -> bool:
    """VELA_LLM_CACHE=0/false 关闭；=1/true 开启；未设则用 default（默认 False）。"""
    v = os.environ.get("VELA_LLM_CACHE", "").strip().lower()
    if v in ("0", "false", "off", "no"):
        return False
    if v in ("1", "true", "on", "yes"):
        return True
    return default


def cache_key(*, provider: str, physical_model: str,
              prompt_sha256: str, params: dict) -> str:
    payload = canonical_json({
        "provider": provider,
        "physical_model": physical_model,
        "prompt_sha256": prompt_sha256,
        "params": params,
    })
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class LLMDiskCache:
    def __init__(self, root: str | Path | None = None, *, enabled: bool = False):
        self.root = Path(root) if root is not None else default_cache_root()
        self.enabled = bool(enabled)
        self.hits = 0
        self.misses = 0

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        p = self._path(key)
        if not p.is_file():
            self.misses += 1
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "response_text" not in data:
                self.misses += 1
                return None
            self.hits += 1
            return data
        except (OSError, json.JSONDecodeError):
            self.misses += 1
            return None

    def put(self, key: str, *, response_text: str, prompt_tokens: int,
            completion_tokens: int, finish_reason: str,
            meta: dict | None = None) -> None:
        if not self.enabled:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        blob = {
            "response_text": response_text,
            "prompt_tokens": int(prompt_tokens),
            "completion_tokens": int(completion_tokens),
            "finish_reason": finish_reason or "stop",
            "created_at": time.time(),
            **(meta or {}),
        }
        tmp = self._path(key).with_suffix(".tmp")
        tmp.write_text(json.dumps(blob, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path(key))
