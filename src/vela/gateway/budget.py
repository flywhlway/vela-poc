"""三级 token 预算计量与硬切断（交底书机制一：双水位预算）。

计量键：(tenant_id, session_id, round_no)
  * 轮次级：round_llm_tokens —— 单轮超限即切断，防止一次失控推理烧穿配额
  * 会话级：session_llm_tokens —— 全会话累计上限
  * 租户级：可选，缺省不限（生产接入计费系统时填）
超限抛 BudgetExceeded；调用方（Agent）据此收敛为"证据不足以支撑结论"而非静默截断。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from vela.config import BudgetProfile, load_budget


class BudgetExceeded(RuntimeError):
    def __init__(self, scope: str, used: int, limit: int):
        self.scope, self.used, self.limit = scope, used, limit
        super().__init__(f"{scope} token 预算超限：已用 {used} / 上限 {limit}")


@dataclass
class TokenLedger:
    budget: BudgetProfile = field(default_factory=load_budget)
    tenant_limit: int = 0
    tenant_used: int = 0
    session_used: int = 0
    round_used: int = 0
    round_no: int = 0
    calls: int = 0
    by_logical_model: dict[str, int] = field(default_factory=dict)

    def start_round(self) -> int:
        self.round_no += 1
        self.round_used = 0
        return self.round_no

    def precheck(self, planned: int) -> None:
        if self.round_used + planned > self.budget.round_llm_tokens:
            raise BudgetExceeded("轮次级", self.round_used + planned, self.budget.round_llm_tokens)
        if self.session_used + planned > self.budget.session_llm_tokens:
            raise BudgetExceeded("会话级", self.session_used + planned,
                                 self.budget.session_llm_tokens)
        if self.tenant_limit and self.tenant_used + planned > self.tenant_limit:
            raise BudgetExceeded("租户级", self.tenant_used + planned, self.tenant_limit)

    def charge(self, logical_model: str, prompt_tokens: int, completion_tokens: int) -> None:
        total = int(prompt_tokens) + int(completion_tokens)
        self.round_used += total
        self.session_used += total
        self.tenant_used += total
        self.calls += 1
        self.by_logical_model[logical_model] = self.by_logical_model.get(logical_model, 0) + total

    def snapshot(self) -> dict:
        return {"round_no": self.round_no, "calls": self.calls,
                "round_used": self.round_used, "round_limit": self.budget.round_llm_tokens,
                "session_used": self.session_used, "session_limit": self.budget.session_llm_tokens,
                "round_remaining": max(0, self.budget.round_llm_tokens - self.round_used),
                "session_remaining": max(0, self.budget.session_llm_tokens - self.session_used),
                "by_logical_model": dict(sorted(self.by_logical_model.items()))}
