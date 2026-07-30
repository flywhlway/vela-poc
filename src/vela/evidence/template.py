"""Stage-5 日志模板挖掘：内置 MiniDrain（固定深度解析树）。

为什么内置而非依赖 drain3：
  1. 决定论——本 POC 的评测与 CI 依赖"同输入同模板 ID"，需完全控制迭代顺序与并列消解；
  2. 零外部依赖，离线可跑；
  3. 模板 ID 分配规则需与列式库、压缩机制、证据引用稳定绑定。

算法：长度分桶 -> 前缀 token 逐层下沉（数字类 token 归一为通配）-> 叶子内相似度匹配。
相似度 = 位置一致 token 数 / 总 token 数，阈值默认 0.40。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_NUMERIC = re.compile(r"^[\d.:,\-+/]*\d[\d.:,\-+/]*$")
_HEXY = re.compile(r"^0x[0-9a-fA-F]+$|^[0-9a-fA-F]{8,}$")
_WILDCARD = "<*>"


def tokenize(message: str) -> list[str]:
    return message.replace("\n", " ").split()


def _is_param(tok: str) -> bool:
    return bool(_NUMERIC.match(tok) or _HEXY.match(tok))


@dataclass
class Cluster:
    template_id: int
    tokens: list[str]
    count: int = 0
    first_seen_idx: int = -1
    components: set[str] = field(default_factory=set)
    levels: dict[str, int] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return " ".join(self.tokens)

    @property
    def param_count(self) -> int:
        return sum(1 for t in self.tokens if t == _WILDCARD)


class MiniDrain:
    def __init__(self, sim_threshold: float = 0.40, max_depth: int = 4,
                 max_children: int = 100, max_clusters: int = 5000):
        self.sim_threshold = sim_threshold
        self.max_depth = max(2, max_depth)
        self.max_children = max_children
        self.max_clusters = max_clusters
        self._tree: dict = {}
        self.clusters: dict[int, Cluster] = {}
        self._next_id = 1
        self._seen = 0

    # -- 内部 ------------------------------------------------------------
    def _path(self, tokens: list[str]) -> list[str]:
        key = [str(len(tokens))]
        for i in range(min(self.max_depth - 1, len(tokens))):
            t = tokens[i]
            key.append(_WILDCARD if _is_param(t) else t)
        return key

    def _leaf(self, path: list[str], create: bool) -> list[Cluster] | None:
        node = self._tree
        for k in path[:-1]:
            nxt = node.get(k)
            if nxt is None:
                if not create:
                    return None
                if len(node) >= self.max_children:
                    k = _WILDCARD
                    nxt = node.setdefault(k, {})
                else:
                    nxt = node[k] = {}
            node = nxt
        last = path[-1]
        leaf = node.get(last)
        if leaf is None:
            if not create:
                return None
            if len(node) >= self.max_children:
                last = _WILDCARD
                leaf = node.setdefault(last, [])
            else:
                leaf = node[last] = []
        return leaf

    @staticmethod
    def _similarity(a: list[str], b: list[str]) -> float:
        if not a:
            return 1.0 if not b else 0.0
        same = sum(1 for x, y in zip(a, b) if x == y or x == _WILDCARD)
        return same / len(a)

    @staticmethod
    def _merge(a: list[str], b: list[str]) -> list[str]:
        return [x if x == y else _WILDCARD for x, y in zip(a, b)]

    # -- 对外 ------------------------------------------------------------
    def add(self, message: str, component: str = "", level: str = "") -> int:
        toks = tokenize(message)
        if not toks:
            toks = [""]
        path = self._path(toks)
        leaf = self._leaf(path, create=True)
        assert leaf is not None
        best, best_sim = None, -1.0
        for c in leaf:                                   # 顺序确定：按插入序遍历
            if len(c.tokens) != len(toks):
                continue
            sim = self._similarity(c.tokens, toks)
            if sim > best_sim or (sim == best_sim and best is not None
                                  and c.template_id < best.template_id):
                best, best_sim = c, sim
        if best is not None and best_sim >= self.sim_threshold:
            best.tokens = self._merge(best.tokens, toks)
            best.count += 1
            if component:
                best.components.add(component)
            if level:
                best.levels[level] = best.levels.get(level, 0) + 1
            self._seen += 1
            return best.template_id

        if len(self.clusters) >= self.max_clusters:      # 超限：归入溢出桶，保证有界
            return 0
        cid = self._next_id
        self._next_id += 1
        c = Cluster(template_id=cid, tokens=[_WILDCARD if _is_param(t) else t for t in toks],
                    count=1, first_seen_idx=self._seen)
        if component:
            c.components.add(component)
        if level:
            c.levels[level] = 1
        leaf.append(c)
        self.clusters[cid] = c
        self._seen += 1
        return cid

    def summary(self) -> list[dict]:
        """按 template_id 升序输出（确定性）。"""
        out = []
        for cid in sorted(self.clusters):
            c = self.clusters[cid]
            lvl_mode = max(sorted(c.levels.items()), key=lambda kv: (kv[1], kv[0]))[0] if c.levels else "UNKNOWN"
            out.append({
                "template_id": cid, "template_text": c.text, "param_count": c.param_count,
                "occurrences": c.count, "components": sorted(c.components),
                "level_mode": lvl_mode,
                "is_error_like": bool(re.search(
                    r"fail|error|exception|timeout|abort|panic|denied|nrc|invalid|insufficient|"
                    r"错误|失败|异常|超时|中止", c.text, re.I)),
            })
        return out
