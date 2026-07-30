"""JSONL 读写：可观测事件、审计流、评测明细的统一落盘格式。

写入采用"追加 + flush + fsync"，保证进程被杀后已写事件不丢——
这是交底书机制六"杀进程续跑"在本地 POC 的等价实现。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable, Iterator


def append_jsonl(path: str | Path, record: dict[str, Any], fsync: bool = True) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        if fsync:
            os.fsync(fh.fileno())


def read_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return
    with open(p, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_json(path: str | Path, obj: Any, fsync: bool = True) -> Path:
    """原子写：先写临时文件再 os.replace，杜绝半截文件。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=2, sort_keys=True, default=str)
        fh.flush()
        if fsync:
            os.fsync(fh.fileno())
    os.replace(tmp, p)
    return p


def read_json(path: str | Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def canonical_json(obj: Any) -> str:
    """规范 JSON：键排序 + 紧凑分隔符，用于计算稳定摘要。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def iter_all(paths: Iterable[str | Path]) -> Iterator[dict[str, Any]]:
    for p in paths:
        yield from read_jsonl(p)
