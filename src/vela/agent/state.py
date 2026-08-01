"""会话状态：可序列化、可 checkpoint、可续跑。"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from vela.util.timeutil import iso

UTC = timezone.utc


@dataclass
class RoundRecord:
    round_no: int
    selected_skill: str | None = None
    thought: str = ""
    actions: list[dict] = field(default_factory=list)
    tool_calls: list[dict] = field(default_factory=list)
    kept_row_hashes: list[str] = field(default_factory=list)
    new_row_hashes: list[str] = field(default_factory=list)
    compression: dict = field(default_factory=dict)
    evidence_tokens: int = 0
    llm_tokens: int = 0
    productive: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class SessionState:
    session_id: str
    db_path: str
    question: str = "本次 OTA 升级为何失败？请给出根因与证据链。"
    started_at: str = field(default_factory=lambda: iso(datetime.now(UTC)))
    round_no: int = 0
    status: str = "running"          # running | answered | human_gate | unanswerable | budget_exhausted
    signals: dict = field(default_factory=dict)
    evidence_digest: list[str] = field(default_factory=list)
    seen_row_hashes: list[str] = field(default_factory=list)
    used_skills: list[str] = field(default_factory=list)
    unproductive_skills: list[str] = field(default_factory=list)
    executed_probes: list[str] = field(default_factory=list)  # "{skill_id}:{args_hash}"
    tools_used: list[str] = field(default_factory=list)
    rounds: list[RoundRecord] = field(default_factory=list)
    evidence_pool: list[dict] = field(default_factory=list)
    root_cause: dict = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    report_md: str = ""
    evidence_pack: dict = field(default_factory=dict)
    citation_check: dict = field(default_factory=dict)
    consecutive_barren_rounds: int = 0
    ended_at: str | None = None

    # ------------------------------------------------------------------ #
    @property
    def seen(self) -> set[str]:
        return set(self.seen_row_hashes)

    def mark_seen(self, hashes: list[str]) -> list[str]:
        """返回本轮新增（此前从未见过）的 row_hash —— 机制三的"新证据"判定依据。"""
        known = self.seen
        new = [h for h in dict.fromkeys(hashes) if h not in known]
        self.seen_row_hashes.extend(new)
        return new

    def excluded_skills(self) -> list[str]:
        """程序化历史规避：从候选集中物理剔除，而不是"提示模型别选"。

        剔除范围 = 未产出有效新证据的技能（unproductive-only）。
        已用技能允许在不同探针 args 下复用；同 (skill_id, args) 由 executed_probes 去重，
        避免确定性探针重跑浪费预算。unproductive_skills 仍是"该假设已被证据否定"的
        可观测指标。
        """
        return sorted(set(self.unproductive_skills))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["rounds"] = [asdict(r) if not isinstance(r, dict) else r for r in self.rounds]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SessionState":
        rounds = [RoundRecord(**r) for r in d.get("rounds", [])]
        payload = {k: v for k, v in d.items() if k != "rounds"}
        st = cls(**payload)
        st.rounds = rounds
        return st
