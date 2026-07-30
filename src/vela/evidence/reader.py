"""Stage-2 行迭代器：字节偏移、多行合并、坏行标记。

关键点：byte_offset/byte_len 记录的是**解压后、解码前**的字节位置，
这是 L2 溯源验证（从原始压缩包重新读回字节重算指纹）成立的前提。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass
class RawRecord:
    line_no: int              # 记录起始物理行号（1-based）
    byte_offset: int          # 记录起始字节偏移
    byte_len: int             # 记录总字节长度（含多行）
    line_span: int            # 跨越的物理行数
    raw_bytes: bytes          # 原始字节（未解码）
    text: str                 # 解码后的文本
    decode_error: bool = False
    truncated: bool = False


class MultilineAggregator:
    """把栈帧等续行并入上一条记录。判定纯正则、无状态回溯，确定性。"""

    def __init__(self, patterns: list[str], max_span: int = 200):
        self.res = [re.compile(p) for p in patterns]
        self.max_span = max_span

    def is_continuation(self, text: str) -> bool:
        return any(r.search(text) for r in self.res)


def iter_records(path: Path, encoding: str, *, max_line_bytes: int = 262_144,
                 aggregator: MultilineAggregator | None = None) -> Iterator[RawRecord]:
    offset = 0
    line_no = 0
    pending: RawRecord | None = None

    with open(path, "rb") as fh:
        for raw in fh:
            line_no += 1
            blen = len(raw)
            body = raw.rstrip(b"\r\n")
            truncated = False
            if len(body) > max_line_bytes:
                body = body[:max_line_bytes]
                truncated = True
            try:
                text = body.decode(encoding)
                derr = False
            except (UnicodeDecodeError, LookupError):
                text = body.decode(encoding, errors="replace")
                derr = True

            if (pending is not None and aggregator is not None
                    and aggregator.is_continuation(text)
                    and pending.line_span < aggregator.max_span):
                pending.raw_bytes += raw
                pending.byte_len += blen
                pending.line_span += 1
                pending.text += "\n" + text
                pending.decode_error = pending.decode_error or derr
                pending.truncated = pending.truncated or truncated
                offset += blen
                continue

            if pending is not None:
                yield pending
            pending = RawRecord(line_no=line_no, byte_offset=offset, byte_len=blen,
                                line_span=1, raw_bytes=raw, text=text,
                                decode_error=derr, truncated=truncated)
            offset += blen

    if pending is not None:
        yield pending


def count_lines(path: Path) -> int:
    n = 0
    with open(path, "rb") as fh:
        for _ in fh:
            n += 1
    return n
