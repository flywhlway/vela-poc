"""确定性优先的 ID 生成。

POC 的可复现性要求：给定 seed 时全部 ID 必须可重放。
因此 run_id / session_id 支持显式 seed；无 seed 时才退化为时间+随机。
"""
from __future__ import annotations

import hashlib
import os
import time

_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"          # Crockford Base32，去掉易混字符


def _b32(n: int, width: int) -> str:
    out = []
    for _ in range(width):
        out.append(_B32[n % 32])
        n //= 32
    return "".join(reversed(out))


def new_run_id(seed: str | None = None) -> str:
    """ULID 风格：时间戳(10) + 随机/派生(16)。seed 非空时完全确定。"""
    if seed is not None:
        d = hashlib.blake2b(seed.encode("utf-8"), digest_size=16).digest()
        ts = int.from_bytes(d[:6], "big") % (1 << 48)
        rnd = int.from_bytes(d[6:], "big")
    else:                                            # pragma: no cover - 非确定分支
        ts = int(time.time() * 1000)
        rnd = int.from_bytes(os.urandom(10), "big")
    return _b32(ts, 10) + _b32(rnd, 16)


def new_session_id(seed: str | None = None) -> str:
    return "S-" + new_run_id(seed)[:16]


def stable_id(prefix: str, *parts: object) -> str:
    """由内容派生的稳定 ID：同内容必同 ID，用于幂等与去重。"""
    payload = "\x1f".join(str(p) for p in parts)
    return f"{prefix}-{hashlib.blake2b(payload.encode('utf-8'), digest_size=8).hexdigest()}"
