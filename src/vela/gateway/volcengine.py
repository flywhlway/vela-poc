"""火山引擎方舟（Volcengine Ark）接入说明与适配器别名。

Ark 提供 OpenAI 兼容端点，因此直接复用 OpenAICompatProvider，
差异仅在配置（config/llm.yaml 的 providers.volcengine 段）：

  base_url : https://ark.cn-beijing.volces.com/api/v3     （VELA_ARK_BASE_URL 可覆盖）
  鉴权     : Authorization: Bearer $VELA_ARK_API_KEY
  model    : 推理接入点 ID（ep-xxxxxxxxxxxx）或模型名  ← VELA_ARK_MODEL
  可选     : VELA_ARK_MODEL_PLANNER / _VERIFIER / _REPORTER / _DISTILLER 按逻辑模型分别指定
  向量     : VELA_ARK_EMBED_MODEL（/embeddings）

生产切换步骤（不改任何业务代码）：
  1. 在项目根 `.env` 写入 VELA_LLM_PROVIDER=volcengine
  2. 同文件写入 VELA_ARK_API_KEY=... 与 VELA_ARK_MODEL=ep-xxxxxxxx
  3. 可选写入 VELA_ARK_MODEL_FALLBACK=ep-yyyyyyyy   （主接入点故障时自动降级）
  4. `src/vela/config.py` 导入时自动加载（override=False）；vela agent diagnose ... ——
     网关自动完成脱敏、计量、审计、降级
"""
from __future__ import annotations

from vela.gateway.openai_compat import OpenAICompatProvider


class VolcengineArkProvider(OpenAICompatProvider):
    """语义别名：便于日志与审计中区分供应商。"""

    def __init__(self, cfg: dict, name: str = "volcengine"):
        super().__init__(cfg, name=name)


__all__ = ["VolcengineArkProvider"]
