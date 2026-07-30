"""查询平面：Agent 工具集 + SQL 沙箱 + 运行时护栏。

设计原则（技术方案 §10.1 + 交底书机制四）：
  1. 两阶段检索：先摘要后全文，避免一次塞爆上下文；
  2. Token 预算硬约束：每工具有 max_chars 上限，超限截断并给游标；
  3. 代价可见：返回 rows_scanned / elapsed_ms / total_matches；
  4. 语义化而非 SQL 化；
  5. 裸 SQL 只作逃生舱，且置于只读沙箱。
"""
from vela.query.api import LogQueryAPI, ToolResult
from vela.query.guard import Guardrail, SqlGuard, SqlGuardError
from vela.query.tools import TOOL_SPECS, tool_names

__all__ = ["LogQueryAPI", "ToolResult", "Guardrail", "SqlGuard", "SqlGuardError",
           "TOOL_SPECS", "tool_names"]
