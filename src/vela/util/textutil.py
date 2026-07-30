"""规范化、token 估算、脱敏。"""
from __future__ import annotations

import math
import re

from vela.version import CANON_RULES_VERSION

# ---------------------------------------------------------------------------
# L2 规范化规则（技术方案 §6.2）—— 顺序敏感：从最具体到最一般
# ⚠️ 规则集一旦上线，变更即破坏 norm_hash 兼容性；版本号参与 config_hash。
# ---------------------------------------------------------------------------
CANON_RULES: list[tuple[str, str]] = [
    (r"\r\n?", "\n"),
    (r"^\s+|\s+$", ""),
    (r"\s+", " "),
    # 时间戳（多形态）
    (r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d{1,9})?(?:Z|[+-]\d{2}:?\d{2})?", "<TS>"),
    (r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d{1,6}", "<TS>"),
    (r"\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d{1,3})?", "<TS>"),
    (r"\[\s*\d+\.\d{6}\]", "<MONO>"),
    (r"\+\d+\.\d{3}s", "<MONO>"),
    # 高基数标识
    (r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", "<UUID>"),
    (r"\b0x[0-9a-fA-F]{4,}\b", "<HEX>"),
    (r"\bpid=\d+\b", "pid=<NUM>"),
    (r"\btid=\d+\b", "tid=<NUM>"),
    (r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b", "<ADDR>"),
    # 数字紧贴单位后缀时 \b 不成立（231ms/512MB），必须单列一条，否则同类行 norm_hash 不同
    (r"(?<![\w.])\d+(?=[a-zA-Z])", "<NUM>"),
    (r"\b\d+\b", "<NUM>"),
]
_COMPILED = [(re.compile(p, re.MULTILINE), r) for p, r in CANON_RULES]


def canonicalize(text: str) -> str:
    """L2 规范化：语义等价的行归一到同一字符串。"""
    out = text
    for rx, repl in _COMPILED:
        out = rx.sub(repl, out)
    return out


def canon_rules_version() -> str:
    return CANON_RULES_VERSION


# ---------------------------------------------------------------------------
# token 估算（确定性；不依赖任何分词器，避免 provider 差异导致预算不可复现）
# ---------------------------------------------------------------------------
_CJK = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")


def estimate_tokens(text: str, bytes_per_token_ascii: float = 4.0,
                    bytes_per_token_cjk: float = 1.5) -> int:
    if not text:
        return 0
    cjk = len(_CJK.findall(text))
    other = len(text) - cjk
    return int(math.ceil(cjk / bytes_per_token_cjk + other / bytes_per_token_ascii))


# ---------------------------------------------------------------------------
# VIN 脱敏：保留后 4 位 + 前缀哈希（技术方案 §5.1.7 vin_masked）
# ---------------------------------------------------------------------------
def mask_vin(vin: str) -> str:
    if not vin or len(vin) < 4:
        return "VIN_****"
    import hashlib
    pre = hashlib.blake2b(vin.encode("utf-8"), digest_size=3).hexdigest()
    return f"VIN_{pre}_{vin[-4:]}"


def truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True
