"""评测执行器：对每个黄金用例跑「建库 → 诊断 → 打分」全链路。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from vela.agent.citations import citation_coverage
from vela.agent.graph import AgentGraph
from vela.eval.golden import GoldenCase, load_golden
from vela.evidence.pipeline import build as build_evidence_db
from vela.evidencepack.verifier import verify_all
from vela.util.jsonl import read_json, write_json


@dataclass
class CaseResult:
    case_id: str
    archive: str
    expected_label: str | None
    predicted_label: str | None
    healthy: bool
    status: str = ""
    top1_hit: bool = False
    phase_hit: bool = False
    component_hit: bool = False
    skill_hit: bool = False
    rounds: int = 0
    llm_calls: int = 0
    llm_tokens: int = 0
    evidence_kept: int = 0
    compression_ratio: float = 1.0
    dangling_rate: float | None = None
    has_citations: bool = False
    citation_ok: bool = False
    citation_coverage: float = 1.0
    illegal_skill_reselect: int = 0
    evidence_pack_ok: bool | None = None
    build_seconds: float = 0.0
    diagnose_seconds: float = 0.0
    records: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass
class EvalResult:
    cases: list[CaseResult] = field(default_factory=list)
    started_at: float = 0.0
    elapsed_s: float = 0.0
    profile: str = ""
    provider: str = ""

    # ---------------- 指标 ---------------- #
    @property
    def faulty(self) -> list[CaseResult]:
        return [c for c in self.cases if not c.healthy]

    @property
    def healthy_cases(self) -> list[CaseResult]:
        return [c for c in self.cases if c.healthy]

    @staticmethod
    def _pct(vals: list[float], p: float) -> float:
        if not vals:
            return 0.0
        s = sorted(vals)
        k = max(0, min(len(s) - 1, int(round((len(s) - 1) * p))))
        return round(s[k], 2)

    def metrics(self) -> dict:
        f = self.faulty
        h = self.healthy_cases
        durs = [c.diagnose_seconds for c in self.cases]
        packs = [c for c in self.cases if c.evidence_pack_ok is not None]
        cited = [c for c in self.cases if c.dangling_rate is not None]
        zero_cite = sum(1 for c in self.cases if not c.has_citations)
        return {
            "cases_total": len(self.cases),
            "cases_faulty": len(f), "cases_healthy": len(h),
            "top1_root_cause_accuracy": _r(sum(c.top1_hit for c in f) / len(f)) if f else 0.0,
            "fail_phase_accuracy": _r(sum(c.phase_hit for c in f) / len(f)) if f else 0.0,
            "culprit_component_hit": _r(sum(c.component_hit for c in f) / len(f)) if f else 0.0,
            "skill_selection_hit": _r(sum(c.skill_hit for c in f) / len(f)) if f else 0.0,
            "healthy_specificity": _r(sum(1 for c in h if _no_fault(c.predicted_label)) / len(h)) if h else 0.0,
            "false_positive_rate": _r(sum(1 for c in h if not _no_fault(c.predicted_label)) / len(h)) if h else 0.0,
            "avg_compression_ratio": _r(sum(c.compression_ratio for c in self.cases) / len(self.cases)) if self.cases else 1.0,
            "dangling_citation_rate": (
                _r(sum(c.dangling_rate for c in cited) / len(cited)) if cited else None
            ),
            "zero_citation_cases": zero_cite,
            "citation_gate_pass_rate": (
                _r(sum(1 for c in self.cases if c.has_citations and c.citation_ok) / len(self.cases))
                if self.cases else 0.0
            ),
            "citation_coverage": (
                _r(sum(c.citation_coverage for c in self.cases) / len(self.cases))
                if self.cases else 1.0
            ),
            "illegal_skill_reselect_total": sum(c.illegal_skill_reselect for c in self.cases),
            "avg_rounds": _r(sum(c.rounds for c in self.cases) / len(self.cases)) if self.cases else 0.0,
            "avg_llm_tokens": int(sum(c.llm_tokens for c in self.cases) / len(self.cases)) if self.cases else 0,
            "evidence_pack_verify_pass": _r(sum(1 for c in packs if c.evidence_pack_ok) / len(packs)) if packs else 0.0,
            "diagnose_p50_s": self._pct(durs, 0.5), "diagnose_p95_s": self._pct(durs, 0.95),
            "total_elapsed_s": round(self.elapsed_s, 2),
            "profile": self.profile, "provider": self.provider,
        }

    def to_dict(self) -> dict:
        return {"metrics": self.metrics(),
                "cases": [c.__dict__ for c in self.cases]}


def _r(x: float) -> float:
    return round(float(x), 4)


_NO_FAULT = {None, "", "undetermined", "no_fault_found"}


def _no_fault(label) -> bool:
    """健康会话的正确表现：不给出任何故障根因标签。"""
    return label in _NO_FAULT


class EvalRunner:
    def __init__(self, dataset_dir: str | Path, workspace: str | Path,
                 provider: str | None = None, profile: str | None = None,
                 verify_packs: bool = True, *,
                 reuse_workspace: bool = False,
                 cache_enabled: bool | None = None):
        self.dataset_dir = Path(dataset_dir)
        self.ws = Path(workspace)
        self.provider = provider
        self.profile = profile
        self.verify_packs = verify_packs
        self.reuse_workspace = bool(reuse_workspace)
        self.cache_enabled = cache_enabled

    def run(self, cases: list[GoldenCase] | None = None,
            progress=None) -> EvalResult:
        cases = cases if cases is not None else load_golden(self.dataset_dir)
        out = EvalResult(started_at=time.time(), profile=self.profile or "-",
                         provider=self.provider or "-")
        t0 = time.time()
        for i, gc in enumerate(cases, 1):
            if progress:
                progress(i, len(cases), gc.case_id)
            out.cases.append(self._one(gc))
        out.elapsed_s = time.time() - t0
        return out

    @staticmethod
    def workspace_reusable(ws: Path) -> bool:
        """METR-07：duckdb + manifest.json + qa checks_passed=True 三条件齐备才可复用。"""
        duck = ws / "gold" / "analysis.duckdb"
        manifest = ws / "manifest.json"
        qa = ws / "qa" / "qa_report.json"
        if not (duck.is_file() and manifest.is_file() and qa.is_file()):
            return False
        try:
            report = read_json(qa)
            return bool(report.get("checks_passed") is True)
        except Exception:
            return False

    def _one(self, gc: GoldenCase) -> CaseResult:
        ws = self.ws / gc.case_id
        cr = CaseResult(case_id=gc.case_id, archive=str(gc.archive),
                        expected_label=gc.expected_label, predicted_label=None,
                        healthy=gc.healthy)
        t0 = time.time()
        reused = False
        try:
            if self.reuse_workspace and self.workspace_reusable(ws):
                reused = True
                cr.notes.append("REUSED_WORKSPACE")
            else:
                br = build_evidence_db(str(gc.archive), str(ws))
                cr.records = br.total_records
        except Exception as e:
            cr.notes.append(f"BUILD_FAILED: {type(e).__name__}: {e}")
            cr.build_seconds = time.time() - t0
            return cr
        cr.build_seconds = time.time() - t0
        if reused and cr.records == 0:
            # 复用路径无 build 结果；records 可留 0
            pass

        t1 = time.time()
        g = AgentGraph(ws / "gold" / "analysis.duckdb", workspace=ws,
                       provider=self.provider, profile=self.profile,
                       session_id=f"EV-{gc.case_id}",
                       enable_cache=self.cache_enabled)
        try:
            res = g.run()
        finally:
            g.close()
        cr.diagnose_seconds = time.time() - t1

        st = res.state
        cr.status = st.status
        cr.predicted_label = (st.root_cause or {}).get("label")
        cr.rounds = st.round_no
        cr.llm_calls = res.gateway_stats.get("calls", 0)
        cr.llm_tokens = res.gateway_stats.get("session_used", 0)
        cr.evidence_kept = len(st.seen_row_hashes)
        ratios = [r.compression.get("compression_ratio", 1.0) for r in st.rounds if r.compression]
        cr.compression_ratio = round(sum(ratios) / len(ratios), 4) if ratios else 1.0
        cc = st.citation_check or {}
        raw_rate = cc.get("dangling_rate")
        cr.dangling_rate = None if raw_rate is None else float(raw_rate)
        cr.has_citations = bool(cc.get("has_citations", False))
        cr.citation_ok = bool(cc.get("ok", False))
        cr.citation_coverage = citation_coverage(st.report_md or "")
        cr.illegal_skill_reselect = int(res.metrics.get("counters", {}).get("plan.illegal_skill", 0))

        if not gc.healthy:
            cr.top1_hit = bool(cr.predicted_label and cr.predicted_label == gc.expected_label)
            cr.phase_hit = bool((st.root_cause or {}).get("fail_phase") == gc.expected_phase)
            comps = {c.get("component") for c in _chain(st)}
            cr.component_hit = bool(comps & set(gc.culprit_components))
            cr.skill_hit = bool(set(st.used_skills) & set(gc.expected_skills))

        if self.verify_packs and st.evidence_pack.get("path"):
            try:
                pack = read_json(st.evidence_pack["path"])
                v = verify_all(pack, archive_path=gc.archive)
                cr.evidence_pack_ok = bool(v["ok"])
                if not v["ok"]:
                    cr.notes.append(f"PACK_VERIFY: {v}")
            except Exception as e:
                cr.notes.append(f"PACK_VERIFY_ERROR: {type(e).__name__}: {e}")
                cr.evidence_pack_ok = False
        return cr


def _chain(st) -> list[dict]:
    return [{"component": c.get("component")} for c in (st.evidence_pool or [])]


def save(result: EvalResult, path: str | Path) -> Path:
    p = Path(path)
    write_json(p, result.to_dict())
    return p
