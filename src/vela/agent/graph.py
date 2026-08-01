"""双层编排：七节点诊断图（交底书机制六 + 机制一/二/三/四/五/七 的汇合点）。

    plan ──► retrieve ──► compress ──► verify ──┬─► report ──► (distill) ──► END
      ▲                                          │
      └──────────────── 下一轮 ◄─────────────────┘
                        │
        连续两轮无新证据 ─┴─► human_gate（转人工）
        无可用假设/预算耗尽 ──► unanswerable（诚实作答"证据不足"）

不变量：
  * 模型只通过工具看数据，且看到的永远是压缩后的证据集 + 压缩痕迹
  * 每轮结束都写检查点，可续跑
  * 结论必须过程序化引用校验，悬空引用会被显式标注而非静默丢弃
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from vela.agent.checkpoint import CheckpointStore
from vela.agent.citations import strip_dangling, verify_citations
from vela.agent.compress import EvidenceCompressor
from vela.agent.skills import FALLBACK_SKILL_ID, SkillRegistry
from vela.agent.state import RoundRecord, SessionState
from vela.config import load_budget, load_yaml
from vela.gateway import LLMRequest, build_gateway
from vela.gateway.budget import BudgetExceeded, TokenLedger
from vela.gateway.prompts import (DISTILLER_SYSTEM, PLANNER_SYSTEM, REPORTER_SYSTEM,
                                  VERIFIER_SYSTEM, distiller_user, planner_user,
                                  reporter_user, verifier_user)
from vela.obs.events import EventBus, Severity
from vela.obs.metrics import Metrics
from vela.query.api import LogQueryAPI
from vela.util.ids import new_session_id
from vela.util.jsonl import canonical_json
from vela.util.timeutil import iso

UTC = timezone.utc
_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)
# ORCH-05：verifier status 归一化后可推进的集合（supported 单独计；其余为 partial）
_OK = {"supported", "partial", "partially_supported", "supported_with_caveats"}
BIRDSEYE_PROBES = [
    {"tool": "describe_dataset", "args": {}},
    {"tool": "phase_timeline", "args": {}},
    {"tool": "top_templates", "args": {"sort": "error_only", "limit": 25}},
    {"tool": "find_gaps", "args": {"min_gap_seconds": 20, "limit": 10}},
]


def _norm_status(s: str | None) -> str:
    """归一化 verifier status：大小写/连字符/空格变体 → snake_case 枚举键。"""
    return str(s or "").strip().lower().replace("-", "_").replace(" ", "_")



def _args_hash(args: dict) -> str:
    """探针 args 指纹：blake2b(canonical_json(args), digest_size=8).hexdigest()。"""
    return hashlib.blake2b(
        canonical_json(args or {}).encode("utf-8"), digest_size=8
    ).hexdigest()


def _probe_key(skill_id: str, args: dict) -> str:
    return f"{skill_id}:{_args_hash(args)}"


def _has_error_signal(st: SessionState) -> bool:
    """A1：会话/鸟瞰是否存在 ERROR 级信号（健康特异性保护）。"""
    for r in st.evidence_pool:
        if str(r.get("level_norm") or "").upper() in ("ERROR", "FATAL"):
            return True
    levels = st.signals.get("levels") or {}
    if isinstance(levels, dict):
        for k, v in levels.items():
            if str(k).upper() in ("ERROR", "FATAL") and v:
                return True
    if st.signals.get("abort_reason") or st.signals.get("abort_marker"):
        return True
    return False



def _parse_json(text: str) -> dict:
    """解析模型 JSON 输出：仅整段或围栏内合法 dict；禁止跨段花括号抢救。"""
    t = (text or "").strip()
    m = _JSON_FENCE.search(t)
    if m:
        t = m.group(1).strip()
    try:
        val = json.loads(t)
        return val if isinstance(val, dict) else {}
    except json.JSONDecodeError:
        return {}


@dataclass
class DiagnosisResult:
    state: SessionState
    metrics: dict = field(default_factory=dict)
    gateway_stats: dict = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)

    @property
    def status(self) -> str:
        return self.state.status

    @property
    def root_cause_label(self) -> str | None:
        return (self.state.root_cause or {}).get("label")

    def to_dict(self) -> dict:
        return {"state": self.state.to_dict(), "metrics": self.metrics,
                "gateway": self.gateway_stats, "events": self.events}


class AgentGraph:
    def __init__(self, db_path: str | Path, *, workspace: str | Path | None = None,
                 provider: str | None = None, profile: str | None = None,
                 session_id: str | None = None, skills: SkillRegistry | None = None,
                 question: str | None = None,
                 enable_cache: bool | None = None):
        self.db_path = str(db_path)
        self.ws = Path(workspace) if workspace else Path(db_path).parent.parent
        self.budget = load_budget(profile)
        self.session_id = session_id or new_session_id()
        self.api = LogQueryAPI(self.db_path, budget=self.budget)
        self.skills = skills or SkillRegistry()
        self.metrics = Metrics()
        self.bus = EventBus(self.ws / "obs" / "events.jsonl", session_id=self.session_id)
        self.ledger = TokenLedger(budget=self.budget)
        self.gw = build_gateway(provider, session_id=self.session_id,
                                audit_path=self.ws / "obs" / "llm_audit.jsonl",
                                ledger=self.ledger,
                                enable_cache=enable_cache)
        self.ckpt = CheckpointStore(self.ws / "sessions")
        self.state = SessionState(session_id=self.session_id, db_path=self.db_path,
                                  question=question or SessionState.question)
        self.tpl_occ = self._template_occurrences()
        self.compressor = EvidenceCompressor(self.budget, self.tpl_occ)

    # ------------------------------------------------------------------ #
    def close(self) -> None:
        self.api.close()

    def _template_occurrences(self) -> dict:
        try:
            return {r["template_id"]: r["occurrences"]
                    for r in self.api._q("SELECT template_id, occurrences FROM templates")}
        except Exception:
            return {}

    def _llm(self, logical: str, system: str, user: str) -> str:
        with self.metrics.timer(f"llm.{logical}"):
            resp = self.gw.chat(LLMRequest(logical_model=logical, system=system, user=user))
        self.metrics.inc(f"llm.{logical}.calls")
        if resp.finish_reason == "length":
            self.bus.emit("llm.truncation", Severity.ALERT, self.state.round_no,
                          logical_model=logical, finish_reason=resp.finish_reason)
            self.metrics.inc("llm.truncation")
        return resp.text

    def _llm_json(self, logical: str, system: str, user: str, retries: int = 2) -> dict:
        """调用逻辑模型并解析为 dict；失败最多重试 retries 次，耗尽发 parse_failure。"""
        attempts = 1 + max(0, int(retries))
        last: dict = {}
        for _ in range(attempts):
            text = self._llm(logical, system, user)
            parsed = _parse_json(text)
            if parsed:
                return parsed
            last = parsed
        self.bus.emit("llm.parse_failure", Severity.ALERT, self.state.round_no,
                      logical_model=logical, attempts=attempts)
        self.metrics.inc("llm.parse_failure")
        return last

    # ============================ 节点 ============================ #
    def node_plan(self, st: SessionState) -> dict:
        self.bus.emit("plan.start", Severity.PROGRESS, st.round_no)
        rows: list[dict] = []
        calls: list[dict] = []
        if st.round_no == 1:
            for p in BIRDSEYE_PROBES:
                res = self.api.call(p["tool"], **p["args"])
                calls.append({"tool": p["tool"], "args": p["args"], "ok": res.ok,
                              "rows": len(res.rows), "notes": res.notes})
                self._absorb_signals(st, p["tool"], res)
            self.bus.emit("birdseye.done", Severity.MILESTONE, st.round_no,
                          signals=st.signals)

        query = _retrieval_query(st)
        excluded = st.excluded_skills()
        cands = self.skills.retrieve(query, top_n=8, exclude=excluded)
        self.metrics.gauge("skills.candidates", len(cands))
        payload = {"round": st.round_no, "question": st.question, "signals": st.signals,
                   "evidence_digest": st.evidence_digest[:40],
                   "candidate_skills": cands, "excluded_skills": excluded,
                   "used_skills": st.used_skills,
                   "budget": self.ledger.snapshot()}
        out = self._llm_json("planner", PLANNER_SYSTEM, planner_user(payload))
        sid = out.get("selected_skill")
        # 程序化兜底：模型若选中已被剔除的技能，直接判非法并转不可答
        if sid and sid in set(excluded):
            self.bus.emit("plan.illegal_skill", Severity.ALERT, st.round_no, skill=sid)
            self.metrics.inc("plan.illegal_skill")
            out["stop"] = True
            out["reason"] = f"模型选择了已被程序剔除的技能 {sid}（历史规避约束）"
            sid = None
        actions = out.get("actions") or (self.skills.probes_of(sid) if sid else [])
        # ORCH-10 A1：候选词面全零分 AND 存在 ERROR 信号 → 注入 GENERIC（健康包不注入）
        all_zero = not self.skills.has_positive_lexical_score(query, exclude=excluded)
        if all_zero and _has_error_signal(st):
            sid = FALLBACK_SKILL_ID
            actions = list(self.skills.probes_of(sid))
            out["stop"] = False
            out["reason"] = out.get("reason") or "候选全零分且存在 ERROR 信号，注入通用取证技能"
        # ORCH-01：首轮禁止 stop；驳回后必要时补 actions（最高分非 fallback → GENERIC）
        if out.get("stop") and st.round_no == 1:
            self.bus.emit("plan.stop_rejected", Severity.ALERT, st.round_no,
                          reason="首轮不允许 stop", model_reason=out.get("reason"))
            self.metrics.inc("plan.stop_rejected")
            out["stop"] = False
            if not actions:
                pick = sid if sid and sid in self.skills.by_id else None
                if not pick and cands:
                    pick = cands[0]["id"]  # retrieve 已按相关度降序，且排除 fallback_only
                if not pick:
                    pick = FALLBACK_SKILL_ID
                sid = pick
                actions = list(self.skills.probes_of(sid))
                if not actions:
                    sid = FALLBACK_SKILL_ID
                    actions = list(self.skills.probes_of(FALLBACK_SKILL_ID))
        # ORCH-07：同 (skill_id, args_hash) 探针去重，避免确定性重跑烧预算
        if sid and actions:
            seen = set(st.executed_probes)
            actions = [a for a in actions
                       if _probe_key(sid, a.get("args") or {}) not in seen]
        if sid:
            st.used_skills = sorted(set(st.used_skills + [sid]))
        self.bus.emit("plan.done", Severity.MILESTONE, st.round_no, skill=sid,
                      actions=[a.get("tool") for a in actions], stop=bool(out.get("stop")))
        return {"skill": sid, "actions": actions, "stop": bool(out.get("stop")),
                "thought": out.get("thought", ""), "reason": out.get("reason", ""),
                "calls": calls, "rows": rows}

    def node_retrieve(self, st: SessionState, actions: list[dict],
                      skill_id: str | None = None) -> dict:
        rows: list[dict] = []
        calls: list[dict] = []
        notes: list[str] = []
        for a in actions[:8]:
            tool = a.get("tool")
            args = dict(a.get("args") or {})
            with self.metrics.timer(f"tool.{tool}"):
                res = self.api.call(tool, **args)
            self.metrics.inc(f"tool.{tool}.calls")
            calls.append({"tool": tool, "args": args, "ok": res.ok,
                          "rows": len(res.rows), "total": res.total_matches,
                          "elapsed_ms": res.elapsed_ms, "error": res.error,
                          "notes": res.notes})
            notes.extend(res.notes)
            if tool not in st.tools_used:
                st.tools_used.append(tool)
            if res.ok and skill_id:
                key = _probe_key(skill_id, args)
                if key not in st.executed_probes:
                    st.executed_probes.append(key)
            if res.ok and res.rows and tool in ("search_logs", "get_lines", "get_context"):
                rows.extend(res.rows)
            elif res.ok and res.rows:
                st.evidence_digest.extend(
                    json.dumps(r, ensure_ascii=False, default=str)[:220] for r in res.rows[:10])
        self.bus.emit("retrieve.done", Severity.PROGRESS, st.round_no,
                      tools=[c["tool"] for c in calls], rows=len(rows))
        return {"rows": rows, "calls": calls, "notes": notes}

    def node_compress(self, st: SessionState, rows: list[dict]) -> dict:
        with self.metrics.timer("compress"):
            cr = self.compressor.compress(rows)
        hashes = [r["row_hash"] for r in cr.kept if r.get("row_hash")]
        new = st.mark_seen(hashes)
        self.metrics.gauge("compress.ratio", cr.ratio)
        self.metrics.inc("compress.folded", cr.trace.get("folded_total", 0))
        for r in cr.kept:
            if r.get("row_hash") and not any(
                    e.get("row_hash") == r["row_hash"] for e in st.evidence_pool):
                st.evidence_pool.append(r)
        self.bus.emit("compress.done", Severity.PROGRESS, st.round_no,
                      kept=len(cr.kept), new_evidence=len(new), ratio=cr.ratio,
                      folded=cr.trace.get("folded_total", 0))
        return {"result": cr, "new": new, "hashes": hashes}

    def _hypothesis_claim(self, skill_id: str | None) -> str:
        """构造根因假设文本（技能语义），禁止用 raw_line 自证。"""
        sk = self.skills.by_id.get(skill_id or "") or {}
        label = sk.get("root_cause_label") or (
            self.skills.label_of(skill_id) if skill_id else None)
        title = str(sk.get("title") or "").strip()
        summary = str(sk.get("summary") or "").strip()
        if title and label:
            text = f"根因假设：{title}（{label}）"
        elif title:
            text = f"根因假设：{title}"
        elif label:
            text = f"根因假设：{label}"
        else:
            text = "根因假设：证据指向的故障模式待确认"
        if summary and summary not in text:
            text = f"{text}：{summary}"
        return text[:200]

    def node_verify(self, st: SessionState, cr, skill_id: str | None) -> dict:
        errs = [r for r in cr.kept
                if str(r.get("level_norm") or "").upper() in ("ERROR", "FATAL")]
        # 没有错误级证据时不得据此下结论：否则健康会话也会被"诊断"出根因（假阳性）
        has_error_evidence = bool(errs)
        ev = errs[:8] or cr.kept[:5]
        # ORCH-06：单条（或少量）根因假设 + 多 citations；claims ≤5
        citations = [r["row_hash"] for r in ev if r.get("row_hash")]
        claims: list[dict] = []
        if citations:
            claims.append({
                "claim_id": "C1",
                "claim": self._hypothesis_claim(skill_id),
                "citations": citations,
            })
        claims = claims[:5]
        payload = {"claims": claims,
                   "known_row_hashes": [r["row_hash"] for r in cr.kept if r.get("row_hash")],
                   "compression_trace": cr.trace}
        out = self._llm_json("verifier", VERIFIER_SYSTEM, verifier_user(payload))
        verdicts = out.get("verdicts") or []
        # 程序化独立校验：不采信模型自述
        blob = " ".join(json.dumps(v, ensure_ascii=False) for v in verdicts)
        cite_rep = verify_citations(
            " ".join(f"[[EV:{h}]]" for v in verdicts for h in (v.get("citations") or [])),
            [r["row_hash"] for r in cr.kept if r.get("row_hash")], api=self.api)
        if cite_rep.dangling:
            payload = {"dangling": cite_rep.dangling[:5]}
            if cite_rep.dangling_rate is not None:
                payload["rate"] = cite_rep.dangling_rate
            self.bus.emit("verify.dangling_citation", Severity.ALERT, st.round_no, **payload)
            self.metrics.inc("verify.dangling", len(cite_rep.dangling))
        # ORCH-05：枚举归一化；decisive = supported 或 ≥2 partial（未知 status 不推进）
        supported = [v for v in verdicts if _norm_status(v.get("status")) == "supported"]
        partial = [v for v in verdicts
                   if _norm_status(v.get("status")) in _OK
                   and _norm_status(v.get("status")) != "supported"]
        decisive = ((bool(supported) or len(partial) >= 2)
                    and has_error_evidence and skill_id is not None
                    and self.skills.label_of(skill_id) is not None)
        self.bus.emit("verify.done", Severity.MILESTONE, st.round_no,
                      claims=len(claims), supported=len(supported), decisive=decisive)
        return {"verdicts": verdicts, "decisive": decisive, "citation_check": cite_rep.to_dict(),
                "evidence": ev, "blob": blob}

    def node_report(self, st: SessionState, skill_id: str | None) -> dict:
        chain = self._build_chain(st)
        rc = self._root_cause(st, skill_id, chain)
        payload = {"question": st.question, "root_cause": rc, "chain": chain,
                   "unresolved": st.unresolved, "budget": self.ledger.snapshot(),
                   "session_id": st.session_id}
        text = self._llm("reporter", REPORTER_SYSTEM, reporter_user(payload))
        rep = verify_citations(text, [c["row_hash"] for c in chain], api=self.api)
        if rep.dangling:
            text = strip_dangling(text, rep.dangling)
            payload = {"dangling": rep.dangling}
            if rep.dangling_rate is not None:
                payload["rate"] = rep.dangling_rate
            self.bus.emit("report.dangling_citation", Severity.ALERT, st.round_no, **payload)
        st.root_cause = rc
        st.report_md = text
        st.citation_check = rep.to_dict()
        self.metrics.gauge("report.dangling_rate", rep.dangling_rate)
        done_kw: dict = {"root_cause": rc.get("label"), "citations": rep.total}
        if rep.dangling_rate is not None:
            done_kw["dangling_rate"] = rep.dangling_rate
        self.bus.emit("report.done", Severity.MILESTONE, st.round_no, **done_kw)
        # 证据包（Merkle + 三级验证）
        items = [{"line_id": c["line_id"], "role": c["role"]} for c in chain if c.get("line_id")]
        if items:
            ev = self.api.call("build_evidence", claim=rc.get("title") or st.question,
                               items=items, include_context=5)
            st.evidence_pack = ev.summary
            self.bus.emit("evidence_pack.built", Severity.MILESTONE, st.round_no, **ev.summary)
        return {"root_cause": rc, "citation_check": rep.to_dict()}

    def node_distill(self, st: SessionState) -> dict:
        payload = {"session_id": st.session_id, "root_cause": st.root_cause,
                   "tools_used": st.tools_used, "used_skills": st.used_skills,
                   "signal_terms": _signal_terms(st)}
        out = self._llm_json("distiller", DISTILLER_SYSTEM, distiller_user(payload))
        if out.get("skill"):
            p = self.ws / "knowledge" / "candidates.jsonl"
            from vela.util.jsonl import append_jsonl
            append_jsonl(p, {"session_id": st.session_id, "created_at": iso(datetime.now(UTC)),
                             "status": "pending_review", **out})
            self.bus.emit("knowledge.candidate", Severity.MILESTONE, st.round_no,
                          skill_id=out["skill"].get("id"), confidence=out.get("confidence"))
        return out

    def node_human_gate(self, st: SessionState, reason: str) -> None:
        st.status = "human_gate"
        st.unresolved.append(reason)
        self.bus.emit("human_gate", Severity.ALERT, st.round_no, reason=reason,
                      seen_evidence=len(st.seen_row_hashes), rounds=st.round_no)

    def node_unanswerable(self, st: SessionState, reason: str) -> None:
        st.status = "unanswerable"
        st.unresolved.append(reason)
        st.report_md = (f"## 诊断结论\n\n**证据不足以支撑根因判定。**\n\n原因：{reason}\n\n"
                        f"已检索 {len(st.seen_row_hashes)} 条候选证据，"
                        f"经过 {st.round_no} 轮下钻仍未获得可支撑结论的关键证据。\n\n"
                        f"### 建议补充\n"
                        f"- 提供故障时段完整车端日志（当前包可能缺失关键模块日志）\n"
                        f"- 确认涉事 ECU 的诊断日志是否已开启\n"
                        f"- 若为偶发问题，请附带可复现步骤\n")
        self.bus.emit("unanswerable", Severity.ALERT, st.round_no, reason=reason)

    # ============================ 主循环 ============================ #
    def run(self, max_rounds: int | None = None) -> DiagnosisResult:
        st = self.state
        limit = int(max_rounds or self.budget.max_rounds)
        t0 = time.time()
        self.bus.emit("session.start", Severity.MILESTONE, 0, question=st.question,
                      db=self.db_path, profile=self.budget.name, provider=self.gw.provider.name)
        try:
            while st.round_no < limit and st.status == "running":
                st.round_no += 1
                self.ledger.start_round()
                rec = RoundRecord(round_no=st.round_no)
                try:
                    plan = self.node_plan(st)
                except BudgetExceeded as e:
                    self.node_unanswerable(st, f"模型预算耗尽：{e}")
                    break
                rec.selected_skill = plan["skill"]
                rec.thought = plan["thought"]
                rec.actions = plan["actions"]
                rec.tool_calls.extend(plan["calls"])
                if plan["stop"] or not plan["actions"]:
                    st.rounds.append(rec)
                    self.ckpt.save(st)
                    if st.evidence_pool:
                        self.node_report(st, _last_productive_skill(st))
                        st.status = "answered"
                    else:
                        self.node_unanswerable(
                            st, plan.get("reason") or "编排器判定无可用假设，且尚未获得任何证据。")
                    break

                got = self.node_retrieve(st, plan["actions"], plan.get("skill"))
                rec.tool_calls.extend(got["calls"])
                rec.notes = got["notes"]
                comp = self.node_compress(st, got["rows"])
                cr = comp["result"]
                rec.kept_row_hashes = comp["hashes"]
                rec.new_row_hashes = comp["new"]
                rec.compression = cr.trace
                rec.evidence_tokens = cr.tokens_after
                rec.productive = bool(comp["new"])

                if not rec.productive:
                    st.consecutive_barren_rounds += 1
                    if plan["skill"]:
                        st.unproductive_skills.append(plan["skill"])
                    self.bus.emit("round.barren", Severity.ALERT, st.round_no,
                                  skill=plan["skill"],
                                  consecutive=st.consecutive_barren_rounds)
                else:
                    st.consecutive_barren_rounds = 0

                ver = self.node_verify(st, cr, plan["skill"])
                rec.llm_tokens = self.ledger.round_used
                st.rounds.append(rec)
                self.ckpt.save(st)

                if ver["decisive"] and rec.productive:
                    self.node_report(st, plan["skill"])
                    st.status = "answered"
                    break
                if st.consecutive_barren_rounds >= 2:
                    self.node_human_gate(
                        st, f"连续 {st.consecutive_barren_rounds} 轮未获得任何新证据，"
                            f"继续下钻只会消耗预算；已用技能 {st.used_skills}。")
                    # 转人工不等于扣留已有发现：仍输出阶段性结论与证据链，供人工接手
                    if st.evidence_pool:
                        self.node_report(st, _last_productive_skill(st))
                        st.status = "human_gate"
                    break
            else:
                if st.status == "running":
                    st.status = "budget_exhausted"
                    if st.evidence_pool:
                        self.node_report(st, _last_productive_skill(st))
                        st.status = "answered"
                    else:
                        self.node_unanswerable(st, f"达到最大轮次上限 {limit}，仍未获得决定性证据。")
        except BudgetExceeded as e:
            self.node_unanswerable(st, f"预算硬切断：{e}")
        finally:
            if st.status == "answered" and st.root_cause:
                try:
                    self.node_distill(st)
                except Exception as e:                     # 蒸馏失败不影响主结论
                    self.bus.emit("knowledge.distill_failed", Severity.ALERT, st.round_no,
                                  error=str(e))
            st.ended_at = iso(datetime.now(UTC))
            self.metrics.gauge("session.rounds", st.round_no)
            self.metrics.observe("session.total", (time.time() - t0) * 1000)
            self.ckpt.save(st)
            self.bus.emit("session.end", Severity.MILESTONE, st.round_no, status=st.status,
                          rounds=st.round_no, root_cause=(st.root_cause or {}).get("label"))
        return DiagnosisResult(state=st, metrics=self.metrics.snapshot(),
                               gateway_stats=self.gw.stats(),
                               events=[e.to_dict() for e in self.bus.buffer])

    # ============================ 辅助 ============================ #
    def _absorb_signals(self, st: SessionState, tool: str, res) -> None:
        if not res.ok:
            return
        if tool == "describe_dataset":
            s = res.summary
            st.signals.update({"total_records": s.get("total_records"),
                               "templates": s.get("templates"),
                               "levels": s.get("levels"), "ts_kinds": s.get("ts_kinds")})
            st.evidence_digest.append(f"components={[r['component'] for r in res.rows]}")
            low = [k for k, v in (s.get("ts_kinds") or {}).items()
                   if k in ("MONOTONIC", "BOOT_RELATIVE", "DERIVED") and v]
            if low:
                st.signals["time_uncertainty"] = low
        elif tool == "phase_timeline":
            st.signals["last_phase"] = res.summary.get("last_phase")
            st.signals["fail_phase"] = res.summary.get("last_phase")
            ends = [str(r.get("ended_at") or "") for r in res.rows if r.get("ended_at")]
            if ends:
                st.signals["_active_until"] = max(ends)
            marks = res.summary.get("abort_markers") or []
            if marks:
                st.signals["abort_marker"] = marks[0]["raw_line"][:200]
                st.evidence_digest.append(marks[0]["raw_line"][:200])
                m = re.search(r"reason=([A-Za-z0-9_x]+)", marks[0]["raw_line"])
                if m:
                    st.signals["abort_reason"] = m.group(1)
                m2 = re.search(r"at\s+([A-Z]+)\s+phase", marks[0]["raw_line"])
                if m2:
                    st.signals["fail_phase"] = m2.group(1)
            for r in res.rows:
                if r.get("errors"):
                    st.evidence_digest.append(
                        f"phase {r['ota_phase']} errors={r['errors']} lines={r['lines']}")
        elif tool == "top_templates":
            for r in res.rows[:25]:
                st.evidence_digest.append(f"[{r['occurrences']}x] {r['template_text'][:160]}")
        elif tool == "find_gaps":
            # 只有发生在"活跃阶段窗口内"且发生在诊断/通信层组件上的静默才是故障信号。
            # 编排层组件（campaign_client/ota_master/flash_agent）天然是事件驱动、
            # 突发式打点——健康会话里它们同样会出现几十秒到几十分钟的静默（例如
            # campaign_client 在下载期间本就不打点），这不是故障。真正有意义的静默
            # 是"本应保持连续协议交互节奏的诊断层组件突然停止响应"（uds_stack/diag_router）。
            active_until = st.signals.get("_active_until")
            comm_layer = {"uds_stack", "diag_router"}
            for r in res.rows[:5]:
                st.evidence_digest.append(
                    f"gap {r['component']} {r['gap_seconds']}s -> {r['after_raw_line'][:100]}")
                in_window = (not active_until) or (str(r.get("gap_start") or "") <= active_until)
                if r["gap_seconds"] >= 30 and in_window and r["component"] in comm_layer:
                    st.signals.setdefault("silent_components", []).append(r["component"])

    def _build_chain(self, st: SessionState) -> list[dict]:
        pool = sorted(st.evidence_pool,
                      key=lambda r: (str(r.get("ts_utc") or ""), int(r.get("line_id") or 0)))
        errs = [r for r in pool if str(r.get("level_norm") or "").upper() in ("ERROR", "FATAL")]
        warns = [r for r in pool if str(r.get("level_norm") or "").upper() == "WARN"]
        ctx = [r for r in pool if r not in errs and r not in warns]
        chain = []
        for i, r in enumerate(errs[:6]):
            chain.append({**_slim(r), "role": "TRIGGER" if i == 0 else "CAUSE"})
        for r in warns[:3]:
            chain.append({**_slim(r), "role": "EFFECT"})
        for r in ctx[:3]:
            chain.append({**_slim(r), "role": "CONTEXT"})
        return chain

    def _root_cause(self, st: SessionState, skill_id: str | None, chain: list[dict]) -> dict:
        sk = self.skills.by_id.get(skill_id or "") or {}
        label = sk.get("root_cause_label")
        if not label:
            for s in reversed(st.used_skills):
                lab = self.skills.label_of(s)
                if lab:
                    label, sk = lab, self.skills.by_id[s]
                    break
        culprit = None
        for c in chain:
            if c.get("role") in ("TRIGGER", "CAUSE") and c.get("component"):
                culprit = c["component"]
                break
        low = [c for c in chain if float(c.get("ts_confidence") or 1.0) < 0.6]
        has_error = any(str(c.get("level_norm") or "").upper() in ("ERROR", "FATAL")
                        for c in chain)
        if not has_error:
            # 证据集中不存在任何错误级日志：诚实地回答"未发现故障证据"，而不是硬套一个根因
            return {"label": "no_fault_found",
                    "title": "未发现故障证据（本次升级日志无错误级事件）",
                    "fail_phase": st.signals.get("fail_phase"), "culprit": None,
                    "abort_reason": None, "evidence_count": len(chain),
                    "time_uncertainty": bool(low), "trigger_hint": None,
                    "actions": ["本次日志未见错误级事件与中止标记，判定为正常完成或故障未落入本次采集范围。",
                                "若确实存在用户可感知的异常，请确认采集时间窗是否覆盖故障时刻。"]}
        return {"label": label or "undetermined",
                "title": sk.get("title") or "未匹配到已知故障模式",
                "fail_phase": st.signals.get("fail_phase"),
                "culprit": culprit,
                "abort_reason": st.signals.get("abort_reason"),
                "evidence_count": len(chain),
                "time_uncertainty": bool(low),
                "trigger_hint": sk.get("trigger"),
                "actions": _suggestions(label, st)}


def _retrieval_query(st: SessionState) -> str:
    """技能召回查询：只取高信号字段，不掺入固定问题模板。

    把 40 条摘要 + 整个 signals JSON 一起灌进去会把中止原因这一最强信号稀释掉，
    实测导致 SK-ECU-SILENT / SK-DEP-VER 这类正确技能根本进不了候选集。
    同理，st.question 是恒定模板（字面含"OTA""升级"），若混入查询会让 SK-PHASE-OVERVIEW
    这类通用编排技能在任何会话（包括健康会话）都稳拿非零分——这会使"候选分全为 0 时
    诚实停止"的判据永远无法触发，是健康会话被拖入无意义下钻循环的根因之一。
    """
    sg = st.signals or {}
    parts: list[str] = []
    for k in ("abort_reason", "abort_marker", "fail_phase"):
        if sg.get(k):
            v = str(sg[k])
            parts += [v, v.replace("_", " ").replace("-", " ")]
    for c in (sg.get("silent_components") or [])[:4]:
        parts.append(f"{c} 静默 无响应 gap")
    for d in st.evidence_digest:
        m = re.match(r"\[(\d+)x\]\s*(.*)", str(d))
        if m and int(m.group(1)) <= 5:            # 只取稀有模板——根因所在
            parts.append(m.group(2)[:160])
    return " ".join(parts)


def _slim(r: dict) -> dict:
    return {k: r.get(k) for k in ("line_id", "row_hash", "ts_utc", "ts_confidence", "ts_kind",
                                  "component", "level_norm", "ota_phase", "ecu_id",
                                  "template_id", "file_path", "line_no")} | {
        "raw_line": str(r.get("raw_line") or r.get("preview") or "")[:300]}


def _signal_terms(st: SessionState) -> list[str]:
    terms = set()
    for k in ("abort_reason", "fail_phase"):
        if st.signals.get(k):
            terms.add(str(st.signals[k]).lower())
    for d in st.evidence_digest[:20]:
        for w in re.findall(r"[a-z_]{4,}|0x[0-9a-f]{2}", str(d).lower()):
            terms.add(w)
    return sorted(terms)[:20]


def _last_productive_skill(st: SessionState) -> str | None:
    for r in reversed(st.rounds):
        if r.productive and r.selected_skill:
            return r.selected_skill
    return st.used_skills[-1] if st.used_skills else None


_SUGGEST = {
    "download_cdn_timeout": ["检查 CDN 节点健康度与回源链路，必要时切换备用域名",
                             "为下载增加断点续传与指数退避重试上限告警"],
    "signature_verify_fail": ["核对签名证书链与固件包一致性，确认发布流水线未混包",
                              "在下发前增加端到端签名预校验"],
    "uds_nrc_programming_failure": ["联系 ECU 供应商核查 Flash 擦写失败块（坏块/寿命）",
                                    "刷写前增加 Flash 健康自检与失败块重映射策略"],
    "power_voltage_drop": ["刷写前强制校验电池 SOC 与外接充电状态，不满足则拒绝启动",
                           "为刷写过程增加低压中断保护与安全回滚"],
    "storage_insufficient": ["下载前预留空间校验，并在不足时先行清理临时分区",
                             "监控车端存储水位，低于阈值时不下发升级任务"],
    "ecu_no_response": ["检查目标 ECU 上下电时序与总线负载，确认诊断会话保活",
                        "为长时间无响应增加自动重试与降级路径"],
    "dependency_mismatch": ["校正整包依赖矩阵，禁止跨版本部分升级",
                            "在 QUERY 阶段前置依赖冲突检查"],
    "activate_rollback": ["核查激活前置条件与 A/B 分区状态一致性",
                          "回滚后自动上报现场快照，避免二次下发同一包"],
    "time_sync_drift": ["修正车端时间同步策略（NTP/GNSS 优先级）",
                        "对时间跳变窗口内的日志标注不确定性，避免误判因果"],
    "log_storm": ["为高频模板增加端侧限流与采样", "在诊断侧对风暴窗口做聚合而非逐行分析"],
    "network_link_flap": ["检查驻网质量与链路切换策略", "为下载增加多链路并发与快速失败"],
}


def _suggestions(label: str | None, st: SessionState) -> list[str]:
    out = list(_SUGGEST.get(label or "", []))
    if st.signals.get("time_uncertainty"):
        out.append("部分日志缺少墙钟时间基准，建议车端在启动早期尽快写入时间锚点行。")
    return out or ["复现该场景并采集完整车端日志后重新诊断。"]


def diagnose(db_path: str | Path, **kw) -> DiagnosisResult:
    g = AgentGraph(db_path, **kw)
    try:
        return g.run()
    finally:
        g.close()
