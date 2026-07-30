"""Stage-8 质量校验：行数对账、时间连续性、解析成功率、置信度分布。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from vela.util.jsonl import write_json


def build_report(con, qa_dir: Path, cfg, pkg_meta: dict | None = None) -> tuple[Path, dict]:
    qa_dir = Path(qa_dir)
    qa_dir.mkdir(parents=True, exist_ok=True)
    q = lambda sql: con.execute(sql).fetchall()

    total = q("SELECT count(*) FROM log_lines")[0][0]
    parsed = q("SELECT count(*) FROM log_lines WHERE parse_status='OK'")[0][0]
    unparsed = q("SELECT count(*) FROM log_lines WHERE parse_status='UNPARSED'")[0][0]
    file_recs = q("SELECT coalesce(sum(record_count),0) FROM files")[0][0]
    ts_null = q("SELECT count(*) FROM log_lines WHERE ts_utc IS NULL")[0][0]
    conf_ok = q("SELECT count(*) FROM log_lines WHERE ts_confidence >= 0.6")[0][0]
    ooo = q("SELECT count(*) FROM log_lines WHERE list_contains(anomaly_flags,'OUT_OF_ORDER')")[0][0]
    jumps = q("SELECT count(*) FROM log_lines WHERE list_contains(anomaly_flags,'CLOCK_JUMP')")[0][0]
    storms = q("SELECT count(*) FROM log_lines WHERE list_contains(anomaly_flags,'STORM')")[0][0]
    multil = q("SELECT count(*) FROM log_lines WHERE line_span > 1")[0][0]
    span = q("SELECT min(ts_utc), max(ts_utc) FROM log_lines")[0]
    comps = q("SELECT component, count(*) n, sum(CASE WHEN level_num>=40 THEN 1 ELSE 0 END) e "
              "FROM log_lines GROUP BY 1 ORDER BY 1")
    kinds = q("SELECT ts_kind, count(*) FROM log_lines GROUP BY 1 ORDER BY 1")
    levels = q("SELECT level_norm, count(*) FROM log_lines GROUP BY 1 ORDER BY 2 DESC")
    parsers = q("SELECT parser_name, count(*) FROM log_lines GROUP BY 1 ORDER BY 2 DESC")
    tmpl = q("SELECT count(*) FROM templates")[0][0]
    dup_top = q("SELECT dup_count, count(*) FROM log_lines GROUP BY 1 ORDER BY 1 DESC LIMIT 3")
    phases = q("SELECT ota_phase, count(*) FROM log_lines WHERE ota_phase IS NOT NULL "
               "GROUP BY 1 ORDER BY 2 DESC")

    max_unparsed = float(cfg.get("qa.max_unparsed_ratio", 0.05))
    min_conf_ratio = float(cfg.get("qa.min_ts_confidence_ratio", 0.80))
    unparsed_ratio = unparsed / total if total else 0.0
    conf_ratio = conf_ok / total if total else 0.0

    checks = [
        ("行数对账 files.record_count == log_lines", file_recs == total,
         f"files={file_recs} log_lines={total}"),
        (f"未解析率 <= {max_unparsed:.0%}", unparsed_ratio <= max_unparsed,
         f"{unparsed_ratio:.4%} ({unparsed}/{total})"),
        (f"ts_confidence>=0.6 占比 >= {min_conf_ratio:.0%}", conf_ratio >= min_conf_ratio,
         f"{conf_ratio:.4%}"),
        ("无缺失时间戳", ts_null == 0, f"ts_utc IS NULL: {ts_null}"),
        ("模板已生成", tmpl > 0, f"templates={tmpl}"),
        ("line_id 稠密且唯一", q("SELECT count(*)=count(DISTINCT line_id) AND min(line_id)=0 "
                                  "AND max(line_id)=count(*)-1 FROM log_lines")[0][0],
         "dense & unique"),
        ("row_hash 全部非空", q("SELECT count(*) FROM log_lines WHERE row_hash IS NULL "
                                 "OR row_hash=''")[0][0] == 0, "anchor integrity"),
    ]
    passed = all(ok for _, ok, _ in checks)

    stats: dict[str, Any] = {
        "total_records": total, "parsed_ok": parsed, "unparsed": unparsed,
        "unparsed_ratio": round(unparsed_ratio, 6),
        "ts_conf_ge_0_6_ratio": round(conf_ratio, 6),
        "ts_null": ts_null, "out_of_order": ooo, "clock_jumps": jumps,
        "storm_lines": storms, "multiline_records": multil, "templates": tmpl,
        "ts_min": str(span[0]), "ts_max": str(span[1]),
        "by_component": {c: n for c, n, _ in comps},
        "errors_by_component": {c: e for c, _, e in comps},
        "by_ts_kind": dict(kinds), "by_level": dict(levels), "by_parser": dict(parsers),
        "by_phase": dict(phases), "checks_passed": passed,
        "checks": [{"name": n, "ok": bool(ok), "detail": d} for n, ok, d in checks],
    }
    write_json(qa_dir / "qa_report.json", stats)

    lines = ["# 证据平面质量报告 (QA Report)", "",
             f"- 总记录数：**{total:,}**（解析成功 {parsed:,} / 未解析 {unparsed:,}，"
             f"未解析率 {unparsed_ratio:.4%}）",
             f"- 时间跨度：`{span[0]}` → `{span[1]}`",
             f"- 模板数：**{tmpl}**（降维比 {total / tmpl:.1f}:1）" if tmpl else "- 模板数：0",
             f"- 时间置信度 ≥0.6 占比：**{conf_ratio:.2%}**",
             f"- 乱序行 {ooo:,} / 时钟跳变 {jumps:,} / 风暴行 {storms:,} / 多行记录 {multil:,}",
             "", "## 校验项", "", "| 校验 | 结果 | 详情 |", "|---|---|---|"]
    for n, ok, d in checks:
        lines.append(f"| {n} | {'✅ PASS' if ok else '❌ FAIL'} | {d} |")

    lines += ["", "## 组件分布", "", "| 组件 | 行数 | ERROR+ |", "|---|---:|---:|"]
    for c, n, e in comps:
        lines.append(f"| {c} | {n:,} | {e:,} |")
    lines += ["", "## 时间基准类型分布（机制五：不确定性来源）", "",
              "| ts_kind | 行数 |", "|---|---:|"]
    for k, n in kinds:
        lines.append(f"| {k} | {n:,} |")
    lines += ["", "## 解析器命中分布", "", "| 解析器 | 行数 |", "|---|---:|"]
    for k, n in parsers:
        lines.append(f"| {k} | {n:,} |")
    lines += ["", "## OTA 阶段分布（前向填充后）", "", "| 阶段 | 行数 |", "|---|---:|"]
    for k, n in phases:
        lines.append(f"| {k} | {n:,} |")
    if dup_top:
        lines += ["", f"- 最高行级重复次数：{dup_top[0][0]}（技术方案 §6.3：重复本身是信息，只标注不删除）"]
    lines += ["", f"**总体结论：{'✅ 全部校验通过' if passed else '❌ 存在未通过项，见上表'}**", ""]

    report_md = qa_dir / "qa_report.md"
    report_md.write_text("\n".join(lines), encoding="utf-8")
    # 返回 JSON 路径：这是程序化消费者（CLI/脚本/评测）实际需要 json.loads 的产物；
    # Markdown 版本同时落盘供人工阅读，路径为同目录下的 qa_report.md。
    report_json = qa_dir / "qa_report.json"
    return report_json, stats
