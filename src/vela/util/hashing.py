"""
三级指纹 + 引用锚点指纹。

对应关系（两份文档的统一点）：
  L1  raw_hash   = BLAKE3-128(原始字节)        —— 技术方案 §6.1，字节级完整性/防篡改/L2 溯源
  L2  norm_hash  = xxh3-64(规范化文本)         —— 技术方案 §6.1，行级去重语义
  L3  template_id                              —— 由 MiniDrain 给出（见 evidence/template.py）
  ANCHOR row_hash = xxh3-64(raw ‖ path ‖ line_no) —— 交底书机制二(a)，报告引用四元组的锚点

设计要点：
  * raw_hash 必须哈希"字节"而非解码后的字符串（GBK/UTF-8 转换非双射，否则不可复现）。
  * row_hash 的碰撞域被 (日志包ID, 文件路径) 自然限定，64 位足够。
  * 可选加速库缺失时自动回退 hashlib.blake2b，摘要长度与语义保持一致，
    但**跨实现比较指纹前必须校验 algo 标识**（见 fingerprint_algos()）。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Union

try:                                    # pragma: no cover - 取决于环境
    import blake3 as _blake3
    _HAS_BLAKE3 = True
except Exception:                       # pragma: no cover
    _blake3 = None
    _HAS_BLAKE3 = False

try:                                    # pragma: no cover
    import xxhash as _xxhash
    _HAS_XXHASH = True
except Exception:                       # pragma: no cover
    _xxhash = None
    _HAS_XXHASH = False

Bytesish = Union[bytes, bytearray, memoryview]


def fingerprint_algos() -> dict[str, str]:
    """返回当前实际生效的算法标识，写入 runs.config_hash 参与可复现性校验。"""
    return {
        "raw_hash": "blake3-128" if _HAS_BLAKE3 else "blake2b-128",
        "norm_hash": "xxh3-64" if _HAS_XXHASH else "blake2b-64",
        "row_hash": "xxh3-64" if _HAS_XXHASH else "blake2b-64",
    }


def _normalize_eol(data: Bytesish) -> bytes:
    """L1 规范化：唯一允许的修改是 CRLF -> LF。"""
    b = bytes(data)
    return b.replace(b"\r\n", b"\n")


def raw_hash(data: Bytesish) -> str:
    """L1：原始字节的 128bit 指纹，返回 32 位小写十六进制。"""
    b = _normalize_eol(data)
    if _HAS_BLAKE3:
        return _blake3.blake3(b).digest(length=16).hex()
    return hashlib.blake2b(b, digest_size=16).hexdigest()


def norm_hash(text: str) -> int:
    """L2：规范化文本的 64bit 指纹（无符号整数，落 UBIGINT 列）。"""
    b = text.encode("utf-8", errors="replace")
    if _HAS_XXHASH:
        return _xxhash.xxh3_64_intdigest(b)
    return int.from_bytes(hashlib.blake2b(b, digest_size=8).digest(), "big")


def row_hash(raw_line: str, file_path: str, line_no: int) -> str:
    """
    交底书机制二(a)：行级稳定证据指纹。
    row_hash = H(原始行文本 ‖ 文件路径 ‖ 文件内行序)

    用 \\x1f 作为域分隔符，杜绝 ("ab","c") 与 ("a","bc") 撞域的歧义。
    返回 16 位小写十六进制字符串（便于在报告正文中被人和程序同时识别）。
    """
    payload = f"{raw_line}\x1f{file_path}\x1f{line_no}".encode("utf-8", errors="replace")
    if _HAS_XXHASH:
        return format(_xxhash.xxh3_64_intdigest(payload), "016x")
    return hashlib.blake2b(payload, digest_size=8).hexdigest()


def sha256_bytes(data: Bytesish) -> str:
    return hashlib.sha256(bytes(data)).hexdigest()


def sha256_file(path: Union[str, Path], chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            blk = fh.read(chunk)
            if not blk:
                break
            h.update(blk)
    return h.hexdigest()


def merkle_root(item_digests: list[str], salt: str = "") -> str:
    """
    技术方案 §6.4.2：对 item 摘要排序后拼接再哈希，使根与 item 顺序无关。
    salt 传入 run.config_hash，把"用什么规则算出来的"绑进根。
    """
    joined = "".join(sorted(item_digests)) + "|" + salt
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()
