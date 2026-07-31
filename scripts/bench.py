#!/usr/bin/env python3
"""基准脚本：测量建库吞吐（行/秒）与诊断延迟（P50/P95），供容量规划参考。

用法：
    python scripts/bench.py                      # 用全部 10 个内置场景
    python scripts/bench.py --repeat 3            # 每个场景诊断 3 次取分布
    python scripts/bench.py --provider volcengine --no-cache
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import os                                                            # noqa: E402
os.environ.setdefault("VELA_CONFIG_DIR", str(ROOT / "config"))


def pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    s = sorted(vals)
    k = max(0, min(len(s) - 1, int(round((len(s) - 1) * p))))
    return round(s[k], 3)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", default=str(ROOT / "data" / "dataset"))
    ap.add_argument("--workspace", default=str(ROOT / "workspace" / "bench"))
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--provider", default=None)
    ap.add_argument("--no-cache", action="store_true",
                    help="关闭 LLM 磁盘缓存（真实基线）")
    ap.add_argument("--out", default=None, help="结果 JSON 路径（默认 workspace/bench_result.json）")
    args = ap.parse_args()

    if args.no_cache:
        os.environ["VELA_LLM_CACHE"] = "0"

    from vela.eval.golden import load_golden
    from vela.evidence.pipeline import build

    ds = Path(args.dataset)
    if not any(ds.glob("*.zip")):
        print(f"数据集 {ds} 为空，先运行: vela sim generate --out {ds}")
        return 1
    cases = load_golden(ds)
    print(f"共 {len(cases)} 个场景，每场景诊断 {args.repeat} 次"
          f"（provider={args.provider or 'default'} no_cache={args.no_cache}）\n")

    build_throughput: list[float] = []
    diag_latency: list[float] = []
    costs: list[float] = []
    tokens: list[int] = []
    rows_total = 0

    for gc in cases:
        ws = Path(args.workspace) / gc.case_id
        t0 = time.time()
        r = build(gc.archive, ws, progress=False)
        dt = time.time() - t0
        thr = r.total_records / dt if dt > 0 else 0.0
        build_throughput.append(thr)
        rows_total += r.total_records
        print(f"[建库] {gc.case_id:22s} {r.total_records:>7,} 行  {dt:6.2f}s  "
              f"{thr:>8.0f} 行/秒")

        from vela.agent.graph import AgentGraph
        for i in range(args.repeat):
            t1 = time.time()
            g = AgentGraph(ws / "gold" / "analysis.duckdb", workspace=ws,
                           provider=args.provider, session_id=f"BENCH-{gc.case_id}-{i}",
                           enable_cache=False if args.no_cache else None)
            try:
                res = g.run()
                snap = res.gateway_stats or {}
            finally:
                g.close()
            dt2 = time.time() - t1
            diag_latency.append(dt2)
            cost = float(snap.get("estimated_cost_usd") or 0.0)
            tok = int(snap.get("session_used") or 0)
            costs.append(cost)
            tokens.append(tok)
            print(f"       [诊断 {i+1}/{args.repeat}] {dt2*1000:6.1f}ms  "
                  f"status={res.state.status}  rounds={res.state.round_no}  "
                  f"tokens={tok}  cost_usd={cost}")

    print(f"\n{'='*60}")
    print(f"总行数: {rows_total:,}")
    print(f"建库吞吐  P50={pct(build_throughput,0.5):>8.0f} 行/秒   "
          f"P95={pct(build_throughput,0.95):>8.0f} 行/秒")
    print(f"诊断延迟  P50={pct(diag_latency,0.5)*1000:>8.1f} ms   "
          f"P95={pct(diag_latency,0.95)*1000:>8.1f} ms   "
          f"均值={statistics.mean(diag_latency)*1000:.1f} ms")
    print(f"token/成本 session_used 均值={statistics.mean(tokens) if tokens else 0:.0f}  "
          f"estimated_cost_usd 合计={sum(costs):.6f}")

    out = {
        "rows_total": rows_total,
        "provider": args.provider or os.environ.get("VELA_LLM_PROVIDER", "default"),
        "no_cache": bool(args.no_cache),
        "build_throughput_rows_per_s": {"p50": pct(build_throughput, 0.5),
                                          "p95": pct(build_throughput, 0.95)},
        "diagnose_latency_s": {"p50": pct(diag_latency, 0.5),
                               "p95": pct(diag_latency, 0.95),
                               "mean": round(statistics.mean(diag_latency), 4) if diag_latency else 0.0},
        "diagnose_p95_s": pct(diag_latency, 0.95),
        "session_used_mean": round(statistics.mean(tokens), 2) if tokens else 0,
        "estimated_cost_usd_total": round(sum(costs), 6),
        "estimated_cost_usd_mean": round(statistics.mean(costs), 6) if costs else 0.0,
    }
    out_path = Path(args.out) if args.out else Path(args.workspace) / "bench_result.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n结果已写入: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
