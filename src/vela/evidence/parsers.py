"""Stage-3 解析器注册表：YAML 驱动，新增格式无需改代码。"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from vela.config import load_yaml


@dataclass
class ParseResult:
    parser_name: str
    parser_version: str
    ts_kind: str                 # WALL / MONOTONIC / BOOT_RELATIVE / NONE
    ts_raw: str | None
    ts_format: str | None
    mono_s: float | None
    level_raw: str | None
    level_norm: str
    level_num: int
    logger: str | None
    process: str | None
    pid: int | None
    tid: int | None
    src_loc: str | None
    message: str
    fields: dict[str, str]
    status: str                  # OK / PARTIAL / UNPARSED


class ParserRegistry:
    def __init__(self, cfg: dict[str, Any] | None = None):
        cfg = cfg or load_yaml("parsers.yaml")
        self.level_map: dict[str, str] = {k.upper(): v for k, v in cfg["level_map"].items()}
        self.klevel_map: dict[int, str] = {int(k): v for k, v in cfg["klevel_map"].items()}
        self.level_num: dict[str, int] = cfg["level_num"]
        self.specs: list[dict] = sorted(cfg["parsers"], key=lambda s: int(s.get("priority", 500)))
        self._compiled: list[tuple[dict, re.Pattern | None]] = [
            (s, None if s.get("json") else re.compile(s["regex"])) for s in self.specs
        ]

    # -- 级别归一 --------------------------------------------------------
    def norm_level(self, raw: str | None, klevel: str | None = None,
                   level_cn: str | None = None, cn_map: dict | None = None) -> tuple[str, int]:
        lv = "UNKNOWN"
        if level_cn and cn_map:
            lv = cn_map.get(level_cn, "UNKNOWN")
        elif klevel is not None and klevel != "":
            lv = self.klevel_map.get(int(klevel), "UNKNOWN")
        elif raw:
            lv = self.level_map.get(raw.strip().upper(), "UNKNOWN")
        return lv, self.level_num.get(lv, 0)

    # -- 主入口 ----------------------------------------------------------
    def parse(self, text: str) -> ParseResult:
        head = text.split("\n", 1)[0]
        for spec, rx in self._compiled:
            if spec.get("json"):
                r = self._try_json(head, spec)
                if r:
                    return r
                continue
            m = rx.match(head)
            if not m:
                continue
            g = m.groupdict()
            if spec["name"] == "fallback_raw":
                break
            return self._from_groups(spec, g, head)
        # 兜底
        return ParseResult(parser_name="fallback_raw", parser_version="1.0", ts_kind="NONE",
                           ts_raw=None, ts_format=None, mono_s=None, level_raw=None,
                           level_norm="UNKNOWN", level_num=0, logger=None, process=None,
                           pid=None, tid=None, src_loc=None, message=head,
                           fields=extract_kv(head), status="UNPARSED")

    def _from_groups(self, spec: dict, g: dict, head: str) -> ParseResult:
        lv, ln = self.norm_level(g.get("level"), g.get("klevel"),
                                 g.get("level_cn"), spec.get("level_cn_map"))
        mono = float(g["mono"]) if g.get("mono") else None
        msg = g.get("message") or ""
        return ParseResult(
            parser_name=spec["name"], parser_version=str(spec.get("version", "1.0")),
            ts_kind=spec.get("ts_kind", "WALL"), ts_raw=g.get("ts"),
            ts_format=spec.get("ts_format"), mono_s=mono,
            level_raw=g.get("level") or g.get("level_cn") or g.get("klevel"),
            level_norm=lv, level_num=ln,
            logger=g.get("logger") or g.get("app") or g.get("ctx"),
            process=g.get("process") or g.get("host"),
            pid=int(g["pid"]) if g.get("pid") else None,
            tid=int(g["tid"]) if g.get("tid") else None,
            src_loc=g.get("src_loc"), message=msg,
            fields=extract_kv(msg), status="OK")

    def _try_json(self, head: str, spec: dict) -> ParseResult | None:
        t = head.strip()
        if not (t.startswith("{") and t.endswith("}")):
            return None
        try:
            obj = json.loads(t)
        except Exception:
            return None
        if not isinstance(obj, dict):
            return None
        jm = spec.get("json_map", {})

        def pick(key: str):
            for k in jm.get(key, [key]):
                if k in obj:
                    return obj[k]
            return None

        lv, ln = self.norm_level(str(pick("level") or ""))
        msg = str(pick("message") or "")
        fields = {k: str(v) for k, v in sorted(obj.items())
                  if k not in set(sum(jm.values(), []))}
        return ParseResult(
            parser_name=spec["name"], parser_version=str(spec.get("version", "1.0")),
            ts_kind=spec.get("ts_kind", "WALL"),
            ts_raw=str(pick("ts")) if pick("ts") is not None else None,
            ts_format=spec.get("ts_format"), mono_s=None,
            level_raw=str(pick("level") or ""), level_norm=lv, level_num=ln,
            logger=str(pick("logger")) if pick("logger") is not None else None,
            process=None,
            pid=int(pick("pid")) if str(pick("pid") or "").isdigit() else None,
            tid=int(pick("tid")) if str(pick("tid") or "").isdigit() else None,
            src_loc=None, message=msg, fields=fields, status="OK")


_KV_RE = re.compile(r"(?P<k>[A-Za-z_][\w.\-]{0,40})=(?P<v>\"[^\"]*\"|'[^']*'|[^\s,;]+)")
_MAX_KV = 24


def extract_kv(msg: str) -> dict[str, str]:
    """从消息体抽取 k=v 结构化字段（有上限，防止畸形行撑爆 MAP 列）。"""
    out: dict[str, str] = {}
    for m in _KV_RE.finditer(msg):
        if len(out) >= _MAX_KV:
            break
        out[m.group("k")] = m.group("v").strip("\"'")
    return out


_ECU_RE = re.compile(r"\becu(?:_id)?\s*[=:]\s*(0x[0-9A-Fa-f]{1,4})\b")
_TASK_RE = re.compile(r"\btask(?:_id)?\s*[=:]\s*([A-Za-z0-9\-_]{3,40})\b")
_CAMPAIGN_RE = re.compile(r"\bcampaign(?:_id)?\s*[=:]\s*([A-Za-z0-9\-_]{3,40})\b")
_VIN_RE = re.compile(r"\bvin\s*[=:]\s*([A-HJ-NPR-Z0-9]{17})\b", re.I)
_NRC_RE = re.compile(r"\bnrc\s*[=:]?\s*(0x[0-9A-Fa-f]{2})\b", re.I)
_BLOCK_RE = re.compile(r"\bblock[= ](\d+)\b")


def extract_business(msg: str) -> dict[str, str]:
    """业务关联域抽取：OTA 任务/活动/ECU/VIN/NRC 等（技术方案 §5.1.7）。"""
    out: dict[str, str] = {}
    for name, rx in (("ecu_id", _ECU_RE), ("ota_task_id", _TASK_RE),
                     ("campaign_id", _CAMPAIGN_RE), ("vin", _VIN_RE),
                     ("nrc", _NRC_RE), ("block", _BLOCK_RE)):
        m = rx.search(msg)
        if m:
            out[name] = m.group(1)
    return out
