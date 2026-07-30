"""证据包构建（技术方案 §6.4）。"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from vela.util.hashing import merkle_root
from vela.util.ids import stable_id
from vela.util.jsonl import canonical_json, write_json
from vela.util.timeutil import iso
from vela.version import EVIDENCE_PACK_VERSION

UTC = timezone.utc
VALID_ROLES = ("TRIGGER", "CAUSE", "EFFECT", "CONTEXT", "COUNTER")


def item_digest(item: dict) -> str:
    """item_digest = SHA256( canonical_json(item 去掉 raw_line) || raw_hash )"""
    slim = {k: v for k, v in item.items() if k not in ("raw_line", "context_window")}
    return hashlib.sha256((canonical_json(slim) + "|" + str(item.get("raw_hash_b3_128", "")))
                          .encode("utf-8")).hexdigest()


class EvidenceBuilder:
    def __init__(self, api, out_dir: Path | None = None):
        self.api = api
        self.out_dir = Path(out_dir) if out_dir else Path(api.db_path).parent.parent / "evidence"

    def build(self, *, claim: str, items: list[dict], include_context: int = 5,
              aggregates: list[dict] | None = None) -> dict:
        run = self.api._q("SELECT * FROM runs LIMIT 1")
        run = run[0] if run else {}
        ids = [int(i["line_id"]) for i in items if i.get("line_id") is not None]
        hashes = [str(i["row_hash"]) for i in items if i.get("row_hash")]
        role_by_id: dict[int, str] = {}
        role_by_hash: dict[str, str] = {}
        for i in items:
            role = str(i.get("role", "CONTEXT")).upper()
            if role not in VALID_ROLES:
                role = "CONTEXT"
            if i.get("line_id") is not None:
                role_by_id[int(i["line_id"])] = role
            if i.get("row_hash"):
                role_by_hash[str(i["row_hash"])] = role

        conds, params = [], {}
        if ids:
            conds.append("l.line_id IN (SELECT unnest($ids))")
            params["ids"] = ids
        if hashes:
            conds.append("l.row_hash IN (SELECT unnest($hs))")
            params["hs"] = hashes
        if not conds:
            conds.append("1=0")
        rows = self.api._q(f"""
            SELECT l.line_id, l.ts_utc, l.ts_confidence, l.ts_kind, l.component, l.level_norm,
                   l.ota_phase, l.ecu_id, l.file_path, l.line_no, l.byte_offset, l.byte_len,
                   l.raw_hash, l.norm_hash, l.row_hash, l.template_id, l.raw_line,
                   f.file_sha256
            FROM log_lines l LEFT JOIN files f ON f.file_id = l.file_id
            WHERE {' OR '.join(conds)}
            ORDER BY l.ts_utc, l.line_id
        """, params)

        pack_items = []
        for seq, r in enumerate(rows, start=1):
            role = role_by_id.get(r["line_id"]) or role_by_hash.get(r["row_hash"]) or "CONTEXT"
            ctx = self.api.call("get_context", line_id=r["line_id"],
                                before=include_context, after=include_context)
            ctx_hash = hashlib.sha256(
                "\n".join(x["raw_line"] for x in ctx.rows).encode("utf-8")).hexdigest()
            pack_items.append({
                "seq": seq, "role": role,
                "line_uid": f"{run.get('run_id','')}:{r['line_id']}",
                "line_id": r["line_id"],
                "ts_utc": iso(r["ts_utc"]), "ts_confidence": round(float(r["ts_confidence"]), 3),
                "ts_kind": r["ts_kind"],
                "component": r["component"], "level_norm": r["level_norm"],
                "ota_phase": r["ota_phase"], "ecu_id": r["ecu_id"],
                "source": {"file_path": r["file_path"], "file_sha256": r["file_sha256"],
                           "line_no": r["line_no"], "byte_offset": r["byte_offset"],
                           "byte_len": r["byte_len"]},
                "raw_hash_b3_128": r["raw_hash"],
                "norm_hash_xxh3_64": str(r["norm_hash"]),
                "row_hash": r["row_hash"],
                "template_id": r["template_id"],
                "raw_line": r["raw_line"],
                "context_window": {"before": include_context, "after": include_context,
                                   "context_hash": ctx_hash,
                                   "lines": [{"line_no": x["line_no"], "raw_line": x["raw_line"]}
                                             for x in ctx.rows]},
            })

        digests = [item_digest(i) for i in pack_items]
        cfg_hash = run.get("config_hash", "")
        pack = {
            "evidence_pack_version": EVIDENCE_PACK_VERSION,
            "evidence_id": stable_id("EV", claim, cfg_hash, *(i["row_hash"] for i in pack_items)),
            "created_at_utc": iso(datetime.now(UTC)),
            "claim": claim,
            "run": {"run_id": run.get("run_id"), "pipeline_version": run.get("pipeline_version"),
                    "schema_version": run.get("schema_version"),
                    "config_hash": cfg_hash, "input_archive": run.get("input_archive"),
                    "input_sha256": run.get("input_sha256"), "tenant_id": run.get("tenant_id")},
            "items": pack_items,
            "aggregates": aggregates or [],
            "merkle_root": merkle_root(digests, salt=cfg_hash),
            "verification": {
                "algorithm": "BLAKE3-128 per item; SHA-256 Merkle over sorted item digests",
                "instructions": "vela evidence verify --pack <file> [--archive <原始压缩包>]",
                "levels": {"L0": "自洽：Merkle 根与 items 一致（仅需证据包）",
                           "L1": "库内：line_uid/row_hash 在库中存在且指纹一致（需 gold 库）",
                           "L2": "溯源：按 byte_offset/byte_len 从原始包重读字节重算指纹（需原始压缩包）"},
            },
        }
        self.out_dir.mkdir(parents=True, exist_ok=True)
        path = self.out_dir / f"{pack['evidence_id']}.json"
        write_json(path, pack)
        pack["_path"] = str(path)
        return pack
