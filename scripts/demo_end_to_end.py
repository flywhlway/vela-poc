#!/usr/bin/env python3
"""端到端演示脚本：仿真 -> 建库 -> 诊断 -> 证据验证，一条命令跑完整链路。

用法：
    python scripts/demo_end_to_end.py                       # 用内置 S3（UDS NRC 故障）场景演示
    python scripts/demo_end_to_end.py --scenario S6_ECU_SILENT
    python scripts/demo_end_to_end.py --provider volcengine  # 切换到真实大模型（需先配置 .env）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import os                                                            # noqa: E402
os.environ.setdefault("VELA_CONFIG_DIR", str(ROOT / "config"))


def _hr(title: str) -> None:
    print(f"\n{'═' * 78}\n  {title}\n{'═' * 78}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scenario", default="S3_UDS_NRC72")
    ap.add_argument("--provider", default=None, help="mock | volcengine | openai_compat")
    ap.add_argument("--profile", default=None, help="poc | production")
    ap.add_argument("--workspace", default=str(ROOT / "workspace" / "demo"))
    ap.add_argument("--dataset", default=str(ROOT / "data" / "demo_dataset"))
    args = ap.parse_args()

    t0 = time.time()

    _hr(f"第 1 步 / 4：仿真生成场景 {args.scenario}")
    from vela.sim.generate import generate_dataset
    truths = generate_dataset(Path(args.dataset), scenarios=[args.scenario])
    truth = truths[0]
    archive = Path(args.dataset) / truth["archive"]
    print(f"  车型 {truth['model']}  VIN 尾号 ...{truth['vin_last4']}  "
          f"记录数 {truth['total_records']:,}")
    print(f"  归档: {archive}")

    _hr("第 2 步 / 4：建立列式取证库（Bronze → Silver → Gold）")
    from vela.evidence.pipeline import build
    ws = Path(args.workspace)
    r = build(archive, ws, progress=False)
    print(f"  run_id={r.run_id}  files={r.total_files}  records={r.total_records:,}  "
          f"unparsed={r.unparsed_records}  耗时={r.elapsed_s:.1f}s")
    qa = json.loads(r.qa_report.read_text(encoding="utf-8"))
    bad = [c for c in qa["checks"] if not c["ok"]]
    print(f"  QA: {len(qa['checks'])} 项校验，{'全部通过 ✅' if not bad else f'{len(bad)} 项失败 ❌'}"
         f"（详情: {r.qa_report_md}）")

    _hr(f"第 3 步 / 4：Agent 七节点诊断（provider={args.provider or '配置文件 active'}）")
    from vela.agent.graph import AgentGraph
    g = AgentGraph(ws / "gold" / "analysis.duckdb", workspace=ws,
                   provider=args.provider, profile=args.profile, session_id=f"DEMO-{args.scenario}")
    try:
        res = g.run()
    finally:
        g.close()
    st = res.state
    print(f"  状态: {st.status}   轮次: {st.round_no}   技能路径: {' → '.join(st.used_skills)}")
    print(f"  判定根因: {st.root_cause.get('label')}"
          f"（期望: {truth['root_cause_label'] or '(健康)'}）")
    print(f"  引用校验: {st.citation_check.get('valid', 0)}/"
          f"{st.citation_check.get('total_citations', 0)} 有效，"
          f"悬空率 {st.citation_check.get('dangling_rate', 0)}")
    print(f"  模型用量: {res.gateway_stats.get('session_used')} tokens / "
          f"{res.gateway_stats.get('calls')} 次调用")

    _hr("第 4 步 / 4：证据包三级验证（L0 自洽 / L1 库内 / L2 溯源到原始字节）")
    if st.evidence_pack.get("path"):
        import duckdb

        from vela.evidencepack.verifier import verify_all
        from vela.util.jsonl import read_json
        pack = read_json(st.evidence_pack["path"])
        # Agent 会话已在上一步 g.close() 中关闭其数据库连接；L1 校验独立开一个
        # 只读连接，这与 `vela evidence verify` CLI 子命令的做法一致。
        con = duckdb.connect(str(ws / "gold" / "analysis.duckdb"), read_only=True)
        try:
            v = verify_all(pack, con=con, archive_path=archive)
        finally:
            con.close()
        for lv in v["levels"]:
            print(f"  {'✅' if lv['ok'] else '❌'} {lv['level']}: {lv['detail']}")
        print(f"  整体: {'通过 ✅' if v['ok'] else '未通过 ❌'}")
    else:
        print("  （本次未产出证据包：可能是健康会话或证据不足）")

    _hr(f"完成，总耗时 {time.time() - t0:.1f}s")
    print(f"诊断报告:\n{'-'*78}\n{st.report_md}\n{'-'*78}")
    print(f"完整会话状态: {ws / 'sessions' / (st.session_id + '.state.json')}")
    print(f"事件流水: {ws / 'obs' / 'events.jsonl'}")
    print(f"模型审计: {ws / 'obs' / 'llm_audit.jsonl'}")
    return 0 if st.status == "answered" else 1


if __name__ == "__main__":
    raise SystemExit(main())
