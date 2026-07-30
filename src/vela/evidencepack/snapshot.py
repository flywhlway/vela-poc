"""证据快照固化与双源解析（交底书机制二(c)）。

留存期内：实时查询列式库返回 ±K 行完整上下文（source=live）
过期/删除后：自动回退渲染归档快照并标注来源（source=snapshot）
从而使报告自包含，证据可核验期从日志留存期延展至报告全生命周期。
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from vela.util.jsonl import read_json, write_json
from vela.util.timeutil import iso

UTC = timezone.utc


class SnapshotStore:
    """报告归档时固化的证据快照仓库（POC 用本地 JSON；生产替换为对象存储）。"""

    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, report_id: str) -> Path:
        return self.root / f"{report_id}.snapshot.json"

    def freeze(self, report_id: str, api, row_hashes: list[str], context_k: int = 5) -> dict:
        """对报告引用的每个 row_hash 抓取锚点行及上下文 ±K 行原文并固化。"""
        snaps: dict[str, dict] = {}
        for h in sorted(set(row_hashes)):
            res = api.call("get_lines", row_hashes=[h], include_raw=False)
            if not res.rows:
                snaps[h] = {"row_hash": h, "resolvable": False,
                            "reason": "NOT_FOUND_AT_ARCHIVE_TIME"}
                continue
            r = res.rows[0]
            ctx = api.call("get_context", line_id=r["line_id"], before=context_k, after=context_k)
            snaps[h] = {
                "row_hash": h, "resolvable": True,
                "line_id": r["line_id"], "ts_utc": r["ts_utc"], "ts_kind": r["ts_kind"],
                "ts_confidence": r["ts_confidence"], "component": r["component"],
                "level_norm": r["level_norm"], "ota_phase": r["ota_phase"],
                "file_path": r["file_path"], "line_no": r["line_no"],
                "raw_hash": r["raw_hash"], "byte_offset": r["byte_offset"],
                "byte_len": r["byte_len"],
                "context": [{"line_no": x["line_no"], "raw_line": x["raw_line"],
                             "is_anchor": x["is_anchor"]} for x in ctx.rows],
            }
        doc = {"report_id": report_id, "frozen_at_utc": iso(datetime.now(UTC)),
               "context_k": context_k, "count": len(snaps), "snapshots": snaps}
        write_json(self.path_for(report_id), doc)
        return doc

    def load(self, report_id: str) -> dict | None:
        p = self.path_for(report_id)
        return read_json(p) if p.exists() else None


def resolve_citation(row_hash: str, *, api=None, snapshot: dict | None = None,
                     context_k: int = 50) -> dict:
    """
    双源证据解析：
      1) 优先实时查询列式库（留存期内，返回完整上下文）
      2) 库中不可解析时回退归档快照，并显式标注 source=snapshot
      3) 两者皆不可用时返回 UNRESOLVABLE（报告仍应显示该引用曾存在）
    """
    if api is not None:
        try:
            res = api.call("get_lines", row_hashes=[row_hash], include_raw=True)
            if res.rows:
                r = res.rows[0]
                ctx = api.call("get_context", line_id=r["line_id"],
                               before=context_k, after=context_k)
                return {"row_hash": row_hash, "source": "live", "resolvable": True,
                        "anchor": r,
                        "context": [{"line_no": x["line_no"], "raw_line": x["raw_line"],
                                     "is_anchor": x["is_anchor"]} for x in ctx.rows]}
        except Exception:
            pass
    if snapshot:
        s = (snapshot.get("snapshots") or {}).get(row_hash)
        if s and s.get("resolvable"):
            return {"row_hash": row_hash, "source": "snapshot", "resolvable": True,
                    "anchor": {k: s[k] for k in
                               ("line_id", "ts_utc", "component", "level_norm", "file_path",
                                "line_no", "raw_hash") if k in s},
                    "context": s.get("context", []),
                    "note": "原始日志已过期或已删除，以下内容来自归档时固化的证据快照。"}
    return {"row_hash": row_hash, "source": "none", "resolvable": False,
            "note": "该引用既不能在列式库解析，也无归档快照——应在报告中标记并降低结论置信度。"}
