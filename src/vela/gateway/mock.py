"""确定性 Mock 供应商：同输入必同输出，供 CI / 评测 / 离线演示使用。

它不是"假装回答"，而是一个规则化的推理器：解析提示词中的 [[VELA_STATE]] 结构化状态，
按与真实模型相同的契约输出 JSON。因此整条 Agent 链路（含预算、压缩、引用校验、报告）
在无任何外部依赖时即可完整运行与回归。

inject_hallucinated_citations=true 时会故意伪造一个不存在的 row_hash，
用于验证"系统级引用校验"确实能抓到模型幻觉——这是安全网的自测开关。
"""
from __future__ import annotations

import hashlib
import json
import time

from vela.gateway.base import LLMRequest, LLMResponse, Provider
from vela.gateway.prompts import extract_state


def _fake_hash(seed: str) -> str:
    return hashlib.blake2b(seed.encode("utf-8"), digest_size=8).hexdigest()


def _weighted_signal(state: dict) -> list[tuple[str, float]]:
    """构造加权信号面。

    权重体现诊断先验：中止标记 / 中止原因是最强信号；稀有错误模板次之；
    高频模板（如每次升级都会出现的 responsePending）几乎不携带根因信息。
    每段文本同时保留下划线原文与空格化版本，使 "ECU_NO_RESPONSE" 能命中关键词 "no response"。
    """
    import re as _re

    def _seg(text: str, w: float) -> tuple[str, float]:
        low = str(text).lower()
        return (low + " " + low.replace("_", " ").replace("-", " "), w)

    sg = state.get("signals", {}) or {}
    segs: list[tuple[str, float]] = []
    for key, w in (("abort_reason", 6.0), ("abort_marker", 5.0)):
        if sg.get(key):
            segs.append(_seg(sg[key], w))
    if sg.get("fail_phase"):
        segs.append(_seg(sg["fail_phase"], 2.0))
    for c in sg.get("silent_components", []) or []:
        segs.append(_seg(f"{c} no response gap silent", 2.0))
    for d in state.get("evidence_digest", []) or []:
        m = _re.match(r"\[(\d+)x\]", str(d))
        occ = int(m.group(1)) if m else 1
        segs.append(_seg(d, 3.0 if occ <= 5 else 0.5))
    return segs


