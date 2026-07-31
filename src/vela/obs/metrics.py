"""轻量指标：计数器 / 计时器 / 直方图，无外部依赖，可导出 JSON 或 Prometheus 文本。"""
from __future__ import annotations

import time
from collections import defaultdict
from contextlib import contextmanager


class Metrics:
    def __init__(self) -> None:
        self.counters: dict[str, float] = defaultdict(float)
        self.timers: dict[str, list[float]] = defaultdict(list)
        self.gauges: dict[str, float] = {}

    def inc(self, name: str, value: float = 1.0) -> None:
        self.counters[name] += value

    def gauge(self, name: str, value: float | None) -> None:
        if value is None:
            return
        self.gauges[name] = value

    def observe(self, name: str, ms: float) -> None:
        self.timers[name].append(ms)

    @contextmanager
    def timer(self, name: str):
        t0 = time.time()
        try:
            yield
        finally:
            self.observe(name, (time.time() - t0) * 1000)

    @staticmethod
    def _pct(vals: list[float], p: float) -> float:
        if not vals:
            return 0.0
        s = sorted(vals)
        k = max(0, min(len(s) - 1, int(round((len(s) - 1) * p))))
        return round(s[k], 2)

    def snapshot(self) -> dict:
        return {
            "counters": {k: round(v, 4) for k, v in sorted(self.counters.items())},
            "gauges": {k: round(v, 4) for k, v in sorted(self.gauges.items())},
            "timers_ms": {k: {"count": len(v), "p50": self._pct(v, 0.5),
                              "p95": self._pct(v, 0.95), "max": round(max(v), 2)}
                          for k, v in sorted(self.timers.items()) if v},
        }

    def prometheus(self) -> str:
        lines = []
        for k, v in sorted(self.counters.items()):
            lines.append(f"vela_{k.replace('.', '_')}_total {v}")
        for k, v in sorted(self.gauges.items()):
            lines.append(f"vela_{k.replace('.', '_')} {v}")
        for k, v in sorted(self.timers.items()):
            if v:
                lines.append(f"vela_{k.replace('.', '_')}_p95_ms {self._pct(v, 0.95)}")
        return "\n".join(lines) + "\n"
