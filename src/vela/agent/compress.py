"""机制一：预算感知证据压缩 + 压缩痕迹回馈闭环。

分级保留（与通用日志摘要"保高频丢低频"相反——故障信号恰恰在低频侧）：
  N3 白名单：命中错误语义词的行，每模板最多保留 whitelist_cap_per_template 条
  N2 稀有豁免：全库出现次数 <= rare_template_max_count 的模板整体保留（根因常在此）
  N1 模板配额：其余行同模板只保留 template_quota_lines 条，其余折叠为计数
仍超预算 → 滑窗摘要：按 slide_window_seconds 分块，用块级统计替代明细。

压缩痕迹（compression trace）随证据一并回传给模型：告诉它"哪些内容被折叠了、折叠了多少、
时间范围是什么、如何取回"。模型据此可发起精确的二次下钻，形成闭环，
而不是在不知情的情况下基于残缺证据下结论。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from vela.config import BudgetProfile
from vela.util.textutil import estimate_tokens

_TIER_NAMES = {3: "whitelist", 2: "rare_exempt", 1: "template_quota", 0: "folded"}


@dataclass
class CompressionResult:
    kept: list[dict] = field(default_factory=list)
    trace: dict = field(default_factory=dict)
    tokens_before: int = 0
    tokens_after: int = 0
    windows: list[dict] = field(default_factory=list)

    @property
    def ratio(self) -> float:
        return round(self.tokens_after / self.tokens_before, 4) if self.tokens_before else 1.0

    def as_context(self) -> dict:
        """交给模型的完整证据视图：保留行 + 压缩痕迹 + 滑窗摘要。"""
        return {"evidence": self.kept, "compression_trace": self.trace,
                "window_summaries": self.windows}


def _row_text(r: dict) -> str:
    return " | ".join(str(r.get(k, "")) for k in
                      ("ts_utc", "component", "level_norm", "ota_phase", "preview", "raw_line"))


def _is_whitelisted(r: dict, terms: tuple[str, ...]) -> bool:
    blob = (str(r.get("raw_line") or r.get("preview") or "")).lower()
    lvl = str(r.get("level_norm") or "").upper()
    if lvl in ("ERROR", "FATAL"):
        return True
    return any(t in blob for t in terms)


class EvidenceCompressor:
    def __init__(self, budget: BudgetProfile, template_occurrences: dict | None = None):
        self.b = budget
        self.occ = {int(k): int(v) for k, v in (template_occurrences or {}).items()}

    # ------------------------------------------------------------------ #
    def compress(self, rows: list[dict], token_budget: int | None = None) -> CompressionResult:
        budget = int(token_budget if token_budget is not None else self.b.round_evidence_tokens)
        rows = [r for r in rows if r is not None]
        before = estimate_tokens("\n".join(_row_text(r) for r in rows))

        # ---- 分层打标 ----
        tiered: dict[int, list[dict]] = {3: [], 2: [], 1: []}
        for r in rows:
            tid = r.get("template_id")
            occ = self.occ.get(int(tid), 0) if tid is not None else 0
            if _is_whitelisted(r, self.b.whitelist_terms):
                tier = 3
            elif occ and occ <= self.b.rare_template_max_count:
                tier = 2
            else:
                tier = 1
            tiered[tier].append({**r, "_tier": tier, "_occ": occ})

        kept: list[dict] = []
        folded: dict[str, dict] = {}

        def _fold(tid, tier, items):
            key = f"{tier}:{tid}"
            e = folded.setdefault(key, {"template_id": tid, "tier": _TIER_NAMES[tier],
                                        "folded_count": 0, "ts_from": None, "ts_to": None,
                                        "sample": "", "components": set()})
            e["folded_count"] += len(items)
            ts = sorted(str(i.get("ts_utc") or "") for i in items if i.get("ts_utc"))
            if ts:
                e["ts_from"] = min(filter(None, [e["ts_from"], ts[0]]))
                e["ts_to"] = max(filter(None, [e["ts_to"], ts[-1]]))
            e["components"].update(str(i.get("component") or "") for i in items)
            if not e["sample"]:
                e["sample"] = str(items[0].get("raw_line") or items[0].get("preview") or "")[:160]

        # N3 白名单封顶：超出上限时保留首尾，中间折叠
        for tid, items in _group(tiered[3]):
            cap = self.b.whitelist_cap_per_template
            if len(items) <= cap:
                kept.extend(items)
            else:
                head, tail = items[: cap - 1], items[-1:]
                kept.extend(head + tail)
                _fold(tid, 3, items[cap - 1: -1])
        # N2 稀有模板整体豁免
        for _, items in _group(tiered[2]):
            kept.extend(items)
        # N1 模板配额
        for tid, items in _group(tiered[1]):
            q = self.b.template_quota_lines
            kept.extend(items[:q])
            if len(items) > q:
                _fold(tid, 1, items[q:])

        kept.sort(key=lambda r: (str(r.get("ts_utc") or ""), int(r.get("line_id") or 0)))
        after = estimate_tokens("\n".join(_row_text(r) for r in kept))

        # ---- 仍超预算 → 滑窗摘要 ----
        windows: list[dict] = []
        overflow = False
        if after > budget:
            overflow = True
            kept, windows, after = self._slide(kept, budget)

        trace = {
            "input_rows": len(rows), "kept_rows": len(kept),
            "tokens_before": before, "tokens_after": after,
            "budget_tokens": budget, "compression_ratio": round(after / before, 4) if before else 1.0,
            "tier_policy": {
                "N3_whitelist_cap_per_template": self.b.whitelist_cap_per_template,
                "N2_rare_template_max_count": self.b.rare_template_max_count,
                "N1_template_quota_lines": self.b.template_quota_lines,
            },
            "folded": sorted(
                [{**v, "components": sorted(v["components"])} for v in folded.values()],
                key=lambda x: -x["folded_count"])[:40],
            "folded_total": sum(v["folded_count"] for v in folded.values()),
            "slide_window_applied": overflow,
            "notice": ("以上 folded 条目表示同模板的重复行已被折叠为计数摘要；"
                       "若需要其中某条模板的完整明细，请用 search_logs(template_id=...) "
                       "或 get_lines(line_ids=[...]) 精确取回。被折叠的内容不代表不存在。"),
        }
        return CompressionResult(kept=kept, trace=trace, tokens_before=before,
                                 tokens_after=after, windows=windows)

    def _slide(self, rows: list[dict], budget: int) -> tuple[list[dict], list[dict], int]:
        """按时间块折叠：错误级明细优先保留，其余块化为统计摘要。"""
        win = self.b.slide_window_seconds
        blocks: dict[str, list[dict]] = {}
        for r in rows:
            ts = str(r.get("ts_utc") or "")
            key = ts[:16] if win >= 60 else ts[:19]   # 分钟/秒级块键（确定性）
            blocks.setdefault(key, []).append(r)
        priority = [r for r in rows if str(r.get("level_norm") or "").upper() in ("ERROR", "FATAL")]
        keep: list[dict] = []
        acc = 0
        for r in priority:
            t = estimate_tokens(_row_text(r))
            if acc + t > budget:
                break
            keep.append(r)
            acc += t
        kept_ids = {id(r) for r in keep}
        summaries = []
        for key in sorted(blocks):
            items = blocks[key]
            rest = [i for i in items if id(i) not in kept_ids]
            if not rest:
                continue
            summaries.append({
                "window": key, "lines": len(rest),
                "components": sorted({str(i.get("component") or "") for i in rest})[:8],
                "levels": _count(str(i.get("level_norm") or "") for i in rest),
                "templates": sorted({int(i["template_id"]) for i in rest
                                     if i.get("template_id") is not None})[:12],
                "sample": str(rest[0].get("raw_line") or rest[0].get("preview") or "")[:120],
            })
        keep.sort(key=lambda r: (str(r.get("ts_utc") or ""), int(r.get("line_id") or 0)))
        return keep, summaries, acc


def _group(rows: list[dict]):
    """按 template_id 分组，组内按 (ts, line_id) 稳定排序；分组顺序确定。"""
    g: dict = {}
    for r in rows:
        g.setdefault(r.get("template_id"), []).append(r)
    for tid in sorted(g, key=lambda x: (x is None, x)):
        items = sorted(g[tid], key=lambda r: (str(r.get("ts_utc") or ""),
                                              int(r.get("line_id") or 0)))
        yield tid, items


def _count(it) -> dict:
    out: dict[str, int] = {}
    for x in it:
        out[x] = out.get(x, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
