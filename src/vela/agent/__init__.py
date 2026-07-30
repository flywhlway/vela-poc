"""推理平面：双层编排 + 七节点诊断图。

节点：plan → retrieve → compress → verify → report ；另有 human_gate / unanswerable 两个终止节点。
核心不变量：
  * 模型永远看不到原始日志全量，只看到经预算感知压缩后的证据集（含压缩痕迹）
  * 任何结论必须携带 row_hash 引用，且由程序独立校验（不信任模型自述）
  * 连续两轮无新证据 → 转人工介入，而不是继续烧预算
"""
from vela.agent.graph import AgentGraph, DiagnosisResult, diagnose
from vela.agent.state import SessionState

__all__ = ["AgentGraph", "SessionState", "DiagnosisResult", "diagnose"]
