"""Stage-1 文件清单、编码探测、组件归属、滚动组识别。"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from vela.util.hashing import sha256_file

UTC = timezone.utc
_ROTATE_RE = re.compile(r"^(?P<base>.+?)(?:\.(?P<idx>\d+))?(?:\.gz)?$")


@dataclass
class FileEntry:
    file_id: int
    abs_path: Path
    rel_path: str
    file_name: str
    file_sha256: str
    size_bytes: int
    mtime_utc: datetime
    encoding: str
    encoding_conf: float
    component: str
    source_rank: int
    is_binary: bool = False
    is_rotated: bool = False
    rotation_group: str = ""
    rotation_index: int = 0
    alias_of: int | None = None          # 物理重复文件指向首现 file_id
    line_count: int = 0
    record_count: int = 0
    parser_hint: str = ""
    extra: dict = field(default_factory=dict)


def detect_encoding(path: Path, candidates: list[str], sample_bytes: int = 65536,
                    binary_ratio_threshold: float = 0.30) -> tuple[str, float, bool]:
    """返回 (编码, 置信度, 是否二进制)。策略：可解码 + 可打印字符占比打分，确定性无外部依赖。"""
    with open(path, "rb") as fh:
        blob = fh.read(sample_bytes)
    if not blob:
        return "utf-8", 1.0, False

    nontext = sum(1 for b in blob if b < 9 or (13 < b < 32))
    if nontext / len(blob) > binary_ratio_threshold:
        return "binary", 1.0, True

    best, best_score = "latin-1", 0.0
    for enc in candidates:
        try:
            text = blob.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        printable = sum(1 for ch in text if ch.isprintable() or ch in "\n\r\t")
        score = printable / max(1, len(text))
        if enc.startswith("utf") and "\ufffd" not in text:
            score += 0.02                        # 同分时优先 UTF 家族
        if score > best_score:
            best, best_score = enc, score
    return best, round(best_score, 4), False


def _component_for(rel_path: str, rules: list[dict]) -> tuple[str, int]:
    p = "/" + rel_path.replace("\\", "/").lstrip("/")
    for r in rules:
        pat = r["match"]
        if fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p, pat.replace("**/", "*")) or \
           fnmatch.fnmatch(rel_path, pat.lstrip("/")):
            return r["component"], int(r.get("rank", 500))
    return "unknown", 999


def _rotation(file_name: str) -> tuple[str, int, bool]:
    m = _ROTATE_RE.match(file_name)
    if not m:
        return file_name, 0, False
    base, idx = m.group("base"), m.group("idx")
    if idx is None:
        return base, 0, False
    return base, int(idx), True


def _excluded(rel_path: str, patterns: list[str]) -> bool:
    p = rel_path.replace("\\", "/")
    name = p.rsplit("/", 1)[-1]
    for pat in patterns or []:
        if fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(name, pat) or \
           fnmatch.fnmatch("/" + p, pat):
            return True
    return False


def inventory(root: Path, rules: list[dict], *, encoding_candidates: list[str],
              sample_bytes: int = 65536, binary_ratio_threshold: float = 0.30,
              exclude_patterns: list[str] | None = None) -> list[FileEntry]:
    """扫描解包目录，产出稳定排序（按相对路径字典序）的文件清单。"""
    entries: list[FileEntry] = []
    seen_sha: dict[str, int] = {}
    paths = sorted((p for p in root.rglob("*") if p.is_file()),
                   key=lambda p: str(p.relative_to(root)))
    for fid, p in enumerate(paths):
        rel = str(p.relative_to(root)).replace("\\", "/")
        sha = sha256_file(p)
        enc, conf, is_bin = detect_encoding(p, encoding_candidates, sample_bytes, binary_ratio_threshold)
        comp, rank = _component_for(rel, rules)
        base, idx, rotated = _rotation(p.name)
        e = FileEntry(
            file_id=fid, abs_path=p, rel_path=rel, file_name=p.name, file_sha256=sha,
            size_bytes=p.stat().st_size,
            mtime_utc=datetime.fromtimestamp(p.stat().st_mtime, UTC),
            encoding=enc, encoding_conf=conf, component=comp, source_rank=rank,
            is_binary=is_bin, is_rotated=rotated,
            rotation_group=f"{comp}:{base}", rotation_index=idx,
        )
        if _excluded(rel, exclude_patterns or []):
            e.extra["excluded"] = True
        if sha in seen_sha:
            e.alias_of = seen_sha[sha]           # 物理重复：只解析首现，其余登记别名
        else:
            seen_sha[sha] = fid
        entries.append(e)
    return entries


def parse_order(entries: list[FileEntry]) -> list[FileEntry]:
    """
    解析顺序：同一滚动组内按 rotation_index 倒序（.2 -> .1 -> 无后缀），
    保证同组日志的物理行号与时间轴自然递增。
    """
    return sorted([e for e in entries
                   if not e.is_binary and e.alias_of is None and not e.extra.get("excluded")],
                  key=lambda e: (e.component, e.rotation_group, -e.rotation_index, e.rel_path))
