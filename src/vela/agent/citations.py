"""机制二：系统级引用校验（不信任模型自述）。

模型报告里的每一个 [[EV:row_hash]] 都必须：
  1. 语法合法（16 位十六进制）
  2. 存在于本次会话的证据集中（模型不能引用自己没看过的行）
  3. 存在于列式库中且 raw_hash 一致（模型不能凭空捏造一个 row_hash）
任何一条不满足即为悬空引用（dangling citation）。悬空率是可量化的质量闸门。
"""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

CITE_RX = re.compile(r"\[\[EV:([0-9a-fA-F]{8,32})\]\]")
TRAILER_RX = re.compile(r"<!--\s*citations:\s*(\[[^\]]*\])\s*-->")
_HEADING_RX = re.compile(r"^\s*#{1,6}\s")
_RULE_RX = re.compile(r"^\s*[-*_]{3,}\s*$")
_SENTENCE_SPLIT_RX = re.compile(r"[。！？.!?\n]+")


@dataclass
class CitationReport:
    total: int = 0
    valid: list[str] = field(default_factory=list)
    dangling: list[dict] = field(default_factory=list)
    unused_evidence: list[str] = field(default_factory=list)

    @property
    def dangling_rate(self) -> float | None:
        if self.total == 0:
            return None
        return round(len(self.dangling) / self.total, 4)

    @property
    def has_citations(self) -> bool:
        return self.total > 0

    @property
    def ok(self) -> bool:
        return self.has_citations and not self.dangling

    def to_dict(self) -> dict:
        return {"total_citations": self.total, "valid": len(self.valid),
                "dangling": self.dangling, "dangling_rate": self.dangling_rate,
                "unused_evidence_count": len(self.unused_evidence),
                "has_citations": self.has_citations, "ok": self.ok}


def split_factual_sentences(text: str) -> list[str]:
    """确定性启发式切分事实句：中英文句号/叹问号/换行；丢弃空串、标题、分隔线。"""
    out: list[str] = []
    for part in _SENTENCE_SPLIT_RX.split(text or ""):
        s = part.strip()
        if not s:
            continue
        if _HEADING_RX.match(s) or _RULE_RX.match(s):
            continue
        out.append(s)
    return out


def citation_coverage(text: str) -> float:
    """含至少一个 [[EV:…]] 的事实句数 / 事实句总数；无事实句时返回 1.0。"""
    sents = split_factual_sentences(text)
    if not sents:
        return 1.0
    covered = sum(1 for s in sents if CITE_RX.search(s))
    return round(covered / len(sents), 4)


def extract_citations(text: str) -> list[str]:
    out = list(dict.fromkeys(CITE_RX.findall(text or "")))
    m = TRAILER_RX.search(text or "")
    if m:
        try:
            for h in json.loads(m.group(1)):
                if isinstance(h, str) and h not in out:
                    out.append(h)
        except json.JSONDecodeError:
            pass
    return out


def citation_ratio_ok(text: str, chain_len: int, min_ratio: float) -> bool:
    """ORCH-08：有效引用数 ≥ ceil(min_ratio * chain_len)；空链视为通过。"""
    if chain_len <= 0:
        return True
    return len(extract_citations(text)) >= math.ceil(float(min_ratio) * chain_len)


def verify_citations(text: str, evidence_hashes: list[str], api=None) -> CitationReport:
    cites = extract_citations(text)
    ev = set(evidence_hashes)
    rep = CitationReport(total=len(cites))
    db_hits: set[str] = set()
    if api is not None and cites:
        rows = api._q("SELECT row_hash FROM log_lines WHERE row_hash IN (SELECT unnest($h))",
                      {"h": cites})
        db_hits = {r["row_hash"] for r in rows}
    for h in cites:
        if h not in ev:
            reason = ("NOT_IN_EVIDENCE_SET" if (api is None or h in db_hits)
                      else "NOT_IN_DB_AND_NOT_IN_EVIDENCE")
            rep.dangling.append({"row_hash": h, "reason": reason})
        elif api is not None and h not in db_hits:
            rep.dangling.append({"row_hash": h, "reason": "NOT_FOUND_IN_DB"})
        else:
            rep.valid.append(h)
    rep.unused_evidence = sorted(ev - set(cites))
    return rep


def strip_dangling(text: str, dangling: list[dict]) -> str:
    """把悬空引用在报告中显式标注出来，而不是静默删除——留痕优于粉饰。"""
    out = text
    for d in dangling:
        out = out.replace(f"[[EV:{d['row_hash']}]]",
                          f"[[EV:{d['row_hash']}｜⚠引用校验失败:{d['reason']}]]")
    return out
