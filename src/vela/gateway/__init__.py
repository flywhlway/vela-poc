"""统一模型网关：全部大模型流量的唯一出口。

职责（交底书机制六 + 技术方案 §11）：
  1. 逻辑模型名（planner/verifier/reporter/distiller）→ 物理模型/接入点映射
  2. 出站脱敏（VIN/位置/手机号/IMEI/身份证/邮箱/IP）
  3. 三级 token 预算计量与硬切断（租户 / 会话 / 轮次）
  4. 全量调用审计（JSONL，含 prompt 哈希而非明文）
  5. 故障降级链：主模型不可用 → 备用接入点 → 备用供应商
业务代码只依赖 LLMGateway.chat()，切换供应商零改动。
"""
from vela.gateway.base import LLMGateway, LLMError, LLMRequest, LLMResponse, build_gateway
from vela.gateway.budget import BudgetExceeded, TokenLedger

__all__ = ["LLMGateway", "LLMRequest", "LLMResponse", "LLMError",
           "build_gateway", "TokenLedger", "BudgetExceeded"]
