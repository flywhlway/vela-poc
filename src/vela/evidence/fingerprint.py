"""Stage-5 指纹计算与分词（三级指纹 + 引用锚点）。"""
from __future__ import annotations

import re

from vela.util.hashing import norm_hash as _norm_hash
from vela.util.hashing import raw_hash as _raw_hash
from vela.util.hashing import row_hash as _row_hash
from vela.util.textutil import canonicalize

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}|[0-9]+|0x[0-9a-fA-F]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def fingerprints(raw_bytes: bytes, raw_text: str, file_path: str, line_no: int) -> dict:
    """一次性算出一行的三级指纹 + 引用锚点。"""
    canon = canonicalize(raw_text)
    return {
        "raw_hash": _raw_hash(raw_bytes),
        "norm_hash": _norm_hash(canon),
        "row_hash": _row_hash(raw_text, file_path, line_no),
        "canon": canon,
    }


def tokenize_for_search(message: str) -> str:
    """
    FTS 索引源：英文按词切分 + 中文按 bigram 切分（无外部分词依赖，确定性）。
    """
    if not message:
        return ""
    toks = [t.lower() for t in _TOKEN_RE.findall(message)]
    cjk = _CJK_RE.findall(message)
    if len(cjk) >= 2:
        toks.extend(cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1))
    toks.extend(cjk)
    seen: set[str] = set()
    out: list[str] = []
    for t in toks:                       # 去重但保持首现顺序 -> 确定性
        if t not in seen:
            seen.add(t)
            out.append(t)
    return " ".join(out)


class DupTracker:
    """行级重复统计：绝不删行，只标注 dup_rank / dup_count（技术方案 §6.3）。"""

    def __init__(self) -> None:
        self._rank: dict[int, int] = {}

    def observe(self, norm: int) -> int:
        r = self._rank.get(norm, 0)
        self._rank[norm] = r + 1
        return r

    def counts(self) -> dict[int, int]:
        return dict(self._rank)
