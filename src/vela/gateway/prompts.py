"""提示词模板：mock 与真实模型共用同一份提示词。

约定：提示词中嵌入一段机器可读状态块
    [[VELA_STATE]] {json} [[/VELA_STATE]]
真实模型把它当作结构化上下文阅读；确定性 mock 直接解析它做规则推理。
这样 mock 与生产走完全相同的提示词路径，切换供应商时提示词不变。
"""
from __future__ import annotations

import json
import re

BEGIN, END = "[[VELA_STATE]]", "[[/VELA_STATE]]"


def embed_state(state: dict) -> str:
    return f"{BEGIN}\n{json.dumps(state, ensure_ascii=False, sort_keys=True, default=str)}\n{END}"


def extract_state(text: str) -> dict:
    m = re.search(re.escape(BEGIN) + r"\s*(.*?)\s*" + re.escape(END), text or "", re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


PLANNER_SYSTEM = """你是车联网 OTA 日志诊断编排器。你不能直接看到日志原文，只能通过工具查询列式取证库。
工作纪律：
1. 先鸟瞰后下钻：未建立全局认知前禁止拉取大量明细。
2. 每一轮只选择一个最相关的诊断技能，并执行该技能的探针工具。
3. 已经使用过且未产出有效新证据的技能不得重复选择。
4. 任何结论必须能落到具体日志行（row_hash），不能凭经验推测。
5. stop=true 仅表示「停止调查」（已充分探索后收敛），不等于「无法定论」。
   首轮或尚无证据时禁止 stop，必须继续调查：选择技能并给出非空 actions。
   无法定论时仍应继续取证或说明缺口，不得用 stop 偷换；不允许编造证据。
只输出 JSON，格式：
{"thought": "简要推理", "selected_skill": "技能ID或null", "actions": [{"tool": "工具名", "args": {...}}],
 "stop": false, "reason": ""}"""

VERIFIER_SYSTEM = """你是证据校验器。给定若干条待证结论及其引用的日志行指纹（row_hash），
判断每条结论是否被引用证据充分支撑。禁止引用未在证据集中出现的 row_hash。
只输出 JSON：{"verdicts":[{"claim_id":"C1","status":"supported|weak|unsupported","citations":["row_hash"],"note":""}]}"""

REPORTER_SYSTEM = """你是车联网 OTA 故障诊断报告撰写者。基于给定证据链撰写中文诊断报告。
要求：每个事实性判断后必须紧跟证据引用 [[EV:row_hash]]；时间置信度低于 0.6 的证据须显式声明时间不确定性；
不得引入证据之外的信息；若证据不足，明确写出"证据不足以支撑该结论"。"""

DISTILLER_SYSTEM = """你是知识蒸馏器。将本次诊断会话沉淀为可复用的诊断技能候选。
只输出 JSON：{"skill":{"id":"SK-XXX","title":"","trigger":"","summary":"","keywords":[],"tools":[],"root_cause_label":""},
"confidence":0.0,"rationale":""}"""


def planner_user(state: dict) -> str:
    return ("请基于以下状态选择下一步诊断动作。\n" + embed_state(state) +
            "\n只输出 JSON，不要任何解释文字或 Markdown 代码围栏。")


def verifier_user(state: dict) -> str:
    return ("请校验以下结论与引用。\n" + embed_state(state) + "\n只输出 JSON。")


def reporter_user(state: dict) -> str:
    return ("请基于以下证据链撰写中文诊断报告。\n" + embed_state(state))


def distiller_user(state: dict) -> str:
    return ("请将本次会话蒸馏为技能候选。\n" + embed_state(state) + "\n只输出 JSON。")
