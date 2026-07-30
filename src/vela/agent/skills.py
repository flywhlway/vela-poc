"""机制三：两段式技能检索 + 程序化历史规避。

第一段（宽召回）：本地确定性向量化（字符 n-gram 哈希 + 余弦）取 Top-N，无需外部向量库；
                 生产可替换为 Ark /embeddings + 向量库，接口不变（see retrieve()）。
第二段（精遴选）：把候选技能的"紧凑表示"（标题 + 触发条件 + 摘要）交给模型择一。

关键点：被判定为"已用且未产出有效新证据"的技能在第一段之后即被程序物理剔除，
不进入模型上下文——因此模型在结构上不可能重复选中它，而不是"被提示不要选"。
"""
from __future__ import annotations

import hashlib
import math
import re

from vela.config import load_skills

_DIM = 512
_TOKEN = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]")


def _tokens(text: str) -> list[str]:
    t = (text or "").lower()
    toks = _TOKEN.findall(t)
    cjk = [c for c in toks if len(c) == 1 and "\u4e00" <= c <= "\u9fff"]
    grams = [cjk[i] + cjk[i + 1] for i in range(len(cjk) - 1)]
    return toks + grams


def embed_local(text: str) -> list[float]:
    """确定性哈希向量（同输入必同输出，跨进程稳定，不依赖 Python hash 随机化）。"""
    v = [0.0] * _DIM
    for tok in _tokens(text):
        h = int.from_bytes(hashlib.blake2b(tok.encode("utf-8"), digest_size=8).digest(), "big")
        v[h % _DIM] += 1.0 if (h >> 16) % 2 else -1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def skill_text(sk: dict) -> str:
    return " ".join([sk.get("title", ""), sk.get("trigger", ""), sk.get("summary", ""),
                     " ".join(str(k) for k in sk.get("tags", [])),
                     " ".join(str(k) for k in sk.get("keywords", []))])


def compact(sk: dict) -> dict:
    """紧凑表示：只给模型标题+触发条件+摘要（+探针工具名），不给完整技能体。"""
    return {"id": sk["id"], "title": sk.get("title", ""), "trigger": sk.get("trigger", ""),
            "summary": sk.get("summary", ""),
            "keywords": [str(k) for k in sk.get("keywords", [])],
            "tools": sk.get("tools", []),
            "probes": sk.get("probes", [])}


class SkillRegistry:
    def __init__(self, skills: list[dict] | None = None):
        self.skills = skills if skills is not None else load_skills()
        self.by_id = {s["id"]: s for s in self.skills}
        self._vec = {s["id"]: embed_local(skill_text(s)) for s in self.skills}

    def retrieve(self, query: str, top_n: int = 8, exclude: list[str] | None = None) -> list[dict]:
        """混合宽召回 → 程序化剔除 → 紧凑候选（顺序稳定：分数降序，同分按 id 升序）。

        单纯依赖稠密向量在短查询上召回不稳（实测会漏掉 SK-ECU-SILENT / SK-DEP-VER 这类
        与查询词面高度重合、但哈希向量夹角不占优的技能）。因此与词面命中做并集召回——
        这也是生产上 BM25 + 向量的标准做法，替换为 Ark /embeddings 时接口不变。
        """
        ex = set(exclude or [])
        pool = [s for s in self.skills if s["id"] not in ex]
        if not pool:
            return []
        qv = embed_local(query)
        dense = sorted((-round(cosine(qv, self._vec[s["id"]]), 6), s["id"]) for s in pool)

        qtoks = set(_tokens(query))
        lex = []
        for s in pool:
            kt = set()
            for k in list(s.get("keywords", [])) + [s.get("title", ""), s.get("trigger", "")]:
                kt |= set(_tokens(str(k)))
            hit = len(qtoks & kt)
            if hit:
                lex.append((-hit, s["id"]))
        lex.sort()

        half = max(1, top_n // 2)
        picked: list[str] = []
        for src in (lex[:half], dense[:top_n], lex, dense):
            for _, sid in src:
                if sid not in picked:
                    picked.append(sid)
                if len(picked) >= top_n:
                    break
            if len(picked) >= top_n:
                break
        return [compact(self.by_id[sid]) for sid in picked[:top_n]]

    def probes_of(self, skill_id: str) -> list[dict]:
        return list((self.by_id.get(skill_id) or {}).get("probes", []))

    def label_of(self, skill_id: str) -> str | None:
        return (self.by_id.get(skill_id) or {}).get("root_cause_label")
