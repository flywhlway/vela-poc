"""出站脱敏（配置驱动，7 条规则）。"""
from __future__ import annotations

import re
from dataclasses import dataclass

from vela.config import load_yaml
from vela.util.textutil import mask_vin


@dataclass
class RedactionResult:
    text: str
    hits: dict[str, int]

    @property
    def total(self) -> int:
        return sum(self.hits.values())


class Redactor:
    def __init__(self, cfg: dict | None = None):
        cfg = cfg if cfg is not None else load_yaml("llm.yaml").get("redaction", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.rules = [(r["name"], re.compile(r["pattern"]), r["repl"])
                      for r in cfg.get("rules", [])]

    def redact(self, text: str) -> RedactionResult:
        if not self.enabled or not text:
            return RedactionResult(text, {})
        hits: dict[str, int] = {}
        out = text
        for name, rx, repl in self.rules:
            if name == "vin":
                def _v(m: re.Match) -> str:
                    hits["vin"] = hits.get("vin", 0) + 1
                    return mask_vin(m.group(0))
                out = rx.sub(_v, out)
                continue
            out, n = rx.subn(repl, out)
            if n:
                hits[name] = hits.get(name, 0) + n
        return RedactionResult(out, hits)
