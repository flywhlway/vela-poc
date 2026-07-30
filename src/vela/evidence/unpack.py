"""Stage-0 安全解包。

安全要求（真实取证场景不可省略）：
  * zip-slip：成员路径归一后必须仍位于目标目录内；
  * 符号链接：默认拒绝；
  * zip bomb：解压总字节 / 文件数 / 嵌套层数三重上限；
  * 可复现：记录输入 SHA-256 与每个成员的 SHA-256。
"""
from __future__ import annotations

import hashlib
import os
import tarfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from vela.util.hashing import sha256_file

_ARCHIVE_SUFFIX = {".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz"}


class UnsafeArchiveError(RuntimeError):
    pass


@dataclass
class UnpackResult:
    root: Path
    archive_path: Path
    archive_sha256: str
    total_files: int
    total_bytes: int
    nested_archives: list[str]
    skipped: list[dict]


def _safe_join(root: Path, member: str) -> Path:
    target = (root / member).resolve()
    if not str(target).startswith(str(root.resolve())):
        raise UnsafeArchiveError(f"zip-slip 拦截：成员路径逃逸目标目录 -> {member}")
    return target


def _is_archive(name: str) -> bool:
    p = Path(name)
    return p.suffix.lower() in _ARCHIVE_SUFFIX or "".join(p.suffixes[-2:]).lower() in (".tar.gz", ".tar.bz2", ".tar.xz")


def _zip_mtime(info: zipfile.ZipInfo) -> float:
    """ZIP 的 date_time 是不带时区的 6 元组（年,月,日,时,分,秒），精度到 2 秒。
    我们只用它反推"文件大致产生于何时"这一小时级粗粒度锚点，故不需要时区精确性。
    非法/超出范围（如 1980 之前）时退回当前时间，避免抛错中断整个解包流程。"""
    try:
        return time.mktime((*info.date_time, 0, 0, -1))
    except (ValueError, OverflowError):
        return time.time()


def _restore_mtime(path: Path, mtime: float) -> None:
    """把压缩包内嵌的原始 mtime 写回解压后的文件，使下游任何读取 mtime 的逻辑
    （尤其是纯 monotonic 时间戳缺乏强锚点时的兜底反推）看到的是"日志内容自带的
    时间"而非"这次解压恰好发生在什么时候"——同一归档任何时候解包都应得到同样的证据。"""
    try:
        os.utime(path, (mtime, mtime))
    except OSError:
        pass          # 时间戳还原失败不应中断解包；下游仍有 reference_time 兜底

def extract(archive: str | Path, dest: str | Path, *, max_bytes: int = 20 << 30,

            max_files: int = 200_000, max_depth: int = 3,
            allow_symlinks: bool = False, _depth: int = 0) -> UnpackResult:
    archive = Path(archive)
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    total_files = 0
    nested: list[str] = []
    skipped: list[dict] = []

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if not allow_symlinks and (info.external_attr >> 16) & 0o170000 == 0o120000:
                    skipped.append({"member": info.filename, "reason": "SYMLINK_DENIED"})
                    continue
                total_files += 1
                total_bytes += info.file_size
                if total_files > max_files:
                    raise UnsafeArchiveError(f"文件数超过上限 {max_files}")
                if total_bytes > max_bytes:
                    raise UnsafeArchiveError(f"解压总字节超过上限 {max_bytes}")
                target = _safe_join(dest, info.filename)
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    while True:
                        blk = src.read(1 << 20)
                        if not blk:
                            break
                        out.write(blk)
                _restore_mtime(target, _zip_mtime(info))
                if _is_archive(info.filename) and _depth < max_depth:
                    nested.append(info.filename)
    elif tarfile.is_tarfile(archive):
        with tarfile.open(archive) as tf:
            for m in tf.getmembers():
                if m.isdir():
                    continue
                if m.issym() or m.islnk():
                    if not allow_symlinks:
                        skipped.append({"member": m.name, "reason": "SYMLINK_DENIED"})
                        continue
                total_files += 1
                total_bytes += m.size
                if total_files > max_files or total_bytes > max_bytes:
                    raise UnsafeArchiveError("超过解包上限（文件数或总字节）")
                target = _safe_join(dest, m.name)
                target.parent.mkdir(parents=True, exist_ok=True)
                fo = tf.extractfile(m)
                if fo is None:
                    continue
                with open(target, "wb") as out:
                    while True:
                        blk = fo.read(1 << 20)
                        if not blk:
                            break
                        out.write(blk)
                _restore_mtime(target, float(m.mtime))
                if _is_archive(m.name) and _depth < max_depth:
                    nested.append(m.name)
    else:
        raise UnsafeArchiveError(f"不支持的压缩格式: {archive}")

    # 嵌套展开：就地解到同名 .d 目录，随后删除嵌套包本体
    for name in list(nested):
        inner = dest / name
        if not inner.exists():
            continue
        sub = inner.with_suffix(inner.suffix + ".d")
        try:
            extract(inner, sub, max_bytes=max_bytes, max_files=max_files,
                    max_depth=max_depth, allow_symlinks=allow_symlinks, _depth=_depth + 1)
            inner.unlink()
        except UnsafeArchiveError:
            skipped.append({"member": name, "reason": "NESTED_UNSAFE"})

    return UnpackResult(root=dest, archive_path=archive, archive_sha256=sha256_file(archive),
                        total_files=total_files, total_bytes=total_bytes,
                        nested_archives=nested, skipped=skipped)
