"""VELA 统一命令行入口。

    vela sim generate      仿真生成 OTA 车端日志数据集（可写入生产日志则跳过）
    vela build             原始日志压缩包 → 列式取证库（Bronze/Silver/Gold）
    vela query             对已建库执行任意 Agent 工具（人工复核 / 调试）
    vela agent diagnose    运行七节点诊断图，产出报告 + 证据包
    vela eval run          黄金评测集全链路评测
    vela evidence verify   证据包 L0/L1/L2 三级验证
    vela serve             启动本地 HTTP 服务（FastAPI，缺失时降级 stdlib）
    vela doctor            环境自检
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from vela.version import __version__


def _p(obj, limit: int | None = None) -> None:
    s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    print(s[:limit] if limit else s)


# ---------------------------------------------------------------- sim
def cmd_sim(a) -> int:
    from vela.sim.generate import generate_dataset
    from vela.sim.scenarios import SCENARIOS
    if a.list:
        for sid in sorted(SCENARIOS):
            s = SCENARIOS[sid]
            print(f"{sid:22s} {s.zh:24s} phase={s.fail_phase or '-':10s} "
                  f"label={s.root_cause_label or '(healthy)'}")
        return 0
    out = Path(a.out)
    truths = generate_dataset(out, scenarios=a.scenarios, seed=a.seed, density=a.density,
                              chunks=a.chunks, blocks=a.blocks)
    total = sum(t["total_records"] for t in truths)
    print(f"✅ 生成 {len(truths)} 个会话，共 {total:,} 条记录 → {out}")
    for t in truths:
        print(f"   {t['scenario_id']:22s} {t['archive']:34s} {t['total_records']:>7,} 行  "
              f"{t['scenario_zh']}")
    return 0


# -------------------------------------------------------------- build
def cmd_build(a) -> int:
    from vela.evidence.pipeline import build
    r = build(a.archive, a.workspace, keep_raw=a.keep_raw, progress=not a.quiet)
    print(f"✅ run_id={r.run_id}  files={r.total_files}  records={r.total_records:,}  "
          f"unparsed={r.unparsed_records}  {r.elapsed_s:.1f}s")
    print(f"   gold: {r.gold_db}")
    print(f"   qa  : {r.qa_report}  (人读版本: {r.qa_report_md})")
    qa = json.loads(Path(r.qa_report).read_text(encoding="utf-8"))
    bad = [c for c in qa.get("checks", []) if not c.get("ok")]
    print(f"   QA  : {len(qa.get('checks', []))} 项校验，"
          f"{'全部通过 ✅' if not bad else f'{len(bad)} 项未通过 ❌'}")
    for c in bad:
        print(f"        ❌ {c.get('name')}: {c.get('detail')}")
    return 1 if bad else 0


# -------------------------------------------------------------- query
def cmd_query(a) -> int:
    from vela.query.api import LogQueryAPI
    from vela.query.tools import TOOLS_BY_NAME, compact_catalog
    if a.list:
        print(compact_catalog())
        return 0
    if a.tool not in TOOLS_BY_NAME:
        print(f"❌ 未知工具 {a.tool}；用 --list 查看全部", file=sys.stderr)
        return 2
    api = LogQueryAPI(a.db)
    try:
        args = json.loads(a.args) if a.args else {}
        res = api.call(a.tool, **args)
        _p({"ok": res.ok, "error": res.error, "total_matches": res.total_matches,
            "elapsed_ms": res.elapsed_ms, "truncated": res.truncated,
            "next_cursor": res.next_cursor, "notes": res.notes,
            "summary": res.summary, "est_tokens": res.est_tokens,
            "rows": res.rows[: a.limit]})
        return 0 if res.ok else 1
    finally:
        api.close()


# -------------------------------------------------------------- agent
def cmd_agent(a) -> int:
    from vela.agent.graph import AgentGraph
    g = AgentGraph(a.db, workspace=a.workspace, provider=a.provider, profile=a.profile,
                   session_id=a.session_id, question=a.question)
    try:
        res = g.run(max_rounds=a.max_rounds)
    finally:
        g.close()
    st = res.state
    print(f"\n{'='*78}\n状态: {st.status}   轮次: {st.round_no}   "
          f"根因: {(st.root_cause or {}).get('label')}\n"
          f"技能路径: {' → '.join(st.used_skills) or '-'}\n"
          f"证据: {len(st.seen_row_hashes)} 条   引用校验: "
          f"{st.citation_check.get('valid', 0)}/{st.citation_check.get('total_citations', 0)} 有效"
          f"（悬空率 {st.citation_check.get('dangling_rate')}；"
          f"has_citations={st.citation_check.get('has_citations')}；"
          f"ok={st.citation_check.get('ok')}）\n"
          f"模型用量: {res.gateway_stats.get('session_used')} tokens / "
          f"{res.gateway_stats.get('calls')} 次调用\n{'='*78}\n")
    print(st.report_md)
    if st.evidence_pack:
        print(f"\n证据包: {st.evidence_pack.get('path')}")
        print(f"Merkle: {st.evidence_pack.get('merkle_root')}")
    if a.json_out:
        Path(a.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json_out).write_text(
            json.dumps(res.to_dict(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8")
        print(f"\n完整会话已写入: {a.json_out}")
    return 0 if st.status == "answered" else 3


# --------------------------------------------------------------- eval
def cmd_eval(a) -> int:
    from vela.eval.report import render_markdown
    from vela.eval.runner import EvalRunner, save
    from vela.util.jsonl import write_json

    repeat = getattr(a, "repeat", None)
    if repeat is not None and repeat < 2:
        print("错误: --repeat N 要求 N≥2（单次评测请省略 --repeat）", flush=True)
        return 2

    no_cache = bool(getattr(a, "no_cache", False))
    cache_enabled = False if no_cache else None
    if no_cache:
        import os
        os.environ["VELA_LLM_CACHE"] = "0"

    r = EvalRunner(a.dataset, a.workspace, provider=a.provider, profile=a.profile,
                   reuse_workspace=bool(getattr(a, "reuse_workspace", False)),
                   cache_enabled=cache_enabled,
                   ablation=bool(getattr(a, "ablation", False)))

    def prog(i, n, cid):
        print(f"[{i}/{n}] {cid} ...", flush=True)

    runs_metrics: list[dict] = []
    aggregate = None
    if repeat:
        last = None
        for run_i in range(1, repeat + 1):
            print(f"\n=== repeat {run_i}/{repeat} ===", flush=True)
            last = r.run(progress=prog)
            runs_metrics.append(last.metrics())
        from vela.eval.stats import aggregate_metrics
        aggregate = aggregate_metrics(runs_metrics)
        res = last
        # 退出码用聚合均值对照原四条件（D-25 / Plan 04）
        m = {k: (aggregate[k]["mean"] if k in aggregate else runs_metrics[-1].get(k))
             for k in runs_metrics[-1]}
        # 保留非数值键
        for k, v in runs_metrics[-1].items():
            if k not in m:
                m[k] = v
            elif k not in aggregate:
                m[k] = v
    else:
        res = r.run(progress=prog)
        m = res.metrics()

    md = render_markdown(res, runs=runs_metrics or None, aggregate=aggregate)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "eval_report.md").write_text(md, encoding="utf-8")
    payload = res.to_dict()
    if runs_metrics:
        payload["runs"] = runs_metrics
        payload["aggregate"] = aggregate
    # 基线/指纹元数据（D-26）；无密钥
    try:
        from vela.config import config_hash
        payload["meta"] = {
            "config_hash": config_hash(),
            "provider": m.get("provider") or a.provider,
            "profile": m.get("profile") or a.profile,
            "n": repeat or 1,
            "no_cache": no_cache,
            "reuse_workspace": bool(getattr(a, "reuse_workspace", False)),
            "ablation": bool(getattr(a, "ablation", False)),
        }
    except Exception:
        pass
    write_json(out / "eval_result.json", payload)
    # 基线目录友好别名
    if out.name == "baseline" or (out / "README.md").exists():
        (out / "report.md").write_text(md, encoding="utf-8")
        write_json(out / "result.json", payload)
    print("\n" + md)
    print(f"报告: {out/'eval_report.md'}\n明细: {out/'eval_result.json'}")
    dcr = m.get("dangling_citation_rate")
    ok = (m["top1_root_cause_accuracy"] >= 0.8 and m["false_positive_rate"] <= 0.0
          and (dcr is None or dcr <= 0.015)
          and m["illegal_skill_reselect_total"] == 0)
    return 0 if ok else 4


# ----------------------------------------------------------- evidence
def cmd_evidence(a) -> int:
    import duckdb

    from vela.evidencepack.verifier import verify_all
    from vela.util.jsonl import read_json
    pack = read_json(a.pack)
    con = duckdb.connect(a.db, read_only=True) if a.db else None
    try:
        res = verify_all(pack, con=con, archive_path=a.archive)
    finally:
        if con:
            con.close()
    for lv in res["levels"]:
        icon = "✅" if lv["ok"] else "❌"
        print(f"{icon} {lv['level']}: {lv['detail']}")
        for f in lv.get("failures", [])[:5]:
            print(f"     - {f}")
    print(f"\n整体: {'通过 ✅' if res['ok'] else '未通过 ❌'}   evidence_id={res['evidence_id']}")
    return 0 if res["ok"] else 5


# -------------------------------------------------------------- serve
def cmd_serve(a) -> int:
    from vela.server.app import serve
    return serve(db=a.db, workspace=a.workspace, host=a.host, port=a.port)


# ------------------------------------------------------------- doctor
_LOGICAL_MODELS = ("planner", "verifier", "reporter", "distiller")
_REQUIRED_MODS = ("duckdb", "pyarrow", "yaml", "dotenv", "openai")
_OPTIONAL_MODS = ("xxhash", "blake3", "fastapi", "pytest")


def _doctor_item(name: str, ok: bool, detail: str, *,
                 kind: str = "local", warn: bool = False) -> dict:
    return {"name": name, "ok": ok, "detail": detail, "kind": kind, "warn": warn}


def _doctor_icon(c: dict) -> str:
    if not c["ok"]:
        return "❌"
    return "⚠️ " if c.get("warn") else "✅"


def cmd_doctor(a) -> int:
    """环境自检：先收集 list[dict]，再双通道渲染（D-12~D-15 / D-18）。"""
    from vela.config import (config_dir, config_hash, dotenv_report, load_budget,
                             load_skills, load_yaml)
    from vela.envcheck import EnvChecker
    from vela.gateway.base import build_gateway
    from vela.util.hashing import fingerprint_algos

    offline = bool(getattr(a, "offline", False))
    online = bool(getattr(a, "online", False))
    as_json = bool(getattr(a, "as_json", False))
    if offline and online:
        print("❌ --offline 与 --online 不能同时使用", file=sys.stderr)
        return 2

    llm_cfg = load_yaml("llm.yaml")
    provider = os.environ.get("VELA_LLM_PROVIDER") or llm_cfg.get("active", "mock")
    do_probe = online or (not offline and provider != "mock")

    checks: list[dict] = []

    # ---- 本地：配置文件存在性 ----
    for name in ("pipeline.yaml", "parsers.yaml", "ota_phases.yaml",
                 "budget.yaml", "llm.yaml"):
        p = config_dir() / name
        checks.append(_doctor_item(name, p.exists(),
                                   str(p) if p.exists() else "缺失"))

    # ---- 本地：必需 / 可选依赖 ----
    for mod in _REQUIRED_MODS + _OPTIONAL_MODS:
        try:
            __import__(mod)
            checks.append(_doctor_item(f"module:{mod}", True, "已安装"))
        except ImportError:
            if mod in _REQUIRED_MODS:
                checks.append(_doctor_item(
                    f"module:{mod}", False, "必需，缺失"))
            else:
                checks.append(_doctor_item(
                    f"module:{mod}", True, "可选，未安装，将降级", warn=True))

    # ---- 本地：.env 形态（ENV-04 / D-16）----
    for item in EnvChecker().run(provider):
        item = dict(item)
        item.setdefault("warn", False)
        checks.append(item)

    # ---- 连通性四项（D-12 / D-15）----
    gw = build_gateway(provider)
    prov = gw.provider
    chains = {n: prov.models_for(n) for n in _LOGICAL_MODELS}
    mapping_ok = all(bool(chains[n]) for n in _LOGICAL_MODELS)
    mapping_detail = "; ".join(
        f"{n}→{chains[n] if chains[n] else '(空)'}" for n in _LOGICAL_MODELS)

    if not do_probe:
        skip = f"provider={provider}，已跳过网络探测（--online 可强制）"
        for name in ("端点可达", "鉴权有效", "模型可用"):
            checks.append(_doctor_item(name, True, skip,
                                       kind="connectivity", warn=True))
        # 第 4 项零网络本地判定，始终展示四条逻辑模型链（验收需含模型名）
        checks.append(_doctor_item(
            "四个逻辑模型映射完整性", mapping_ok, mapping_detail,
            kind="connectivity", warn=not mapping_ok))
    elif not hasattr(prov, "probe"):
        nodetail = f"provider={provider} 不支持网络探测"
        for name in ("端点可达", "鉴权有效", "模型可用",
                     "四个逻辑模型映射完整性"):
            checks.append(_doctor_item(name, True, nodetail,
                                       kind="connectivity", warn=True))
    else:
        physical: list[str] = []
        seen: set[str] = set()
        for n in _LOGICAL_MODELS:
            for m in chains[n]:
                if m not in seen:
                    seen.add(m)
                    physical.append(m)
        if not physical:
            agg_detail = "无物理模型可探测"
            reachable = authenticated = model_ok = False
        else:
            results = [prov.probe(m) for m in physical]
            reachable = all(r["reachable"] for r in results)
            authenticated = all(r["authenticated"] for r in results)
            model_ok = all(r["model_ok"] for r in results)
            parts = []
            for r in results:
                ek, dt = r.get("error_kind") or "", r.get("detail") or ""
                if ek or dt:
                    parts.append(f"{ek}: {dt}".strip(": ").strip())
            agg_detail = "; ".join(parts) if parts else "ok"
        checks.append(_doctor_item(
            "端点可达", reachable, agg_detail, kind="connectivity"))
        checks.append(_doctor_item(
            "鉴权有效", authenticated, agg_detail, kind="connectivity"))
        checks.append(_doctor_item(
            "模型可用", model_ok, agg_detail, kind="connectivity"))
        checks.append(_doctor_item(
            "四个逻辑模型映射完整性", mapping_ok, mapping_detail,
            kind="connectivity"))

    dotenv = dotenv_report()
    local_ok = all(c["ok"] for c in checks if c["kind"] == "local")
    checks_passed = all(c["ok"] for c in checks)
    chash = config_hash()
    py_ver = sys.version.split()[0]
    cdir = str(config_dir())

    # ---- 双通道渲染（同一 checks 变量，D-18）----
    if as_json:
        _p({
            "vela_version": __version__,
            "python": py_ver,
            "config_dir": cdir,
            "config_hash": chash,
            "provider": provider,
            "probed": do_probe and hasattr(prov, "probe"),
            "dotenv": {
                "path": dotenv.get("path"),
                "loaded": dotenv.get("loaded"),
                "keys": list(dotenv.get("keys") or []),
                "shadowed": list(dotenv.get("shadowed") or []),
            },
            "checks": checks,
            "checks_passed": checks_passed,
            "local_ok": local_ok,
        })
    else:
        print(f"VELA {__version__}   Python {py_ver}")
        print(f"config_dir : {cdir}")
        b = load_budget()
        print(f"skills     : {len(load_skills())} 个")
        print(f"budget     : profile={b.name} round_evidence={b.round_evidence_tokens} "
              f"round_llm={b.round_llm_tokens} max_rounds={b.max_rounds}")
        print(f"algos      : {fingerprint_algos()}")
        print(f"config_hash: {chash}")
        print(f"provider   : {provider}")
        shadowed = dotenv.get("shadowed") or []
        print(f".env       : path={dotenv.get('path')} loaded={dotenv.get('loaded')} "
              f"keys={len(dotenv.get('keys') or [])} shadowed={shadowed}")
        print("checks:")
        for c in checks:
            print(f"  {_doctor_icon(c)} {c['name']}: {c['detail']}")

    # D-14 有意偏离本文件「失败即非零」惯例（build/query/agent/eval/evidence）：
    # 连通性失败标 ❌ 但返 0，避免 run_all.sh:7 set -euo pipefail + :31 第 1 步
    # doctor 因限流/断网中断整条演示链路。消费方：Makefile:41-42、
    # tests/test_cli_and_server.py:9-13。仅 local 硬错误返 1。
    local_bad = any(not c["ok"] for c in checks if c["kind"] == "local")
    return 1 if local_bad else 0


# --------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="vela", description="VELA —— 车端日志证据化诊断 POC")
    ap.add_argument("--version", action="version", version=f"vela {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sim", help="仿真数据集").add_subparsers(dest="sub", required=True)
    g = s.add_parser("generate", help="生成 OTA 日志数据集")
    g.add_argument("--out", default="./data/dataset")
    g.add_argument("--scenarios", nargs="*", default=None)
    g.add_argument("--seed", type=int, default=20260729)
    g.add_argument("--density", type=int, default=10)
    g.add_argument("--chunks", type=int, default=2600)
    g.add_argument("--blocks", type=int, default=260)
    g.add_argument("--list", action="store_true", help="只列出场景")
    g.set_defaults(func=cmd_sim)

    b = sub.add_parser("build", help="建库")
    b.add_argument("archive")
    b.add_argument("workspace")
    b.add_argument("--keep-raw", action="store_true", default=None)
    b.add_argument("--quiet", action="store_true")
    b.set_defaults(func=cmd_build)

    q = sub.add_parser("query", help="执行单个工具")
    q.add_argument("--db", default="")
    q.add_argument("--tool", default="describe_dataset")
    q.add_argument("--args", default="")
    q.add_argument("--limit", type=int, default=20)
    q.add_argument("--list", action="store_true")
    q.set_defaults(func=cmd_query)

    ag = sub.add_parser("agent", help="Agent 诊断").add_subparsers(dest="sub", required=True)
    d = ag.add_parser("diagnose", help="运行诊断图")
    d.add_argument("--db", required=True)
    d.add_argument("--workspace", default=None)
    d.add_argument("--provider", default=None)
    d.add_argument("--profile", default=None)
    d.add_argument("--session-id", default=None)
    d.add_argument("--question", default=None)
    d.add_argument("--max-rounds", type=int, default=None)
    d.add_argument("--json-out", default=None)
    d.set_defaults(func=cmd_agent)

    e = sub.add_parser("eval", help="评测").add_subparsers(dest="sub", required=True)
    er = e.add_parser("run", help="跑黄金评测集")
    er.add_argument("--dataset", default="./data/dataset")
    er.add_argument("--workspace", default="./workspace/eval")
    er.add_argument("--out", default="./workspace/eval/report")
    er.add_argument("--provider", default=None)
    er.add_argument("--profile", default=None)
    er.add_argument("--repeat", type=int, default=None,
                    help="重复评测 N 次（N≥2）并输出均值±标准差与 95%% CI")
    er.add_argument("--reuse-workspace", action="store_true",
                    help="若 workspace 已有可用证据库则跳过重建")
    er.add_argument("--no-cache", action="store_true",
                    help="关闭 LLM 磁盘缓存（基线评测用）")
    er.add_argument("--ablation", action="store_true",
                    help="消融评测：运行时 mask 剔除 golden expected_skills")
    er.set_defaults(func=cmd_eval)

    ev = sub.add_parser("evidence", help="证据包").add_subparsers(dest="sub", required=True)
    vv = ev.add_parser("verify", help="三级验证")
    vv.add_argument("--pack", required=True)
    vv.add_argument("--db", default=None)
    vv.add_argument("--archive", default=None)
    vv.set_defaults(func=cmd_evidence)

    sv = sub.add_parser("serve", help="启动本地服务")
    sv.add_argument("--db", required=True)
    sv.add_argument("--workspace", default=None)
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8848)
    sv.set_defaults(func=cmd_serve)

    dr = sub.add_parser("doctor", help="环境自检")
    dr.add_argument("--offline", action="store_true",
                    help="强制跳过全部网络探测")
    dr.add_argument("--online", action="store_true",
                    help="强制执行网络探测（即使 provider 是 mock）")
    dr.add_argument("--json", dest="as_json", action="store_true",
                    help="以纯 JSON 输出检查结果（供评测/脚本消费）")
    dr.set_defaults(func=cmd_doctor)
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = build_parser()
    a = ap.parse_args(argv)
    return int(a.func(a) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
