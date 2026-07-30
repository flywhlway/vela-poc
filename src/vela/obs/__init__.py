"""可观测平面：结构化事件总线 + 指标 + 分级双通道推送。"""
from vela.obs.events import EventBus, Severity, event_bus
from vela.obs.metrics import Metrics

__all__ = ["EventBus", "Severity", "event_bus", "Metrics"]
