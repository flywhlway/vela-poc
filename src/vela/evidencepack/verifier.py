"""证据包三级验证（技术方案 §6.4.3）。

L0 自洽：仅需证据包 —— 检测证据包被编辑
L1 库内：证据包 + gold 库 —— 检测幻觉引用
L2 溯源：证据包 + 原始压缩包 —— 最强证明，结论直指原始字节
"""
from __future__ import annotations

import zipfile
from pathlib import Path

from vela.evidencepack.builder import item_digest
from vela.util.hashing import merkle_root, raw_hash


def verify_l0(pack: dict) -> dict:
    digests = [item_digest(i) for i in pack["items"]]
    expect = merkle_root(digests, salt=pack.get("run", {}).get("config_hash", ""))
    ok = expect == pack.get("merkle_root")
    return {"level": "L0", "ok": ok, "expected": expect, "actual": pack.get("merkle_root"),
            "items": len(pack["items"]),
            "detail": "证据包自洽" if ok else "Merkle 根不匹配：证据包内容被修改过"}


def verify_l1(pack: dict, con) -> dict:
    failures = []
    for it in pack["items"]:
        rows = con.execute(
            "SELECT raw_hash, row_hash, line_no, byte_offset FROM log_lines WHERE row_hash=?",
            [it["row_hash"]]).fetchall()
        if not rows:
            failures.append({"seq": it["seq"], "row_hash": it["row_hash"],
                             "reason": "ROW_HASH_NOT_FOUND_IN_DB"})
            continue
        if rows[0][0] != it["raw_hash_b3_128"]:
            failures.append({"seq": it["seq"], "row_hash": it["row_hash"],
                             "reason": "RAW_HASH_MISMATCH",
                             "expected": it["raw_hash_b3_128"], "actual": rows[0][0]})
    return {"level": "L1", "ok": not failures, "checked": len(pack["items"]),
            "failures": failures,
            "detail": "全部引用在库中可解析且指纹一致" if not failures else "存在悬空或不一致的引用"}


def verify_l2(pack: dict, archive_path: str | Path) -> dict:
    """从原始压缩包按 sha256 定位成员，按 byte_offset/byte_len 重读字节并重算 BLAKE3。"""
    archive_path = Path(archive_path)
    failures = []
    checked = 0
    with zipfile.ZipFile(archive_path) as zf:
        sha_index: dict[str, str] = {}
        import hashlib
        for info in zf.infolist():
            if info.is_dir():
                continue
            with zf.open(info) as fh:
                sha_index[hashlib.sha256(fh.read()).hexdigest()] = info.filename
        for it in pack["items"]:
            src = it["source"]
            member = sha_index.get(src.get("file_sha256") or "")
            if member is None:
                failures.append({"seq": it["seq"], "reason": "FILE_NOT_FOUND_BY_SHA256",
                                 "file_path": src.get("file_path")})
                continue
            with zf.open(member) as fh:
                blob = fh.read()
            # 精确切片：byte_len 已包含行尾符，与建库时 raw_hash 的输入字节完全一致
            chunk = blob[src["byte_offset"]: src["byte_offset"] + src["byte_len"]]
            actual = raw_hash(chunk)
            checked += 1
            if actual != it["raw_hash_b3_128"]:
                failures.append({"seq": it["seq"], "reason": "HASH_MISMATCH",
                                 "expected": it["raw_hash_b3_128"], "actual": actual})
    return {"level": "L2", "ok": not failures, "checked": checked, "failures": failures,
            "detail": "全部证据可溯源至原始压缩包字节" if not failures
                      else "存在无法从原始字节复算一致的证据项"}


def verify_all(pack: dict, con=None, archive_path: str | Path | None = None) -> dict:
    out = {"evidence_id": pack.get("evidence_id"), "claim": pack.get("claim"), "levels": []}
    out["levels"].append(verify_l0(pack))
    if con is not None:
        out["levels"].append(verify_l1(pack, con))
    if archive_path is not None:
        out["levels"].append(verify_l2(pack, archive_path))
    out["ok"] = all(x["ok"] for x in out["levels"])
    return out
