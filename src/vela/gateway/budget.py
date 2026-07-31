"""三级 token 预算计量与硬切断（交底书机制一：双水位预算）。

计量键：(tenant_id, session_id, round_no)
  * 轮次级：round_llm_tokens —— 单轮超限即切断，防止一次失控推理烧穿配额
  * 会话级：session_llm_tokens —— 全会话累计上限
  * 租户级：可选，缺省不限（生产接入计费系统时填）
超限抛 BudgetExceeded；调用方（Agent）据此收敛为"证据不足以支撑结论"而非静默截断。

PERF-02：另做成本归集（estimated_cost_usd）与超 diagnose_cost_alert 的 EventBus ALERT；
告警不替代 BudgetExceeded 硬切断。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from vela.config import BudgetProfile, load_budget, load_yaml


class BudgetExceeded(RuntimeError):
    def __init__(self, scope: str, used: int, limit: int):
        self.scope, self.used, self.limit = scope, used, limit
        super().__init__(f"{scope} token 预算超限：已用 {used} / 上限 {limit}")


def load_cost_rates() -> dict[str, float]:
    """从 budget.yaml 顶层 cost: 段读取单价与告警阈值（配置驱动，禁止硬编码）。"""
    raw = (load_yaml("budget.yaml") or {}).get("cost") or {}
    return {
        "input_per_1k": float(raw.get("input_per_1k", 0.0)),
        "output_per_1k": float(raw.get("output_per_1k", 0.0)),
        "diagnose_cost_alert": float(raw.get("diagnose_cost_alert", 1.0)),
    }


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
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_hits: int = 0
    cost_rates: dict[str, float] = field(default_factory=load_cost_rates)
    on_alert: Callable[[str, dict[str, Any]], None] | None = None
    _cost_alerted: bool = False

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

    @property
    def estimated_cost_usd(self) -> float:
        rates = self.cost_rates or {}
        inp = rates.get("input_per_1k", 0.0) * (self.prompt_tokens / 1000.0)
        out = rates.get("output_per_1k", 0.0) * (self.completion_tokens / 1000.0)
        return round(inp + out, 6)

    def charge(self, logical_model: str, prompt_tokens: int, completion_tokens: int,
               *, cache_hit: bool = False) -> None:
        pt, ct = int(prompt_tokens), int(completion_tokens)
        total = pt + ct
        self.round_used += total
        self.session_used += total
        self.tenant_used += total
        self.calls += 1
        self.prompt_tokens += pt
        self.completion_tokens += ct
        if cache_hit:
            self.cache_hits += 1
        self.by_logical_model[logical_model] = self.by_logical_model.get(logical_model, 0) + total
        self._maybe_cost_alert()

    def _maybe_cost_alert(self) -> None:
        alert_at = float((self.cost_rates or {}).get("diagnose_cost_alert", 1.0))
        cost = self.estimated_cost_usd
        if alert_at > 0 and cost > alert_at and not self._cost_alerted:
            self._cost_alerted = True
            payload = {"estimated_cost_usd": cost, "diagnose_cost_alert": alert_at,
                       "prompt_tokens": self.prompt_tokens,
                       "completion_tokens": self.completion_tokens}
            if self.on_alert:
                self.on_alert("cost.alert", payload)
            else:
                try:
                    from vela.obs.events import EventBus, Severity
                    EventBus(session_id="-").emit("cost.alert", Severity.ALERT, **payload)
                except Exception:
                    pass

    def snapshot(self) -> dict:
        return {"round_no": self.round_no, "calls": self.calls,
                "round_used": self.round_used, "round_limit": self.budget.round_llm_tokens,
                "session_used": self.session_used, "session_limit": self.budget.session_llm_tokens,
                "round_remaining": max(0, self.budget.round_llm_tokens - self.round_used),
                "session_remaining": max(0, self.budget.session_llm_tokens - self.session_used),
                "by_logical_model": dict(sorted(self.by_logical_model.items())),
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "estimated_cost_usd": self.estimated_cost_usd,
                "cache_hits": self.cache_hits}