class MockProvider(Provider):
    def __init__(self, cfg: dict, name: str = "mock"):
        self.name = name
        self.cfg = cfg or {}
        self.deterministic = bool(self.cfg.get("deterministic", True))
        self.latency_ms = float(self.cfg.get("latency_ms", 0))
        self.inject = bool(self.cfg.get("inject_hallucinated_citations", False))

    def models_for(self, logical_model: str) -> list[str]:
        return [f"mock-{logical_model}"]

    # ------------------------------------------------------------------ #
    def complete(self, req: LLMRequest, physical_model: str, params: dict) -> LLMResponse:
        t0 = time.time()
        if self.latency_ms:
            time.sleep(self.latency_ms / 1000.0)
        state = extract_state(req.flat_text())
        fn = {"planner": self._plan, "verifier": self._verify,
              "reporter": self._report, "distiller": self._distill}.get(req.logical_model)
        text = fn(state) if fn else json.dumps({"echo": True}, ensure_ascii=False)
        return LLMResponse(text=text, logical_model=req.logical_model,
                           physical_model=physical_model, provider=self.name,
                           latency_ms=(time.time() - t0) * 1000, raw={"mock": True})

    # ---------------- planner：技能遴选 + 探针规划 ---------------- #
    def _plan(self, state: dict) -> str:
        cands = state.get("candidate_skills") or []
        used = set(state.get("excluded_skills") or [])
        segments = _weighted_signal(state)

        scored = []
        for sk in cands:
            if sk["id"] in used:
                continue
            kws = [str(k).lower() for k in sk.get("keywords", [])]
            score = 0.0
            hits: list[str] = []
            for k in kws:
                if not k:
                    continue
                w = max((wt for text, wt in segments if k in text), default=0.0)
                if w:
                    score += w
                    hits.append(k)
            # 技能触发条件覆盖当前失败阶段时加权
            phase = str(state.get("signals", {}).get("fail_phase", "")).lower()
            if phase and phase in str(sk.get("trigger", "")).lower():
                score += 2.0
            scored.append((-score, sk["id"], sk, hits))
        scored.sort()

        if not scored or scored[0][0] == 0:
            return json.dumps({
                "thought": "候选技能与当前证据信号无关键词交集，继续下钻只会消耗预算而不产生新证据。",
                "selected_skill": None, "actions": [], "stop": True,
                "reason": "无可用假设：已有证据不足以支撑进一步定向下钻。",
            }, ensure_ascii=False)

        _, sid, sk, hits = scored[0]
        actions = [{"tool": p["tool"], "args": dict(p.get("args", {}))}
                   for p in sk.get("probes", [])]
        return json.dumps({
            "thought": f"证据信号命中技能《{sk['title']}》的关键词 {hits[:6]}，"
                       f"按其探针进行定向下钻以获取可引用的原始日志行。",
            "selected_skill": sid, "actions": actions, "stop": False, "reason": "",
        }, ensure_ascii=False)

    # ---------------- verifier：结论-证据一致性 ---------------- #
    def _verify(self, state: dict) -> str:
        known = set(state.get("known_row_hashes") or [])
        verdicts = []
        for c in state.get("claims") or []:
            cites = list(c.get("citations") or [])
            if self.inject and cites:
                cites = cites + [_fake_hash(str(c.get("claim_id")) + "hallucination")]
            ok = [h for h in cites if h in known]
            bad = [h for h in cites if h not in known]
            status = "supported" if ok and not bad else ("weak" if ok else "unsupported")
            verdicts.append({"claim_id": c.get("claim_id"), "status": status,
                             "citations": cites,
                             "note": ("全部引用可在证据集中解析" if not bad
                                      else f"存在无法解析的引用 {bad[:3]}")})
        return json.dumps({"verdicts": verdicts}, ensure_ascii=False)

    # ---------------- reporter：中文诊断报告 ---------------- #
    def _report(self, state: dict) -> str:
        rc = state.get("root_cause") or {}
        chain = state.get("chain") or []
        cites = [c.get("row_hash") for c in chain if c.get("row_hash")]
        if self.inject and cites:
            cites = cites + [_fake_hash("report-hallucination")]
        low_conf = [c for c in chain if float(c.get("ts_confidence") or 1.0) < 0.6]

        L = []
        L.append(f"## 诊断结论\n\n判定根因：**{rc.get('label','未定论')}** —— {rc.get('title','')}。")
        if rc.get("fail_phase") and rc.get("label") not in ("no_fault_found", "undetermined", None):
            L.append(f"升级流程在 **{rc['fail_phase']}** 阶段中断"
                     + (f"，责任模块为 `{rc.get('culprit')}`" if rc.get("culprit") else "") + "。")
        elif rc.get("label") == "no_fault_found" and rc.get("fail_phase"):
            L.append(f"升级流程已进行至 **{rc['fail_phase']}** 阶段，期间未见错误级事件。")
        L.append("\n## 证据链\n")
        for i, c in enumerate(chain[:12], 1):
            tag = {"TRIGGER": "触发", "CAUSE": "成因", "EFFECT": "后果",
                   "CONTEXT": "背景", "COUNTER": "反证"}.get(c.get("role", "CONTEXT"), "背景")
            L.append(f"{i}. [{tag}] {c.get('ts_utc','')} `{c.get('component','')}` "
                     f"{str(c.get('raw_line',''))[:160]} [[EV:{c.get('row_hash')}]]")
        if low_conf:
            L.append(f"\n> ⚠ 时间不确定性声明：{len(low_conf)} 条证据的时间置信度低于 0.6"
                     f"（{[c.get('ts_kind') for c in low_conf][:4]}），"
                     f"其相对先后顺序仅可用于分钟级关联，不足以支撑毫秒级因果判定。")
        unresolved = state.get("unresolved") or []
        if unresolved:
            L.append("\n## 证据不足以支撑的部分\n")
            for u in unresolved:
                L.append(f"- {u}")
        L.append("\n## 处置建议\n")
        for a in (rc.get("actions") or ["复现该场景并采集完整车端日志后重新诊断。"]):
            L.append(f"- {a}")
        L.append(f"\n<!-- citations: {json.dumps(cites, ensure_ascii=False)} -->")
        return "\n".join(L)

    # ---------------- distiller：知识自增强 ---------------- #
    def _distill(self, state: dict) -> str:
        rc = state.get("root_cause") or {}
        label = rc.get("label") or "unknown"
        kws = sorted({str(k).lower() for k in (state.get("signal_terms") or []) if k})[:12]
        return json.dumps({
            "skill": {
                "id": "SK-AUTO-" + _fake_hash(label)[:6].upper(),
                "title": f"自动蒸馏：{rc.get('title') or label}",
                "trigger": rc.get("trigger_hint") or f"出现 {label} 相关征兆时",
                "summary": f"由会话 {state.get('session_id','-')} 蒸馏；"
                           f"命中阶段 {rc.get('fail_phase','-')}，责任模块 {rc.get('culprit','-')}。",
                "keywords": kws,
                "tools": sorted(set(state.get("tools_used") or [])),
                "root_cause_label": label,
            },
            "confidence": round(min(0.95, 0.4 + 0.1 * len(kws)), 2),
            "rationale": "本次会话已产出可核验证据链，且技能命中路径可复用。",
        }, ensure_ascii=False)
