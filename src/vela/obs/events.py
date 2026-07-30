"""结构化事件总线（交底书机制六：分级事件 + 双通道推送）。

双通道：
  * 进度通道（PROGRESS）—— 高频、可丢弃，用于前端实时进度条；订阅者可选择性消费
  * 关键通道（MILESTONE/ALERT）—— 低频、不可丢，必须落盘 JSONL 并 fsync
事件带单调递增 event_id，断线重连后可用 last_event_id 续传，不会重复或漏送。
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from vela.util.jsonl import append_jsonl
from vela.util.timeutil import iso

UTC = timezone.utc


class Severity(str, Enum):
    PROGRESS = "PROGRESS"     # 进度通道：可丢弃
    MILESTONE = "MILESTONE"   # 关键通道：必达
    ALERT = "ALERT"           # 关键通道：必达 + 告警


@dataclass
class Event:
    event_id: int
    ts_utc: str
    session_id: str
    severity: str
    kind: str
    round_no: int = 0
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class EventBus:
    def __init__(self, path: str | Path | None = None, session_id: str = "-"):
        self.path = Path(path) if path else None
        self.session_id = session_id
        self._seq = 0
        self._lock = threading.Lock()
        self._subs: list[Callable[[Event], None]] = []
        self.buffer: list[Event] = []

    def subscribe(self, fn: Callable[[Event], None]) -> None:
        self._subs.append(fn)

    def emit(self, kind: str, severity: Severity = Severity.PROGRESS,
             round_no: int = 0, **payload) -> Event:
        with self._lock:
            self._seq += 1
            ev = Event(event_id=self._seq, ts_utc=iso(datetime.now(UTC)),
                       session_id=self.session_id, severity=severity.value,
                       kind=kind, round_no=round_no, payload=payload)
        self.buffer.append(ev)
        # 关键通道必达：同步落盘 + fsync
        if self.path and severity in (Severity.MILESTONE, Severity.ALERT):
            append_jsonl(self.path, ev.to_dict())
        elif self.path:
            append_jsonl(self.path, ev.to_dict(), fsync=False)
        for fn in self._subs:
            try:
                fn(ev)
            except Exception:                      # 订阅者异常不得影响主链路
                pass
        return ev

    def since(self, last_event_id: int = 0) -> list[Event]:
        return [e for e in self.buffer if e.event_id > last_event_id]

    def critical(self) -> list[Event]:
        return [e for e in self.buffer if e.severity in ("MILESTONE", "ALERT")]


_default: EventBus | None = None


def event_bus(path: str | Path | None = None, session_id: str = "-") -> EventBus:
    global _default
    if path is not None or _default is None:
        _default = EventBus(path, session_id)
    return _default
