"""可观测平面（事件总线/指标）+ 配置层（budget/skills/config_hash）。"""
from __future__ import annotations

import json

from vela.config import config_hash, load_budget, load_skills
from vela.obs.events import EventBus, Severity
from vela.obs.metrics import Metrics


def test_event_bus_assigns_monotonic_ids():
    bus = EventBus(session_id="s1")
    e1 = bus.emit("a", Severity.PROGRESS)
    e2 = bus.emit("b", Severity.MILESTONE)
    assert e2.event_id == e1.event_id + 1


def test_event_bus_since_filters_by_last_id():
    bus = EventBus(session_id="s1")
    bus.emit("a", Severity.PROGRESS)
    mid = bus.emit("b", Severity.PROGRESS).event_id
    bus.emit("c", Severity.PROGRESS)
    assert [e.kind for e in bus.since(mid)] == ["c"]


def test_event_bus_critical_only_returns_milestone_and_alert():
    bus = EventBus(session_id="s1")
    bus.emit("noise", Severity.PROGRESS)
    bus.emit("important", Severity.MILESTONE)
    bus.emit("bad", Severity.ALERT)
    assert {e.kind for e in bus.critical()} == {"important", "bad"}


def test_event_bus_persists_milestones_to_disk(tmp_path):
    p = tmp_path / "events.jsonl"
    bus = EventBus(p, session_id="s1")
    bus.emit("progress_only", Severity.PROGRESS)
    bus.emit("must_persist", Severity.MILESTONE, key="v")
    lines = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]
    kinds = {l["kind"] for l in lines}
    assert "must_persist" in kinds


def test_event_bus_subscriber_exception_does_not_break_emit():
    bus = EventBus(session_id="s1")
    bus.subscribe(lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
    ev = bus.emit("x", Severity.PROGRESS)      # 不应抛出
    assert ev.kind == "x"


def test_metrics_counter_and_gauge():
    m = Metrics()
    m.inc("calls")
    m.inc("calls", 2)
    m.gauge("ratio", 0.5)
    snap = m.snapshot()
    assert snap["counters"]["calls"] == 3.0
    assert snap["gauges"]["ratio"] == 0.5


def test_metrics_timer_records_percentiles():
    m = Metrics()
    for v in [10, 20, 30, 40, 50]:
        m.observe("op", v)
    snap = m.snapshot()
    assert snap["timers_ms"]["op"]["count"] == 5
    assert snap["timers_ms"]["op"]["p50"] > 0


def test_metrics_timer_context_manager():
    m = Metrics()
    with m.timer("block"):
        pass
    assert m.snapshot()["timers_ms"]["block"]["count"] == 1


def test_metrics_prometheus_format_contains_prefixed_names():
    m = Metrics()
    m.inc("foo.bar")
    text = m.prometheus()
    assert "vela_foo_bar_total" in text


# --------------------------------------------------------------- config
def test_load_budget_poc_is_smaller_than_production():
    poc = load_budget("poc")
    prod = load_budget("production")
    assert poc.round_evidence_tokens < prod.round_evidence_tokens
    assert poc.max_rounds < prod.max_rounds


def test_load_skills_returns_12_sorted_by_id():
    skills = load_skills()
    ids = [s["id"] for s in skills]
    assert len(skills) == 12
    assert ids == sorted(ids)


def test_config_hash_is_deterministic_and_stable_format():
    a = config_hash()
    b = config_hash()
    assert a == b
    assert a.startswith("sha256:") and len(a) == len("sha256:") + 64


def test_config_hash_changes_on_skills_budget_llm_prompts(tmp_path, monkeypatch):
    """METR-03/D-08：四类输入扰动各使 hash 变化；env_checks 不进指纹（D-06）。"""
    import shutil
    from pathlib import Path

    import vela.config as cfg

    root = Path(__file__).resolve().parents[1]
    src_cfg = root / "config"
    prompts = root / "src" / "vela" / "gateway" / "prompts.py"

    def _fresh_copy() -> Path:
        dest = tmp_path / f"cfg_{_fresh_copy.n}"
        _fresh_copy.n += 1
        shutil.copytree(src_cfg, dest)
        return dest

    _fresh_copy.n = 0

    def _hash_at(config_root: Path) -> str:
        monkeypatch.setenv("VELA_CONFIG_DIR", str(config_root))
        cfg.load_yaml.cache_clear()
        return config_hash()

    baseline_dir = _fresh_copy()
    base = _hash_at(baseline_dir)
    assert base.startswith("sha256:")

    # skills — 改已加载字段（注释不进 yaml.safe_load）
    d = _fresh_copy()
    skill_f = d / "skills" / "builtin.yaml"
    text = skill_f.read_text(encoding="utf-8")
    skill_f.write_text(text.replace("version: 3", "version: 999", 1), encoding="utf-8")
    assert _hash_at(d) != base

    # budget.yaml
    d = _fresh_copy()
    bf = d / "budget.yaml"
    bf.write_text(bf.read_text(encoding="utf-8").replace("max_rounds: 30", "max_rounds: 31", 1),
                  encoding="utf-8")
    assert _hash_at(d) != base

    # llm.yaml
    d = _fresh_copy()
    lf = d / "llm.yaml"
    lf.write_text(lf.read_text(encoding="utf-8").replace("temperature: 0.1", "temperature: 0.11", 1),
                  encoding="utf-8")
    assert _hash_at(d) != base

    # env_checks.yaml — must NOT change hash（即便改实质字段）
    d = _fresh_copy()
    ef = d / "env_checks.yaml"
    ef.write_text(ef.read_text(encoding="utf-8") + "\nperturb_key: true\n", encoding="utf-8")
    assert _hash_at(d) == base

    # prompts.py — temporary byte tweak then restore
    original = prompts.read_bytes()
    try:
        prompts.write_bytes(original + b"\n# hash-perturb-prompts\n")
        cfg.load_yaml.cache_clear()
        monkeypatch.setenv("VELA_CONFIG_DIR", str(baseline_dir))
        assert config_hash() != base
    finally:
        prompts.write_bytes(original)
        cfg.load_yaml.cache_clear()
